"""Raiz de composicion del modulo audit: unico sitio con implementaciones concretas."""
from collections.abc import Callable
from datetime import date

from modules.audit.config import AuditSettings
from modules.audit.facade import AuditFacade
from modules.audit.policy import DecisionEngine, Policy, SafeResponseBuilder
from modules.audit.validators import CitationValidator, RegulatoryValidator, SensitiveQueryDetector
from modules.rag import RagFacade
from shared.logging import JsonlWriter


def build_audit_facade(
    settings: AuditSettings | None = None,
    *,
    rag: RagFacade | None = None,
    today: Callable[[], date] | None = None,
) -> AuditFacade:
    settings = settings or AuditSettings()
    rag = rag or RagFacade.from_settings()
    policy = Policy.load(settings.audit_policy_path)
    # Orden: deterministas primero. El semantico (groundedness por LLM) ira
    # despues y solo sobre afirmaciones que pasaron estos (roadmap).
    validators = [
        CitationValidator(rag),
        RegulatoryValidator(rag),
        SensitiveQueryDetector(policy.sensitive_patterns),
    ]
    return AuditFacade(
        validators=validators,
        engine=DecisionEngine(policy),
        safe_response=SafeResponseBuilder(),
        event_log=JsonlWriter(settings.audit_log_path),
        # Mismo "hoy" que rag: fechas coherentes entre modulos.
        today=today or rag.hoy,
    )
