"""Contrato de entrada/salida del auditor.

A diferencia de rag (dataclasses), aqui el dominio es Pydantic: AuditRequest
llega de otro agente y su validacion de esquema ES regla de dominio (tipos de
afirmacion, ids de evidencia). Sigue siendo puro: sin I/O ni infraestructura.
"""
from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ClaimType(StrEnum):
    NORMATIVA = "normativa"
    DATO_CASO = "dato_caso"
    INFERENCIA = "inferencia"


class Decision(StrEnum):
    ALLOW = "ALLOW"
    WARN = "WARN"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"


class FindingStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class _Strict(BaseModel):
    # Campos desconocidos = error: un agente que manda basura no debe pasar.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Claim(_Strict):
    claim_id: str = Field(..., min_length=1, max_length=64)
    text: str = Field(..., min_length=1, max_length=4000)
    type: ClaimType
    evidence_ids: list[int] = Field(default_factory=list, max_length=20)


class CandidateResponse(_Strict):
    text: str = Field(..., min_length=1, max_length=20000)
    claims: list[Claim] = Field(..., min_length=1, max_length=50)


class AuditRequest(_Strict):
    interaction_id: str = Field(..., min_length=1, max_length=128)
    user_id: str = Field(..., min_length=1, max_length=128)
    role: str = Field(..., min_length=1, max_length=64)
    query: str = Field(..., min_length=1, max_length=4000)
    # None = el CODIGO usa hoy (nunca el LLM ni el cliente implicitamente).
    effective_date: date | None = None
    use_case: str = Field(..., min_length=1, max_length=64)
    candidate: CandidateResponse


class Finding(BaseModel):
    validator: str
    claim_id: str | None = None
    status: FindingStatus
    critical: bool = False
    reason: str
    requires_human_approval: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class AuditResult(BaseModel):
    audit_id: str
    interaction_id: str
    decision: Decision
    score: float = Field(ge=0, le=100)
    risk_level: str
    effective_date: date
    checks: dict[str, Any]
    findings: list[Finding]
    safe_response: str
    policy_version: str


class HumanReview(BaseModel):
    review_id: int
    audit_id: str
    reviewer: str
    decision: str  # aprobada | rechazada
    comment: str | None = None
    created_at: str


class AuditRecord(BaseModel):
    """Auditoria guardada + revisiones humanas (append-only)."""

    result: AuditResult
    reviews: list[HumanReview] = Field(default_factory=list)
    revision_final: str | None = None  # ultima decision humana, si la hubo


class AuditEvent(BaseModel):
    id: int
    ts: str
    actor: str
    action: str
    payload: dict[str, Any]
    prev_hash: str
    hash: str


class ChainReport(BaseModel):
    ok: bool
    eventos: int
    auditorias: int
    primer_error_id: int | None = None
    motivo: str | None = None
    ultimo_hash: str | None = None
