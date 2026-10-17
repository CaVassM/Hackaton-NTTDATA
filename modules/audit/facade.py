"""AuditFacade: la UNICA puerta del modulo audit.

    from modules.audit import AuditFacade
    result = AuditFacade.from_settings().evaluate(request_dict)

Orquesta: validadores deterministas -> motor de decision -> respuesta segura.
"""
import uuid
from collections.abc import Callable, Sequence
from datetime import date
from typing import TYPE_CHECKING, Any

from modules.audit.config import AuditSettings
from modules.audit.domain import (
    AuditEvent,
    AuditRecord,
    AuditRequest,
    AuditResult,
    ChainReport,
    Finding,
    FindingStatus,
    HumanReview,
    PersistenceNotConfigured,
)
from modules.audit.policy import DecisionEngine, SafeResponseBuilder
from modules.audit.validators import Validator
from shared.logging import JsonlWriter, get_logger

if TYPE_CHECKING:
    from modules.audit.repositories import SqlAuditRepository
    from modules.rag import RagFacade

log = get_logger(__name__)
_GRAVEDAD = {FindingStatus.PASS: 0, FindingStatus.WARN: 1, FindingStatus.FAIL: 2}


class AuditFacade:
    def __init__(
        self,
        *,
        validators: Sequence[Validator],
        engine: DecisionEngine,
        safe_response: SafeResponseBuilder,
        event_log: JsonlWriter | None = None,
        repo: "SqlAuditRepository | None" = None,
        today: Callable[[], date] = date.today,
    ):
        self._validators = list(validators)
        self._engine = engine
        self._safe = safe_response
        self._event_log = event_log
        self._repo = repo
        self._today = today

    @classmethod
    def from_settings(
        cls,
        settings: AuditSettings | None = None,
        *,
        rag: "RagFacade | None" = None,
        today: Callable[[], date] | None = None,
    ) -> "AuditFacade":
        from modules.audit.bootstrap import build_audit_facade

        return build_audit_facade(settings, rag=rag, today=today)

    @property
    def policy_version(self) -> str:
        return self._engine.policy.version

    def evaluate(self, request: AuditRequest | dict[str, Any], *, requested_by: str | None = None) -> AuditResult:
        """Audita afirmacion por afirmacion y decide. Lanza pydantic.ValidationError
        si `request` es un dict que no cumple el contrato."""
        req = request if isinstance(request, AuditRequest) else AuditRequest.model_validate(request)
        if req.effective_date is None:
            req = req.model_copy(update={"effective_date": self._today()})

        findings: list[Finding] = []
        for v in self._validators:
            try:
                findings.extend(v.validate(req))
            except Exception as exc:  # noqa: BLE001
                # Fail-closed: un validador roto NUNCA equivale a "aprobado".
                log.exception("Validador %s fallo", v.name)
                findings.append(Finding(validator=v.name, status=FindingStatus.FAIL, critical=True,
                                        reason=f"Error interno del validador: {type(exc).__name__}"))

        outcome = self._engine.decide(findings, req)
        checks: dict[str, Any] = {
            v.name: {
                "status": max((f.status for f in findings if f.validator == v.name),
                              key=_GRAVEDAD.get, default=FindingStatus.PASS).value,
                "findings": sum(1 for f in findings if f.validator == v.name),
                **({"score": outcome.partial_scores[v.name]} if v.name in outcome.partial_scores else {}),
            }
            for v in self._validators
        }
        checks["requires_human_approval"] = outcome.requires_human_approval
        checks["decision_reason"] = outcome.reason

        result = AuditResult(
            audit_id=str(uuid.uuid4()),
            interaction_id=req.interaction_id,
            decision=outcome.decision,
            score=outcome.score,
            risk_level=outcome.risk_level,
            effective_date=req.effective_date,
            checks=checks,
            findings=findings,
            safe_response=self._safe.build(req, outcome.decision, findings),
            policy_version=self.policy_version,
        )
        log.info("audit %s interaction=%s decision=%s score=%s by=%s", result.audit_id,
                 req.interaction_id, result.decision, result.score, requested_by)
        if self._event_log:
            self._event_log.write({
                "evento": "audit.evaluate", "audit_id": result.audit_id, "interaction_id": req.interaction_id,
                "requested_by": requested_by, "user_id": req.user_id, "role": req.role,
                "decision": result.decision, "score": result.score, "policy_version": result.policy_version,
                "critical": [f.reason for f in findings if f.critical],
            })
        if self._repo is not None:
            self._repo.save_evaluation(req, result, requested_by)
        return result

    # ------------------------------------------------------- persistencia
    def _r(self) -> "SqlAuditRepository":
        if self._repo is None:
            raise PersistenceNotConfigured("Este auditor no tiene persistencia configurada")
        return self._repo

    def get(self, audit_id: str) -> AuditRecord:
        """Auditoria guardada + revisiones humanas (AuditNotFound si no existe)."""
        return self._r().get(audit_id)

    def review(self, audit_id: str, reviewer: str, aprobar: bool, comentario: str | None = None) -> HumanReview:
        """Revision humana (p. ej. de un ESCALATE). Append-only: queda en la cadena."""
        if not reviewer or not reviewer.strip():
            raise ValueError("La revision humana requiere identificar al revisor")
        return self._r().add_review(audit_id, reviewer.strip(), "aprobada" if aprobar else "rechazada", comentario)

    def verify_chain(self) -> ChainReport:
        return self._r().verify_chain()

    def events(self, limit: int = 100) -> list[AuditEvent]:
        return self._r().events(limit)

    def counts(self) -> dict:
        return self._r().counts() if self._repo is not None else {}
