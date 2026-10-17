"""Puertos de cases. RagFacade y ComplianceFacade los cumplen tal cual (tipado
estructural); la auditoria tiene dos adaptadores (direct | a2a)."""
from datetime import date
from typing import Any, Protocol

from modules.audit import AuditResult
from modules.compliance import EvaluacionCaso, Obligacion
from modules.rag import ResultadoBusqueda, VersionDetalle


class RagGateway(Protocol):
    def search(self, query: str, fecha: Any = None, top_k: int | None = None,
               incluir_proyectos: bool = False, norma: str | None = None) -> ResultadoBusqueda: ...
    def texto_vigente(self, norma: str, articulo: str, fecha: Any = None) -> VersionDetalle | None: ...
    def get_version(self, version_id: int) -> VersionDetalle: ...
    def vigente_en(self, version_id: int, fecha: Any) -> bool: ...
    def versiones_posteriores(self, version_id: int) -> list[VersionDetalle]: ...
    def hoy(self) -> date: ...


class ComplianceGateway(Protocol):
    def evaluar_caso(self, categoria: str, evidencias: list, fecha_corte: date | None = None,
                     codigos: list[str] | None = None) -> EvaluacionCaso: ...
    def obligacion(self, codigo: str) -> Obligacion | None: ...


class AuditGateway(Protocol):
    mode: str

    def evaluate(self, request: dict[str, Any]) -> AuditResult: ...
