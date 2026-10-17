"""Modulo audit: decide si una respuesta candidata se puede publicar.

INTERFAZ PUBLICA (lo unico que otros modulos pueden importar):

    from modules.audit import AuditFacade, AuditRequest, AuditResult, Decision, ...

Para exponerlo como agente A2A: `uvicorn modules.audit.api.app:app --port 8100`.
"""
from modules.audit.config import AuditSettings
from modules.audit.domain import (
    AuditError,
    AuditRequest,
    AuditResult,
    CandidateResponse,
    Claim,
    ClaimType,
    Decision,
    Finding,
    FindingStatus,
    PolicyError,
)
from modules.audit.facade import AuditFacade

__all__ = [
    "AuditError",
    "AuditFacade",
    "AuditRequest",
    "AuditResult",
    "AuditSettings",
    "CandidateResponse",
    "Claim",
    "ClaimType",
    "Decision",
    "Finding",
    "FindingStatus",
    "PolicyError",
]
