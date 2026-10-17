"""Nucleo determinista: decisiones sobre las normas sinteticas de rag."""
import pytest

from modules.audit import AuditFacade, Decision, FindingStatus
from modules.audit.policy import DecisionEngine, Policy, SafeResponseBuilder
from modules.audit.validators import Validator
from modules.audit.validators.facts import extract_facts
from modules.audit.tests.conftest import (
    HOY,
    V_ART2_ORIGINAL,
    V_ART2_VIGENTE,
    V_PROYECTO,
    audit_request,
    claim,
)

CASOS = [
    ("a_cita_vigente", [claim("c1", "El plazo máximo de atención es de 15 días calendario.", evidence=[V_ART2_VIGENTE])],
     None, None, Decision.ALLOW),
    ("b_version_inexistente", [claim("c1", "El plazo es de 15 días.", evidence=[999])], None, None, Decision.BLOCK),
    ("c1_no_vigente_en_fecha", [claim("c1", "El plazo es de 30 días.", evidence=[V_ART2_ORIGINAL])],
     None, None, Decision.BLOCK),
    ("c2_vigente_pero_modificada", [claim("c1", "El plazo es de 30 días.", evidence=[V_ART2_ORIGINAL])],
     None, "2026-06-01", Decision.WARN),
    ("d_proyecto", [claim("c1", "El plazo es de 10 días.", evidence=[V_PROYECTO])], None, None, Decision.BLOCK),
    ("e_plazo_ausente", [claim("c1", "El plazo es de 10 días.", evidence=[V_ART2_VIGENTE])], None, None, Decision.BLOCK),
    ("f_ros_score_alto", [claim("c1", "El plazo máximo es de 15 días.", evidence=[V_ART2_VIGENTE])],
     "¿Debo presentar un ROS por este cliente?", None, Decision.ESCALATE),
    ("normativa_sin_evidencia", [claim("c1", "El plazo es de 15 días.")], None, None, Decision.BLOCK),
]


@pytest.mark.parametrize(("nombre", "claims", "query", "fecha", "esperada"), CASOS, ids=[c[0] for c in CASOS])
def test_decisiones(audit, nombre, claims, query, fecha, esperada):
    kw = {"query": query} if query else {}
    res = audit.evaluate(audit_request(claims, effective_date=fecha, **kw))
    assert res.decision == esperada, res.checks["decision_reason"]
    assert res.policy_version == "aml-audit-v2"


def test_ros_tiene_score_alto_pero_escala(audit):
    res = audit.evaluate(audit_request(CASOS[6][1], query="¿Debo presentar un ROS?"))
    assert res.score >= 85 and res.decision == Decision.ESCALATE
    assert res.checks["requires_human_approval"] is True


def test_caso_demo_bloquea_con_detalle_por_afirmacion(audit):
    res = audit.evaluate(audit_request(
        [
            claim("c1", "La operación debe reportarse a la UIF dentro de 24 horas", evidence=[V_ART2_VIGENTE]),
            claim("c2", "porque supera S/ 50,000", "dato_caso"),
            claim("c3", "y representa un riesgo alto", "inferencia"),
        ],
        query="¿Debo reportar esta operación a la UIF?",
    ))
    assert res.decision == Decision.BLOCK  # critico gana a ESCALATE
    c1 = [f for f in res.findings if f.claim_id == "c1" and f.critical]
    assert c1 and "24 hora" in c1[0].reason
    assert {f.claim_id for f in res.findings if f.status == FindingStatus.WARN} >= {"c2", "c3"}
    assert "Pendiente de verificacion" in res.safe_response and "[c1]" in res.safe_response


def test_warn_informa_version_vigente_actual(audit):
    res = audit.evaluate(audit_request(CASOS[3][1], effective_date="2026-06-01"))
    warn = next(f for f in res.findings if f.validator == "regulatory")
    assert warn.status == FindingStatus.WARN and warn.details["latest_version_id"] == V_ART2_VIGENTE


def test_fecha_por_defecto_la_pone_el_codigo(audit):
    assert audit.evaluate(audit_request(CASOS[0][1])).effective_date == HOY


def test_critico_bloquea_aunque_score_alto(audit):
    # Una cita perfecta + una inexistente: score medio-alto, pero hay critico.
    res = audit.evaluate(audit_request([
        CASOS[0][1][0],
        claim("c2", "Y el art. 1 aplica.", evidence=[999]),
    ]))
    assert res.decision == Decision.BLOCK


def test_fail_closed_si_un_validador_revienta(rag, settings):
    class Roto(Validator):
        name = "roto"
        scored = False

        def validate(self, request):
            raise RuntimeError("boom")

    policy = Policy.load(settings.audit_policy_path)
    facade = AuditFacade(validators=[Roto()], engine=DecisionEngine(policy), safe_response=SafeResponseBuilder())
    assert facade.evaluate(audit_request(CASOS[0][1])).decision == Decision.BLOCK


@pytest.mark.parametrize(
    ("texto", "hecho"),
    [
        ("supera S/ 50,000", "monto:s/50000"),
        ("S/50 000.00", "monto:s/50000"),
        ("dentro de 24 horas", "plazo:24 hora"),
        ("quince (15) días calendario", "plazo:15 dia"),
        ("desde el 1 de julio de 2026", "fecha:2026-07-01"),
        ("desde 2026-07-01", "fecha:2026-07-01"),
    ],
)
def test_extraccion_de_cifras(texto, hecho):
    assert hecho in extract_facts(texto)
