from types import SimpleNamespace

import ollama
import pytest

from shared.config import BaseAppSettings
from shared.llm import (
    QUERY_INSTRUCTION,
    OllamaEmbeddingClient,
    OllamaLLMClient,
    RetryPolicy,
    check_ollama_from_settings,
)


class FakeOllama:
    """Registra las llamadas para verificar lo que se manda a Ollama."""

    def __init__(self, reject_think: bool = False):
        self.calls: list[dict] = []
        self.reject_think = reject_think

    def chat(self, **kw):
        self.calls.append(kw)
        if self.reject_think and kw.get("think") is not None:
            raise ollama.ResponseError("model does not support thinking", 400)
        return SimpleNamespace(message=SimpleNamespace(content='{"x": 1}'))

    def embed(self, model, input):
        self.calls.append({"input": input})
        return SimpleNamespace(embeddings=[[0.0, 1.0] for _ in input])


def test_think_default_y_override_por_llamada():
    fake = FakeOllama()
    llm = OllamaLLMClient("m", default_think=False, client=fake)
    llm.chat([{"role": "user", "content": "hola"}])
    llm.chat([{"role": "user", "content": "hola"}], think=True)
    assert [c["think"] for c in fake.calls] == [False, True]


def test_modelo_sin_think_se_degrada_sin_romper():
    fake = FakeOllama(reject_think=True)
    llm = OllamaLLMClient("gemma", client=fake)
    assert llm.chat_json([{"role": "user", "content": "x"}], {"type": "object"}) == {"x": 1}
    llm.chat([{"role": "user", "content": "y"}])
    # think=None es "no enviar": Ollama lo trata igual que omitirlo.
    assert fake.calls[-1].get("think") is None


def test_embed_query_antepone_instruccion_y_documents_no():
    fake = FakeOllama()
    emb = OllamaEmbeddingClient("e", client=fake)
    emb.embed_documents(["doc"])
    emb.embed_query("pregunta")
    assert fake.calls[0]["input"] == ["doc"]
    assert fake.calls[1]["input"] == [QUERY_INSTRUCTION + "pregunta"]


def test_retry_no_reintenta_errores_4xx():
    n = {"calls": 0}

    def boom():
        n["calls"] += 1
        raise ollama.ResponseError("not found", 404)

    with pytest.raises(ollama.ResponseError):
        RetryPolicy(max_retries=3, backoff_s=0).run(boom, what="t")
    assert n["calls"] == 1


@pytest.mark.ollama
def test_healthcheck_ollama():
    report = check_ollama_from_settings(BaseAppSettings())
    if not report.reachable:
        pytest.skip(f"Ollama no esta corriendo: {report.error}")
    assert report.ok, f"Faltan modelos: {report.missing} (ollama pull ...)"
