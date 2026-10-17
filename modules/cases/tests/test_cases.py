import re

import pytest
from pydantic import ValidationError

from modules.audit import Decision
from modules.cases import CaseNotFound, CaseValidationError
from modules.cases.domain import CaseClaim
from modules.cases.services.claim_builder import ClaimBuilder
from modules.cases.services.numbers import numeros, numeros_nuevos
from modules.cases.tests.conftest import caso, make_cases
from shared.config import PROJECT_ROOT


def test_ros_atrasado_escala(stack, tmp_path):
    f, _ = make_cases(stack, tmp_path, texto="El ROS se comunico fuera del plazo.")
    r = f.evaluate(caso())
    (p,) = r.plazos
    assert p.estado == "atrasado" and p.dias_atraso == 4 and p.sujeto_id == "ROS-2026-0115"
    ros = stack["validadas"]["BAN-004"]
    normativas = [c for c in r.claims if c.type == "normativa"]
    assert normativas and all(c.evidence_ids == [ros.version_id] for c in normativas)
    assert r.audit_result.decision == Decision.ESCALATE  # ROS: la IA no decide
    assert r.audit_result.policy_version == "aml-audit-v2" and not r.publicable
    assert r.obligaciones[0].cita.vigente_en_fecha and r.obligaciones[0].cita.articulo == "58"


def test_capacitacion_atrasada_warn(stack, tmp_path):
    f, _ = make_cases(stack, tmp_path, texto="La capacitacion del nuevo ingreso esta vencida.")
    r = f.evaluate(caso(case_id="ING-2026-044", tipo_evento="ingreso_empleado", fecha_evento="2026-08-17",
                        fecha_cumplimiento=None))
    (p,) = r.plazos
    assert p.estado == "atrasado" and p.dias_atraso == 31
    assert r.audit_result.decision == Decision.WARN  # techo exposicion_potencial (dato_caso)
    assert not [x for x in r.audit_result.findings if x.critical] and r.publicable


def test_claim_con_version_no_recuperada_se_rechaza():
    b = ClaimBuilder({69})
    assert b.normativa("texto valido", 69, "obligacion")
    assert not b.normativa("cita inventada", 9999, "obligacion")
    assert not b.add(CaseClaim(claim_id="x", text="dato", type="dato_caso", version_ref=12345, origen="plazo"))
    assert len(b.claims) == 1 and len(b.rechazados) == 2
    assert all(r["motivo"].startswith("version_id no recuperado") for r in b.rechazados)


def test_resumen_con_numero_nuevo_usa_plantilla(stack, tmp_path):
    f, _ = make_cases(stack, tmp_path, texto="El banco tiene 999 dias de atraso y una multa de 500 UIT.")
    r = f.evaluate(caso())
    assert r.resumen_origen == "plantilla" and "999" not in r.resumen
    assert "atraso 4 dias" in r.resumen  # la plantilla sale de los claims


def test_resumen_sin_numeros_nuevos_se_acepta(stack, tmp_path):
    f, _ = make_cases(stack, tmp_path, texto="El caso ROS-2026-0115 tiene un atraso de 4 dias.")
    assert f.evaluate(caso()).resumen_origen == "llm"


def test_obligacion_sin_validar_no_inventa_plazo(stack, tmp_path):
    f, _ = make_cases(stack, tmp_path)
    r = f.evaluate(caso(case_id="REQ-1", tipo_evento="requerimiento_sbs", fecha_evento="2026-09-21",
                        fecha_cumplimiento=None))
    assert r.plazos == [] and r.sin_fundamento and r.exposicion == []
    assert r.obligaciones[0].estado_validacion == "no_encontrada"
    assert any("no se calcula plazo" in c.text for c in r.claims)


def test_pregunta_con_cita_inventada_se_descarta(stack, tmp_path):
    def responder(prompt, schema):
        if schema.__name__ == "Plan":
            return {"accion": "busqueda", "consulta": "reporte de operaciones sospechosas plazo UIF-Perú"}
        return {"respuesta": "Hay que reportar en 3 dias.",
                "citas": [{"version_id": 9999, "texto": "Se reporta en tres dias."},
                          {"version_id": 69, "texto": "La empresa reportara cuando quiera."}]}

    f, _ = make_cases(stack, tmp_path, json_responder=responder)
    q = f.question({"pregunta": "¿En qué plazo se comunica un ROS?", "fecha": "2026-10-17"})
    motivos = {d["motivo"] for d in q.citas_descartadas}
    assert {"version_id no recuperado", "cita no literal"} <= motivos or "version_id no recuperado" in motivos
    recuperados = {c.version_id for c in q.citas}
    assert q.claims and all(set(c.evidence_ids) <= recuperados for c in q.claims)
    assert q.respuesta_origen == "plantilla" and "3 dias" not in q.respuesta  # cifra nueva -> plantilla
    assert q.audit_result is not None


def test_validacion_de_entrada(stack, tmp_path):
    f, _ = make_cases(stack, tmp_path)
    with pytest.raises(CaseValidationError) as e:
        f.evaluate(caso(tipo_evento="inventado"))
    assert "ingreso_empleado" in e.value.valores_validos
    with pytest.raises(ValidationError):
        f.evaluate(caso(fecha_cumplimiento="2026-09-01"))  # antes del evento
    with pytest.raises(ValidationError):
        f.evaluate(caso(rol="gerente"))


def test_batch_csv_persistencia_y_get(stack, tmp_path):
    f, _ = make_cases(stack, tmp_path)
    csv_text = ("case_id,user_id,rol,tipo_evento,fecha_evento,fecha_cumplimiento,monto,moneda,descripcion,fecha_referencia\n"
                "C1,u,analista,ingreso_empleado,2026-08-03,2026-08-28,,PEN,,2026-10-17\n"
                "C2,u,analista,tipo_que_no_existe,2026-08-03,,,PEN,,\n")
    items = f.batch(f.parse_csv(csv_text))
    assert [i.ok for i in items] == [True, False] and "tipo_evento" in items[1].error
    assert items[0].result.plazos[0].estado == "cumplido"
    assert f.get("C1").case.case_id == "C1" and f.listar()[0]["case_id"] == "C1"
    with pytest.raises(CaseNotFound):
        f.get("NO-EXISTE")


def test_guardia_de_numeros():
    assert {50000, 24} <= numeros("S/ 50,000 en veinticuatro horas")
    assert numeros_nuevos("plazo de 15 dias", ["plazo de quince (15) dias"]) == set()
    assert numeros_nuevos("plazo de 10 dias", ["plazo de quince (15) dias"]) == {10}


def test_cases_solo_usa_apis_publicas():
    rx = re.compile(r"^\s*(?:from|import)\s+([\w.]+)", re.MULTILINE)
    permitidos = ("modules.cases", "modules.rag", "modules.audit", "modules.compliance")
    for py in (PROJECT_ROOT / "modules" / "cases").rglob("*.py"):
        for mod in rx.findall(py.read_text(encoding="utf-8")):
            if mod.startswith("modules."):
                assert mod.startswith("modules.cases") or mod in permitidos, (py, mod)
