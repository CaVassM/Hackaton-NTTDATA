"""Tests de la capa A2A del auditor.

T1  Agent Card en la ruta well-known con la capacidad audit_candidate_response
T2  token valido + agente permitido -> evaluate() y AuditResult por A2A
T4  sin token / token invalido -> 401 y evaluate() NO se llama
T6  agente autenticado pero fuera de la allowlist -> 403 sin evaluar
T7  esquema invalido -> error JSON-RPC sin evaluar
"""
import pytest
from a2a.types import AgentCard, SendMessageResponse
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
from fastapi.testclient import TestClient
from google.protobuf.json_format import ParseDict

from modules.audit import AuditResult, AuditSettings, Decision
from modules.audit.api.app import create_app
from modules.audit.tests.conftest import (
    V_ART2_VIGENTE,
    audit_request,
    auth,
    claim,
    ok_request,
    send_message,
)


# ------------------------------------------------------------------- T1
def test_t1_agent_card_en_ruta_well_known(client):
    assert AGENT_CARD_WELL_KNOWN_PATH == "/.well-known/agent-card.json"  # A2A 1.0 (verificado en el SDK)
    r = client.get(AGENT_CARD_WELL_KNOWN_PATH)  # sin token: el descubrimiento es publico
    assert r.status_code == 200
    card = r.json()
    ParseDict(card, AgentCard())  # valida contra el esquema protobuf oficial
    assert "audit_candidate_response" in {s["id"] for s in card["skills"]}
    (itf,) = card["supportedInterfaces"]
    assert itf["url"].endswith("/a2a") and itf["protocolBinding"] == "JSONRPC" and itf["protocolVersion"] == "1.0"
    assert card["securitySchemes"]["bearer"]["httpAuthSecurityScheme"]["scheme"] == "bearer"
    assert "aml-audit-v2" in card["description"]


# ------------------------------------------------------------------- T2
def test_t2_token_valido_evalua_y_devuelve_audit_result(client, spy):
    r = client.post("/a2a", json=send_message(ok_request(), rpc_id="req-1"), headers=auth("copilot"))
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "req-1" and "error" not in body
    ParseDict(body["result"], SendMessageResponse())  # el cliente oficial del SDK puede parsearlo
    msg = body["result"]["message"]
    assert msg["role"] == "ROLE_AGENT" and msg["metadata"]["skill"] == "audit_candidate_response"
    result = AuditResult.model_validate(next(p["data"] for p in msg["parts"] if "data" in p))
    assert result.decision == Decision.ALLOW and result.policy_version == "aml-audit-v2"
    assert spy.calls == 1


def test_t2_caso_demo_por_a2a_bloquea_con_detalle(client, spy):
    req = audit_request(
        [claim("c1", "La operación debe reportarse a la UIF dentro de 24 horas", evidence=[V_ART2_VIGENTE]),
         claim("c2", "porque supera S/ 50,000", "dato_caso"),
         claim("c3", "y representa un riesgo alto", "inferencia")],
        query="¿Debo reportar esta operación a la UIF?",
    )
    data = client.post("/a2a", json=send_message(req), headers=auth()).json()["result"]["message"]["parts"][0]["data"]
    assert data["decision"] == "BLOCK"
    assert any(f["claim_id"] == "c1" and f["critical"] for f in data["findings"])
    assert spy.calls == 1


# ------------------------------------------------------------------- T4
@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer token-falso"}, {"Authorization": "Basic Y29waWxvdDp4"}, {"Authorization": "Bearer "}],
    ids=["sin_header", "token_invalido", "esquema_basic", "bearer_vacio"],
)
def test_t4_sin_token_o_invalido_401_sin_evaluar(client, spy, headers):
    r = client.post("/a2a", json=send_message(ok_request()), headers=headers)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert spy.calls == 0


def test_t4_sin_tokens_configurados_nadie_entra(spy, tmp_path):
    s = AuditSettings(log_dir=tmp_path, audit_dir=tmp_path / "audit", a2a_agent_tokens={}, a2a_allowed_agents=["copilot"])
    with TestClient(create_app(spy, s)) as c:
        assert c.post("/a2a", json=send_message(ok_request()), headers={"Authorization": "Bearer x"}).status_code == 401
    assert spy.calls == 0


def test_t4_auth_va_antes_que_la_validacion_de_esquema(client, spy):
    # Cuerpo basura y sin token: debe responder 401 (no revelar nada del esquema).
    r = client.post("/a2a", content=b"esto no es json", headers={"Content-Type": "application/json"})
    assert r.status_code == 401 and spy.calls == 0


# ------------------------------------------------------------------- T6
def test_t6_agente_no_permitido_403_sin_evaluar(client, spy):
    r = client.post("/a2a", json=send_message(ok_request()), headers=auth("ui"))
    assert r.status_code == 403 and "ui" in r.json()["detail"]
    assert spy.calls == 0


# ------------------------------------------------------------------- T7
def _sin(d: dict, *path):
    for k in path[:-1]:
        d = d[k]
    del d[path[-1]]


def _bad_requests():
    req = ok_request()
    sin_candidate = ok_request(); _sin(sin_candidate, "candidate")
    tipo_invalido = ok_request(); tipo_invalido["candidate"]["claims"][0]["type"] = "opinion"
    campo_extra = ok_request(); campo_extra["hack"] = True
    evid_texto = ok_request(); evid_texto["candidate"]["claims"][0]["evidence_ids"] = ["seis"]
    sin_claims = ok_request(); sin_claims["candidate"]["claims"] = []
    fecha_mala = ok_request(); fecha_mala["effective_date"] = "31/12/2026"

    params_no_a2a = send_message(req); params_no_a2a["params"]["message"]["campoInventado"] = 1
    sin_datapart = send_message(None, extra_parts=[{"text": "audita esto"}])
    dos_dataparts = send_message(req, extra_parts=[{"data": req}])
    metodo = send_message(req); metodo["method"] = "message/send"
    jsonrpc_v1 = send_message(req); jsonrpc_v1["jsonrpc"] = "1.0"
    return [
        ("auditrequest_sin_candidate", send_message(sin_candidate), -32602),
        ("claim_type_invalido", send_message(tipo_invalido), -32602),
        ("campo_extra", send_message(campo_extra), -32602),
        ("evidence_id_no_entero", send_message(evid_texto), -32602),
        ("claims_vacio", send_message(sin_claims), -32602),
        ("fecha_invalida", send_message(fecha_mala), -32602),
        ("params_no_cumplen_A2A", params_no_a2a, -32602),
        ("sin_datapart", sin_datapart, -32602),
        ("dos_dataparts", dos_dataparts, -32602),
        ("metodo_desconocido", metodo, -32601),
        ("jsonrpc_no_2", jsonrpc_v1, -32600),
    ]


@pytest.mark.parametrize(("nombre", "body", "code"), _bad_requests(), ids=[b[0] for b in _bad_requests()])
def test_t7_esquema_invalido_error_sin_evaluar(client, spy, nombre, body, code):
    r = client.post("/a2a", json=body, headers=auth())
    assert r.status_code == 200  # JSON-RPC: el error va en el cuerpo
    assert r.json()["error"]["code"] == code, r.json()
    assert spy.calls == 0


def test_t7_json_invalido_y_version_no_soportada(client, spy):
    r = client.post("/a2a", content=b"{no json", headers={**auth(), "Content-Type": "application/json"})
    assert r.json()["error"]["code"] == -32700
    r = client.post("/a2a", json=send_message(ok_request()), headers={**auth(), "A2A-Version": "0.3"})
    assert r.json()["error"]["code"] == -32009
    assert spy.calls == 0


def test_t7_detalle_de_validacion_no_filtra_trazas(client):
    bad = ok_request(); bad["candidate"]["claims"][0]["type"] = "opinion"
    err = client.post("/a2a", json=send_message(bad), headers=auth()).json()["error"]
    assert err["data"][0]["loc"][-1] == "type" and "Traceback" not in str(err)
