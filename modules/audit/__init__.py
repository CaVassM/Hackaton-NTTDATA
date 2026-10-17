"""Modulo audit: decide si una respuesta candidata se puede publicar.

INTERFAZ PUBLICA (lo unico que otros modulos pueden importar):

    from modules.audit import AuditFacade, AuditRequest, AuditResult, Decision, ...

Para exponerlo como agente A2A: `uvicorn modules.audit.api.app:app --port 8100`.
"""
from typing import Any

from modules.audit.config import AuditSettings
from modules.audit.domain import (
    AuditError,
    AuditEvent,
    AuditNotFound,
    AuditRecord,
    AuditRequest,
    AuditResult,
    CandidateResponse,
    ChainReport,
    Claim,
    ClaimType,
    Decision,
    Finding,
    FindingStatus,
    HumanReview,
    PolicyError,
)
from modules.audit.facade import AuditFacade

__all__ = [
    "AuditError",
    "AuditEvent",
    "AuditFacade",
    "AuditNotFound",
    "AuditRecord",
    "AuditRequest",
    "AuditResult",
    "AuditSettings",
    "CandidateResponse",
    "ChainReport",
    "Claim",
    "ClaimType",
    "Decision",
    "Finding",
    "FindingStatus",
    "HumanReview",
    "PolicyError",
    "create_audit_router",
]


def __getattr__(name: str) -> Any:
    # Perezoso: quien solo usa la fachada no necesita cargar FastAPI.
    if name == "create_audit_router":
        from modules.audit.api.router import create_audit_router

        return create_audit_router
    raise AttributeError(name)
