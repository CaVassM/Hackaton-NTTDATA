"""Raiz de composicion de cases."""
from modules.audit import AuditFacade
from modules.cases.config import CasesSettings
from modules.cases.facade import CasesFacade
from modules.cases.ports import A2AAuditGateway, AuditGateway, ComplianceGateway, DirectAuditGateway, RagGateway
from modules.cases.repositories import SqliteCasesRepository
from modules.cases.services.case_service import CaseService
from modules.cases.services.eventos import CatalogoEventos
from modules.cases.services.expediente_service import ExpedienteService, ReglasExpediente
from modules.cases.services.question_service import QuestionService
from modules.cases.services.summarizer import Summarizer
from shared.llm import LLMClient, OllamaLLMClient


def build_cases_facade(
    settings: CasesSettings | None = None,
    *,
    rag: RagGateway | None = None,
    compliance: ComplianceGateway | None = None,
    audit: AuditFacade | None = None,
    audit_gateway: AuditGateway | None = None,
    llm: LLMClient | None = None,
) -> CasesFacade:
    settings = settings or CasesSettings()
    if rag is None:
        from modules.rag import RagFacade

        rag = RagFacade.from_settings()
    if compliance is None:
        from modules.compliance import ComplianceFacade

        compliance = ComplianceFacade.from_settings(rag=rag)
    if audit_gateway is None:
        if settings.cases_audit_mode == "a2a":
            from nanda import AuditClient

            audit_gateway = A2AAuditGateway(AuditClient.from_env())
        else:
            # Politica por defecto del auditor: aml-audit-v2 (con techo exposicion_potencial).
            audit_gateway = DirectAuditGateway(audit or AuditFacade.from_settings(rag=rag))
    llm = llm or OllamaLLMClient.from_settings(settings)

    repo = SqliteCasesRepository(settings.sqlite_path)
    repo.init_schema()
    catalogo = CatalogoEventos(settings.eventos_path)
    return CasesFacade(
        settings=settings,
        cases=CaseService(rag, compliance, audit_gateway, catalogo, Summarizer(llm if settings.cases_summary_llm else None)),
        questions=QuestionService(rag, audit_gateway, llm, settings.question_top_k),
        catalogo=catalogo,
        repo=repo,
        audit=audit_gateway,
        expedientes=ExpedienteService(rag, audit_gateway, ReglasExpediente(settings.expedientes_path)),
    )
