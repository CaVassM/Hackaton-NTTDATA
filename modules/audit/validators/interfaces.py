"""Contrato comun de validadores y de la fuente de evidencia.

`EvidenceSource` es lo que el auditor necesita de rag. `RagFacade` lo cumple
tal cual (tipado estructural): audit no conoce ningun internal de rag.
"""
from abc import ABC, abstractmethod
from datetime import date
from typing import Protocol

from modules.audit.domain import AuditRequest, Finding
from modules.rag import VersionDetalle


class EvidenceSource(Protocol):
    def get_version(self, version_id: int) -> VersionDetalle: ...
    def vigente_en(self, version_id: int, fecha: date) -> bool: ...
    def versiones_posteriores(self, version_id: int) -> list[VersionDetalle]: ...


class Validator(ABC):
    name: str
    # True = participa en el score determinista (pesos en la politica).
    scored: bool = True

    @abstractmethod
    def validate(self, request: AuditRequest) -> list[Finding]:
        """`request.effective_date` ya viene resuelta por la fachada."""
