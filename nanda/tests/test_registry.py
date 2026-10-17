import pytest

from nanda import AgentNotFound, AgentRecord, AgentRegistry, RegistryError
from shared.config import PROJECT_ROOT


def test_register_resolve_y_persistencia(tmp_path):
    path = tmp_path / "registry.yaml"
    reg = AgentRegistry(path)
    reg.register(AgentRecord("auditor", "Auditor", "http://localhost:8100/", ("audit_candidate_response",)))
    reg.register(AgentRecord("copilot", "Copiloto", "http://localhost:8200", ("answer_normative_query",)))

    again = AgentRegistry(path)  # se relee de disco
    a = again.resolve("auditor")
    assert a.url == "http://localhost:8100"  # normaliza la barra final
    assert a.card_url == "http://localhost:8100/.well-known/agent-card.json"
    assert again.list_capabilities() == {
        "audit_candidate_response": ["auditor"],
        "answer_normative_query": ["copilot"],
    }
    assert [r.agent_id for r in again.find_by_capability("audit_candidate_response")] == ["auditor"]


def test_resolve_inexistente_y_sin_sobrescribir(tmp_path):
    reg = AgentRegistry(tmp_path / "r.yaml")
    with pytest.raises(AgentNotFound):
        reg.resolve("nadie")
    reg.register(AgentRecord("auditor", "A", "http://x"))
    with pytest.raises(RegistryError):
        reg.register(AgentRecord("auditor", "B", "http://y"), overwrite=False)


@pytest.mark.parametrize(("aid", "url"), [("Auditor X", "http://x"), ("auditor", "ftp://x")])
def test_record_invalido(aid, url):
    with pytest.raises(RegistryError):
        AgentRecord(aid, "n", url)


def test_registro_versionado_anuncia_al_auditor():
    reg = AgentRegistry(PROJECT_ROOT / "nanda" / "registry.yaml")
    assert "auditor" in reg.list_capabilities()["audit_candidate_response"]
