"""Descubrimiento y comunicacion entre agentes (A2A 1.0) con registro local.

Paquete transversal: lo usan los agentes para encontrarse y hablarse. No
importa ningun modulo de `modules/` (solo `shared` y el SDK de A2A).
"""
from nanda.client import AUDIT_CAPABILITY, A2AClientError, AuditClient, NandaSettings
from nanda.registry import AgentNotFound, AgentRecord, AgentRegistry, RegistryError

__all__ = [
    "AUDIT_CAPABILITY",
    "A2AClientError",
    "AgentNotFound",
    "AgentRecord",
    "AgentRegistry",
    "AuditClient",
    "NandaSettings",
    "RegistryError",
]
