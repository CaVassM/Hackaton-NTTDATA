"""Expedientes en el formato del equipo (id_caso + descripcion_caso)."""
from modules.cases.domain.expediente import COLUMNAS_SALIDA
from modules.cases.tests.conftest import make_cases

FECHAS = (" Registro del expediente: 2026-04-08. Fecha objetivo de atención interna: 2026-04-20. "
          "Fecha de atención registrada: 2026-04-26.")
INDICIOS = "Con el dinero proveniente del tráfico ilícito de drogas se compraron dos inmuebles a nombre de un tercero."
SUSTENTO = ("Se registran operaciones financieras y patrimoniales del sector vinculado al expediente. El titular presenta "
            "contratos, declaraciones tributarias y movimientos bancarios para sustentar la procedencia de los fondos utilizados.")
FALTA = ("El expediente describe una operación de transferencia. Se incluye una referencia parcial a la transacción, pero no "
         "se han incorporado documentos de titularidad.")


def _fila(f, id_caso, texto):
    return f.analizar_expediente({"id_caso": id_caso, "descripcion_caso": texto}).fila


def test_posible_sin_fechas_es_alerta_normativa(stack, tmp_path):
    f, _ = make_cases(stack, tmp_path)
    fila = _fila(f, "E1", INDICIOS)
    assert fila["resultado_esperado"] == "POSIBLE_INCUMPLIMIENTO"
    assert fila["alerta_plazo_interno_esperada"] == "NO_DETERMINABLE"
    assert fila["tipo_alerta_esperada"] == "NORMATIVA"  # regresion: antes caia en NINGUNA


def test_posible_con_fechas_es_ambas_y_calcula_atraso(stack, tmp_path):
    f, _ = make_cases(stack, tmp_path)
    fila = _fila(f, "E2", INDICIOS + FECHAS)
    assert fila["tipo_alerta_esperada"] == "AMBAS" and fila["dias_de_retraso_interno"] == 6
    assert str(fila["fecha_limite_interna"]) == "2026-04-20"


def test_sustentado_y_faltante(stack, tmp_path):
    f, _ = make_cases(stack, tmp_path)
    sin = _fila(f, "E3", SUSTENTO)
    assert sin["resultado_esperado"] == "SIN_INCUMPLIMIENTO_DETECTADO" and sin["tipo_alerta_esperada"] == "NINGUNA"
    falta = _fila(f, "E4", FALTA + FECHAS)
    assert falta["resultado_esperado"] == "INFORMACION_INSUFICIENTE" and falta["tipo_alerta_esperada"] == "PLAZO_INTERNO"


def test_fila_tiene_las_columnas_del_equipo_y_auditoria(stack, tmp_path):
    f, _ = make_cases(stack, tmp_path)
    r = f.analizar_expediente({"id_caso": "E5", "descripcion_caso": INDICIOS})
    assert list(r.as_row())[: len(COLUMNAS_SALIDA)] == COLUMNAS_SALIDA
    assert r.audit_result is not None and r.fila["audit_id"] == r.audit_result.audit_id
    assert r.fila["revision_humana"] == "PENDIENTE"
    detalle = f.listar_expedientes(detalle=True)
    assert {"E5"} <= {e["id_caso"] for e in detalle} and all("fila" in e for e in detalle)
