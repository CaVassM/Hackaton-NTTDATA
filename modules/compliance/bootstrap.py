"""Raiz de composicion del modulo compliance."""
from collections.abc import Callable
from datetime import date

from modules.compliance.config import ComplianceSettings
from modules.compliance.deadlines import DeadlineEngine, load_feriados
from modules.compliance.evidence import CsvEvidenceSource, EvidenceSource
from modules.compliance.exposure import ExposureCalculator
from modules.compliance.extraction.categories import load_categorias
from modules.compliance.extraction.infraction_extractor import InfractionExtractor
from modules.compliance.extraction.llm_cache import CachedStructuredLLM
from modules.compliance.extraction.obligation_extractor import ObligationExtractor
from modules.compliance.facade import ComplianceFacade
from modules.compliance.repositories import SqliteComplianceRepository
from modules.rag import RagFacade
from shared.llm import EmbeddingClient, LLMClient, OllamaEmbeddingClient, OllamaLLMClient
from shared.logging import JsonlWriter


def build_compliance_facade(
    settings: ComplianceSettings | None = None,
    *,
    rag: RagFacade | None = None,
    llm: LLMClient | None = None,
    embedder: EmbeddingClient | None = None,
    evidence: EvidenceSource | None = None,
    today: Callable[[], date] | None = None,
    auditor=None,
) -> ComplianceFacade:
    """`auditor`: objeto con .evaluate(dict) (p. ej. AuditFacade) para auditar el
    reporte antes de mostrarlo. Opcional: se inyecta para no acoplar la ingesta."""
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
        infractions=InfractionExtractor(rag, cached, repo, embedder or OllamaEmbeddingClient.from_settings(settings),
                                        norma=settings.norma_infracciones, top_k=settings.extraction_top_k,
                                        max_numerales=settings.infraction_max_numerales, event_log=event_log),
        evidence=evidence or CsvEvidenceSource(settings.evidence_csv),
        deadlines=DeadlineEngine(load_feriados(settings.feriados_path)),
        exposure=ExposureCalculator(settings.uit_valor),
        today=today or rag.hoy,
        auditor=auditor,
    )
