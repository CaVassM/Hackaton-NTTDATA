"""Fixtures del modulo audit. rag se construye SOLO con su API publica
(RagFacade.from_settings + embedder falso): audit no conoce internals de rag."""
import hashlib
import math
import re
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from modules.audit import AuditFacade, AuditSettings
from modules.audit.api.app import create_app
from modules.rag import RagFacade, RagSettings
from shared.config import PROJECT_ROOT
from shared.llm import EmbeddingClient

SINTETICOS = PROJECT_ROOT / "data" / "raw" / "sinteticos"
HOY = date(2026, 10, 17)
# Version ids que produce la ingesta de los sinteticos (orden determinista):
V_ART2_ORIGINAL = 2  # Res. 1234-2025 art. 2, 30 dias, vigente hasta 2026-07-01
V_ART2_VIGENTE = 6  # art. 2 modificado por Res. 567-2026, 15 dias
V_PROYECTO = 7  # proyecto PR-045-2026 art. 1
TOKENS = {"copilot": "tok-copilot-123", "ui": "tok-ui-456"}  # "ui" autentica pero NO esta autorizado


class HashEmbedder(EmbeddingClient):
    model_name = "fake-hash-audit"

    def _v(self, text: str) -> list[float]:
        v = [0.0] * 128
        for tok in re.findall(r"\w+", text.lower()):
            v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % 128] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_documents(self, texts):
        return [self._v(t) for t in texts]

    def embed_query(self, text):
        return self._v(text)


@pytest.fixture(scope="session")
def rag(tmp_path_factory) -> RagFacade:
    d = tmp_path_factory.mktemp("rag")
    facade = RagFacade.from_settings(
        RagSettings(rag_dir=d / "rag", log_dir=d / "logs", use_reranker=False),
        embedder=HashEmbedder(),
        today=lambda: HOY,
    )
    facade.ingest(SINTETICOS)
    return facade


@pytest.fixture
def settings(tmp_path) -> AuditSettings:
    return AuditSettings(log_dir=tmp_path / "logs", audit_dir=tmp_path / "audit", a2a_agent_tokens=TOKENS,
                         a2a_allowed_agents=["copilot"])


@pytest.fixture
def audit(rag, settings) -> AuditFacade:
    return AuditFacade.from_settings(settings, rag=rag)


class SpyFacade:
    """Envuelve la fachada real y cuenta llamadas a evaluate()."""

    def __init__(self, inner: AuditFacade):
        self.inner = inner
        self.calls = 0

    @property
    def policy_version(self) -> str:
        return self.inner.policy_version

    def evaluate(self, *args, **kwargs):
        self.calls += 1
        return self.inner.evaluate(*args, **kwargs)


@pytest.fixture
def spy(audit) -> SpyFacade:
    return SpyFacade(audit)


@pytest.fixture
def client(spy, settings):
    with TestClient(create_app(spy, settings)) as c:
        yield c


# ------------------------------------------------------------------ builders
def claim(cid: str, text: str, type_: str = "normativa", evidence: list[int] | None = None) -> dict:
    return {"claim_id": cid, "text": text, "type": type_, "evidence_ids": evidence or []}


def audit_request(claims: list[dict], query: str = "¿Cuál es el plazo para atender un reclamo?",
                  effective_date: str | None = None, role: str = "analista") -> dict:
    return {
        "interaction_id": f"int-{uuid.uuid4().hex[:8]}",
        "user_id": "u-001",
        "role": role,
        "query": query,
        "effective_date": effective_date,
        "use_case": "consulta_normativa",
        "candidate": {"text": " ".join(c["text"] for c in claims), "claims": claims},
    }


def send_message(data: dict | None, *, rpc_id: int | str = 1, extra_parts: list | None = None) -> dict:
    parts = ([{"data": data, "mediaType": "application/json"}] if data is not None else []) + (extra_parts or [])
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "method": "SendMessage",
        "params": {"message": {"messageId": str(uuid.uuid4()), "role": "ROLE_USER", "parts": parts}},
    }


def ok_request() -> dict:
    return audit_request([claim("c1", "El plazo máximo de atención es de 15 días calendario.", evidence=[V_ART2_VIGENTE])])


def auth(agent: str = "copilot") -> dict:
    return {"Authorization": f"Bearer {TOKENS[agent]}", "A2A-Version": "1.0"}
