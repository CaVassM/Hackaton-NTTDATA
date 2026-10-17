"""Motor de plazos: determinista, sin LLM."""
from datetime import date

import pytest

from modules.compliance.deadlines import DeadlineEngine, plazo_de, sumar_habiles, sumar_plazo
from modules.compliance.domain import EstadoPlazo, EvidenciaInterna, Obligacion, EvidenciaInvalida
from modules.compliance.evidence import CsvEvidenceSource
from shared.config import PROJECT_ROOT

CORTE = date(2026, 10, 17)


def obl(valor=24, unidad="horas", tipo="calendario", cita="no debe exceder las veinticuatro horas (24)", codigo="BAN-004-05"):
    return Obligacion(None, codigo, codigo[:7], "la empresa", "comunicar el ROS", "calificacion como sospechosa",
                      "24 horas", valor, unidad, tipo, "ROS", cita, 69, "Resolución SBS N° 2660-2015", "58", 0.03, "fake")


def ev(evento, cumplimiento=None, corte=None, codigo="BAN-004"):
    return EvidenciaInterna(codigo, "S1", evento, cumplimiento, corte)


def test_cumplido():
    (r,) = DeadlineEngine().evaluar(obl(), [ev(date(2026, 9, 1), date(2026, 9, 2))], CORTE)
    assert r.estado == EstadoPlazo.CUMPLIDO and r.dias_atraso == 0 and r.fecha_limite == date(2026, 9, 2)


def test_cumplido_fuera_de_plazo_es_atrasado():
    (r,) = DeadlineEngine().evaluar(obl(), [ev(date(2026, 9, 10), date(2026, 9, 15))], CORTE)
    assert r.estado == EstadoPlazo.ATRASADO and r.dias_atraso == 4


def test_pendiente_vencido_es_atrasado_contra_fecha_corte():
    (r,) = DeadlineEngine().evaluar(obl(), [ev(date(2026, 10, 1))], CORTE)
    assert r.estado == EstadoPlazo.ATRASADO and r.dias_atraso == (CORTE - date(2026, 10, 2)).days
    assert r.fecha_referencia == CORTE


def test_por_vencer():
    (r,) = DeadlineEngine().evaluar(obl(10, "dias"), [ev(date(2026, 10, 15))], CORTE)
    assert r.estado == EstadoPlazo.POR_VENCER and r.dias_para_vencer == 8 and r.dias_atraso == 0


def test_sin_evidencia():
    (r,) = DeadlineEngine().evaluar(obl(), [], CORTE)
    assert r.estado == EstadoPlazo.SIN_EVIDENCIA


def test_sin_plazo_definido():
    (r,) = DeadlineEngine().evaluar(obl(None, None, None, cita="deben crear un registro de operaciones"),
                                    [ev(date(2026, 9, 1))], CORTE)
    assert r.estado == EstadoPlazo.SIN_PLAZO_DEFINIDO


def test_dias_habiles_saltan_fines_de_semana_y_feriados():
    # Vie 2026-07-24 + 3 habiles: lun 27, (mar 28 y mie 29 feriados), jue 30, vie 31 -> 31
    feriados = {date(2026, 7, 28), date(2026, 7, 29)}
    assert sumar_habiles(date(2026, 7, 24), 3, feriados) == date(2026, 7, 31)
    (r,) = DeadlineEngine(feriados).evaluar(obl(3, "dias", "habil"), [ev(date(2026, 7, 24), date(2026, 7, 31))], CORTE)
    assert r.estado == EstadoPlazo.CUMPLIDO
    (r,) = DeadlineEngine(set()).evaluar(obl(3, "dias", "habil"), [ev(date(2026, 7, 24), date(2026, 7, 31))], CORTE)
    assert r.estado == EstadoPlazo.ATRASADO and r.dias_atraso == 2  # sin feriados vencia el mie 29


@pytest.mark.parametrize(("inicio", "valor", "unidad", "esperado"), [
    (date(2026, 1, 31), 1, "meses", date(2026, 2, 28)),
    (date(2016, 3, 31), 10, "anios", date(2026, 3, 31)),
    (date(2026, 9, 1), 48, "horas", date(2026, 9, 3)),
])
def test_aritmetica_de_plazos(inicio, valor, unidad, esperado):
    assert sumar_plazo(inicio, valor, unidad, "calendario", set()) == esperado


def test_periodicidad_solo_si_la_cita_la_dice():
    capac = obl(None, "anios", "periodico", cita="deben contar cuando menos con dos (2) capacitaciones especializadas al año")
    assert plazo_de(capac)[:2] == (1, "anios")
    assert plazo_de(obl(None, "anios", "periodico", cita="deben capacitarse periodicamente")) is None


def test_csv_sintetico_y_validacion_estricta(tmp_path):
    filas = CsvEvidenceSource(PROJECT_ROOT / "data" / "raw" / "compliance" / "evidencia_sintetica.csv").load()
    assert {f.obligacion_codigo for f in filas} >= {"BAN-004", "BAN-005", "BAN-007"}
    malo = tmp_path / "e.csv"
    malo.write_text("obligacion_codigo,sujeto_id,fecha_evento\nBAN-004,S1,17/10/2026\n", encoding="utf-8")
    with pytest.raises(EvidenciaInvalida, match="AAAA-MM-DD"):
        CsvEvidenceSource(malo).load()
    sin_col = tmp_path / "f.csv"
    sin_col.write_text("codigo,sujeto\nBAN-004,S1\n", encoding="utf-8")
    with pytest.raises(EvidenciaInvalida, match="Faltan columnas"):
        CsvEvidenceSource(sin_col).load()
