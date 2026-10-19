"""Cliente A2A de punta a punta contra el auditor real (en proceso, sin red).

Este test SI arma el auditor (modules.audit) para tener un servidor real;
el cliente en si (nanda/client.py) no importa nada de modules/.
"""
import pytest
from fastapi.testclient import TestClient

from modules.audit.api.app import create_app
from modules.audit.tests.conftest import TOKENS, V_ART2_VIGENTE, audit_request, claim, ok_request
from nanda import A2AClientError, AgentRecord, AgentRegistry, AuditClient


@pytest.fixture
def registry(tmp_path):
    reg = AgentRegistry(tmp_path / "registry.yaml")
    reg.register(AgentRecord("auditor", "Auditor", "http://localhost:8100", ("audit_candidate_response",)))
    return reg


@pytest.fixture
def server(spy, settings):
    with TestClient(create_app(spy, settings)) as c:  # TestClient es un httpx.Client
        yield c


def test_copiloto_pide_auditoria_y_recibe_resultado(server, registry, spy):
    client = AuditClient(token=TOKENS["copilot"], registry=registry, http=server)
    result = client.request_audit(ok_request())
    assert result["decision"] == "ALLOW" and result["policy_version"] == "aml-audit-v2"
    # Los enteros llegan como enteros (no 6.0) aunque viajen por A2A.
    assert any(f["details"].get("version_id") == V_ART2_VIGENTE for f in result["findings"])
    assert spy.calls == 1


def test_bloqueo_llega_con_respuesta_segura(server, registry):
    client = AuditClient(token=TOKENS["copilot"], registry=registry, http=server)
    res = client.request_audit(audit_request([claim("c1", "El plazo es de 10 días.", evidence=[V_ART2_VIGENTE])]))
    assert res["decision"] == "BLOCK" and "Pendiente de verificacion" in res["safe_response"]


def test_token_invalido_y_agente_no_autorizado(server, registry, spy):
    with pytest.raises(A2AClientError) as e401:
        AuditClient(token="malo", registry=registry, http=server).request_audit(ok_request())
    with pytest.raises(A2AClientError) as e403:
        AuditClient(token=TOKENS["ui"], registry=registry, agent_id="ui", http=server).request_audit(ok_request())
    assert (e401.value.http_status, e403.value.http_status) == (401, 403)
    assert spy.calls == 0


def test_error_de_esquema_se_propaga_con_codigo(server, registry):
    bad = ok_request()
    del bad["candidate"]
    with pytest.raises(A2AClientError) as e:
        AuditClient(token=TOKENS["copilot"], registry=registry, http=server).request_audit(bad)
    assert e.value.code == -32602


def test_sin_auditor_registrado(tmp_path, server):
    client = AuditClient(token="x", registry=AgentRegistry(tmp_path / "vacio.yaml"), http=server)
    with pytest.raises(A2AClientError, match="audit_candidate_response"):
        client.request_audit(ok_request())


def test_sin_token_no_construye():
    with pytest.raises(A2AClientError):
        AuditClient(token="", registry=None)


def test_el_intercambio_del_cliente_real_queda_trazado(server, registry, spy):
    req = ok_request()
    result = AuditClient(token=TOKENS["copilot"], registry=registry, http=server).request_audit(req)
    t = spy.inner.trace(result["audit_id"])
    assert t.canal == "a2a" and t.transporte["agente_declarado"] == t.transporte["agente_autenticado"] == "copilot"
    assert t.transporte["context_id"] == req["interaction_id"] and t.eventos[0].hash_verificado
