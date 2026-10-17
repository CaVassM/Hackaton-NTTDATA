"""Politica v2: techo 'exposicion_potencial' (decision maxima WARN)."""
from modules.audit import AuditFacade, Decision
from modules.audit.config import AuditSettings
from modules.audit.policy import Policy
from modules.audit.tests.conftest import V_ART2_VIGENTE, audit_request, claim

CITA_OK = claim("c1", "El plazo máximo de atención es de 15 días calendario.", evidence=[V_ART2_VIGENTE])
DATO = claim("c2", "Caso R-1: atrasado, 4 dias.", "dato_caso")


def test_dato_caso_lleva_allow_a_warn(audit):
    res = audit.evaluate(audit_request([CITA_OK, DATO]))
    assert res.score >= 85  # sin techo seria ALLOW
    assert res.decision == Decision.WARN and res.risk_level == "medio"
    assert "techo 'exposicion_potencial'" in res.checks["decision_reason"]


def test_use_case_de_compliance_tope_warn_aun_sin_dato_caso(audit):
    req = audit_request([CITA_OK])
    req["use_case"] = "reporte_cumplimiento"
    assert audit.evaluate(req).decision == Decision.WARN


def test_sin_condicion_no_aplica_el_techo(audit):
    assert audit.evaluate(audit_request([CITA_OK])).decision == Decision.ALLOW


def test_ros_sigue_escalando(audit):
    res = audit.evaluate(audit_request([CITA_OK, DATO], query="¿Debo presentar un ROS a la UIF?"))
    assert res.decision == Decision.ESCALATE  # el techo nunca relaja un ESCALATE


def test_critico_sigue_bloqueando(audit):
    res = audit.evaluate(audit_request([claim("c1", "El plazo es de 15 días.", evidence=[999]), DATO]))
    assert res.decision == Decision.BLOCK


def test_politica_v1_se_conserva_sin_techos(rag, tmp_path):
    v1 = AuditSettings().audit_policy_path.with_name("aml-audit-v1.yaml")
    assert Policy.load(v1).techos == () and Policy.load(AuditSettings().audit_policy_path).techos
    facade = AuditFacade.from_settings(AuditSettings(log_dir=tmp_path, audit_dir=tmp_path / "audit", audit_policy_path=v1), rag=rag)
    res = facade.evaluate(audit_request([CITA_OK, DATO]))
    assert res.decision == Decision.ALLOW and res.policy_version == "aml-audit-v1"
