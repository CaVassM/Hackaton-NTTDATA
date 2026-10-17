"""Integracion con Ollama real. Se saltan si Ollama no esta corriendo."""
from datetime import date

import pytest

from modules.rag.tests.conftest import BASE, SINTETICOS, make_facade, make_settings
from shared.llm import OllamaEmbeddingClient, check_ollama_from_settings

pytestmark = pytest.mark.ollama


@pytest.fixture(scope="module")
def ollama_settings(tmp_path_factory):
    s = make_settings(tmp_path_factory.mktemp("ollama"))
    report = check_ollama_from_settings(s)
    if not report.reachable:
        pytest.skip(f"Ollama no esta corriendo en {s.ollama_host}")
    return s, report


def test_healthcheck_ollama(ollama_settings):
    _, report = ollama_settings
    assert report.ok, f"Faltan modelos: {report.missing}. Ejecuta: ollama pull <modelo>"


def test_busqueda_con_embeddings_reales(ollama_settings, tmp_path):
    s, report = ollama_settings
    if not report.models.get(s.embed_model):
        pytest.skip(f"Falta {s.embed_model}")
    rag = make_facade(tmp_path, embedder=OllamaEmbeddingClient.from_settings(s))
    rag.ingest(SINTETICOS)
    assert rag.health()["ok"]
    top = rag.search("¿En cuántos días debe el banco responder un reclamo?", fecha=date(2026, 6, 1), top_k=1)
    c = top.fragmentos[0].cita
    assert (c.norma, c.articulo, c.fue_modificada) == (BASE, "2", True)
    assert "treinta (30)" in top.fragmentos[0].texto
