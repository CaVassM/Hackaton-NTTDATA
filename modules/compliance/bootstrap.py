"""Raiz de composicion del modulo compliance."""
from collections.abc import Callable
from datetime import date

from modules.compliance.config import ComplianceSettings
from modules.compliance.extraction.categories import load_categorias
from modules.compliance.extraction.llm_cache import CachedStructuredLLM
from modules.compliance.extraction.obligation_extractor import ObligationExtractor
from modules.compliance.facade import ComplianceFacade
from modules.compliance.repositories import SqliteComplianceRepository
from modules.rag import RagFacade
from shared.llm import LLMClient, OllamaLLMClient
from shared.logging import JsonlWriter


def build_compliance_facade(
    settings: ComplianceSettings | None = None,
    *,
    rag: RagFacade | None = None,
    llm: LLMClient | None = None,
    today: Callable[[], date] | None = None,
    **extra,
) -> ComplianceFacade:
    settings = settings or ComplianceSettings()
    rag = rag or RagFacade.from_settings()
    repo = SqliteComplianceRepository(settings.sqlite_path)
    repo.init_schema()
    cached = CachedStructuredLLM(
        llm or OllamaLLMClient.from_settings(settings),
        repo,
        think=settings.extraction_think,
        num_ctx=settings.extraction_num_ctx,
    )
    event_log = JsonlWriter(settings.extraction_log_path)
    return ComplianceFacade(
        settings=settings,
        rag=rag,
        repo=repo,
        categorias=load_categorias(settings.categorias_path),
        obligations=ObligationExtractor(rag, cached, repo, norma=settings.norma_obligaciones,
                                        top_k=settings.extraction_top_k, event_log=event_log),
        today=today or rag.hoy,
        **extra,
    )
