import hashlib
import math
from datetime import date
from pathlib import Path

import pytest

from modules.rag import RagFacade, RagSettings
from modules.rag.repositories import tokenize
from shared.config import PROJECT_ROOT
from shared.llm import EmbeddingClient

SINTETICOS = PROJECT_ROOT / "data" / "raw" / "sinteticos"
HOY = date(2026, 10, 17)  # reloj fijo: los tests no dependen de cuando se corran
CAMBIO = date(2026, 7, 1)  # entrada en vigencia de la modificatoria
BASE = "Resolución SBS N° 1234-2025"
MOD = "Resolución SBS N° 567-2026"
PROY = "Proyecto de Resolución SBS PR-045-2026"
# Corpus sintetico: 01 base, 02 modificatoria, 03 proyecto (rag) + 04 anexo SINTETICO de
# infracciones (lo usa compliance; emitido despues, asi sus version_id van al final).
N_ARCHIVOS = 4
N_VERSIONES = 8 + 3  # 3 base + 2 modificatoria + 1 modificada + 2 proyecto + 3 anexo sintetico


class FakeEmbeddingClient(EmbeddingClient):
    """Bolsa de palabras hasheada a 256 dims, normalizada. Determinista y sin
    Ollama, con algo de semantica lexica para que el ranking tenga sentido."""

    model_name = "fake-hash-256"
    DIM = 256

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.DIM
        for tok in tokenize(text):
            v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


def make_settings(tmp_path: Path) -> RagSettings:
    return RagSettings(
        rag_dir=tmp_path / "rag",
        log_dir=tmp_path / "logs",
        rag_raw_dir=PROJECT_ROOT / "data" / "raw",
        use_reranker=False,
    )


def make_facade(tmp_path: Path, embedder: EmbeddingClient | None = None) -> RagFacade:
    return RagFacade.from_settings(
        make_settings(tmp_path), embedder=embedder or FakeEmbeddingClient(), today=lambda: HOY
    )


@pytest.fixture
def empty_rag(tmp_path) -> RagFacade:
    return make_facade(tmp_path)


@pytest.fixture
def rag(empty_rag) -> RagFacade:
    empty_rag.ingest(SINTETICOS)
    return empty_rag


@pytest.fixture
def art2(rag):
    """(version_original, version_modificada) del art. 2 de la norma base."""
    old, new = rag.historial(BASE, "2")
    return old, new
