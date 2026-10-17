"""Adaptadores de auditoria: en proceso (AuditFacade) o por A2A (cliente nanda)."""
from typing import Any

from modules.audit import AuditFacade, AuditResult
from nanda import AuditClient


class DirectAuditGateway:
    mode = "direct"

    def __init__(self, facade: AuditFacade):
        self.facade = facade

    def evaluate(self, request: dict[str, Any]) -> AuditResult:
        return self.facade.evaluate(request, requested_by="cases")


class A2AAuditGateway:
    """Pide la auditoria al agente auditor (A2A 1.0) descubierto en el registro nanda."""

    mode = "a2a"

    def __init__(self, client: AuditClient):
        self.client = client

    def evaluate(self, request: dict[str, Any]) -> AuditResult:
        return AuditResult.model_validate(self.client.request_audit(request))
