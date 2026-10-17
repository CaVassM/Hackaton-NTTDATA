"""Raiz de composicion: el UNICO sitio que conoce las implementaciones concretas.

Services y fachada reciben dependencias por constructor; aqui se decide cuales.
"""
from collections.abc import Callable
from datetime import date
from typing import Any

from modules.rag.config import RagSettings
from modules.rag.facade import RagFacade
from modules.rag.repositories import (
    Bm25LexicalRepository,
    ChromaVectorRepository,
    SqliteRepository,
    collection_name_for,
)
from modules.rag.services.answer_service import StubAnswerService
from modules.rag.services.ingestion_service import IngestionService
from modules.rag.services.reranker import LLMReranker, NoOpReranker, Reranker
from modules.rag.services.retrieval_service import RetrievalService
from modules.rag.services.temporal_service import TemporalService
from shared.llm import EmbeddingClient, LLMClient, OllamaEmbeddingClient, OllamaLLMClient, check_ollama
from shared.logging import JsonlWriter


def build_facade(
    settings: RagSettings | None = None,
    *,
    embedder: EmbeddingClient | None = None,
    llm: LLMClient | None = None,
    today: Callable[[], date] | None = None,
) -> RagFacade:
    settings = settings or RagSettings()
    today = today or date.today
    embedder = embedder or OllamaEmbeddingClient.from_settings(settings)

    sql = SqliteRepository(settings.sqlite_path)
    sql.init_schema()
    vectors = ChromaVectorRepository(settings.chroma_dir, collection_name_for(embedder.model_name))
    lexical = Bm25LexicalRepository(settings.bm25_path)

    reranker: Reranker = NoOpReranker()
    if settings.use_reranker:
        # El LLM solo se instancia si se usa: el modulo no lo necesita para buscar.
        reranker = LLMReranker(llm or OllamaLLMClient.from_settings(settings))

    retrieval = RetrievalService(
        sql, vectors, lexical, embedder, reranker,
        rrf_k=settings.rag_rrf_k,
        candidates_k=settings.rag_candidates_k,
        search_log=JsonlWriter(settings.search_log_path),
        today=today,
    )

    def health() -> dict[str, Any]:
        models = [embedder.model_name] + ([settings.llm_model] if settings.use_reranker else [])
        report = check_ollama(settings.ollama_host, models) if isinstance(embedder, OllamaEmbeddingClient) else None
        return {
            "ok": report.ok if report else True,
            "ollama": None if report is None else {
                "host": report.host, "reachable": report.reachable, "models": report.models, "error": report.error,
            },
            "indices": {
                "versiones_sql": len(sql.all_detalles()),
                "vectores": vectors.count(),
                "bm25": lexical.count(),
            },
            "embed_model": embedder.model_name,
            "reranker": settings.use_reranker,
        }

    return RagFacade(
        settings=settings,
        ingestion=IngestionService(sql, vectors, lexical, embedder),
        retrieval=retrieval,
        temporal=TemporalService(sql, today=today),
        answer=StubAnswerService(),
        health_check=health,
    )
