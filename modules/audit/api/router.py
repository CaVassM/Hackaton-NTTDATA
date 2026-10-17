"""Router HTTP delgado del auditor (ademas del agente A2A).

    POST /audit/evaluate            AuditRequest -> AuditResult (se persiste)
    GET  /audit/verify-chain        verifica la cadena de hashes
    GET  /audit/events?limit=       ultimos eventos de la cadena
    GET  /audit/{audit_id}          auditoria + revisiones humanas
    POST /audit/{audit_id}/review   revision humana (append-only)
Rutas fijas antes que /{audit_id} para que no las capture.
"""
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from modules.audit.domain import (
    AuditEvent,
    AuditNotFound,
    AuditRecord,
    AuditRequest,
    AuditResult,
    ChainReport,
    HumanReview,
    PersistenceNotConfigured,
)
from modules.audit.facade import AuditFacade


class ReviewRequest(BaseModel):
    reviewer: str = Field(..., min_length=1, max_length=128, examples=["oficial.cumplimiento"])
    aprobar: bool
    comentario: str | None = Field(None, max_length=2000)


def create_audit_router(get_facade: Callable[..., AuditFacade]) -> APIRouter:
    router = APIRouter(prefix="/audit", tags=["audit"])

    def _err(exc: Exception) -> HTTPException:
        if isinstance(exc, AuditNotFound):
            return HTTPException(404, f"Auditoria no encontrada: {exc}")
        if isinstance(exc, PersistenceNotConfigured):
            return HTTPException(503, str(exc))
        return HTTPException(400, str(exc))

    @router.post("/evaluate", response_model=AuditResult)
    def evaluate(body: AuditRequest, facade: AuditFacade = Depends(get_facade)):
        return facade.evaluate(body, requested_by="api")

    @router.get("/verify-chain", response_model=ChainReport)
    def verify_chain(facade: AuditFacade = Depends(get_facade)):
        try:
            return facade.verify_chain()
        except PersistenceNotConfigured as exc:
            raise _err(exc) from exc

    @router.get("/events", response_model=list[AuditEvent])
    def events(limit: int = Query(50, ge=1, le=500), facade: AuditFacade = Depends(get_facade)):
        try:
            return facade.events(limit)
        except PersistenceNotConfigured as exc:
            raise _err(exc) from exc

    @router.get("/{audit_id}", response_model=AuditRecord)
    def get(audit_id: str, facade: AuditFacade = Depends(get_facade)):
        try:
            return facade.get(audit_id)
        except (AuditNotFound, PersistenceNotConfigured) as exc:
            raise _err(exc) from exc

    @router.post("/{audit_id}/review", response_model=HumanReview)
    def review(audit_id: str, body: ReviewRequest, facade: AuditFacade = Depends(get_facade)):
        try:
            return facade.review(audit_id, body.reviewer, body.aprobar, body.comentario)
        except (AuditNotFound, PersistenceNotConfigured, ValueError) as exc:
            raise _err(exc) from exc

    return router
