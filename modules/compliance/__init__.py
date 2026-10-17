"""Modulo compliance: obligaciones LA/FT, infracciones, plazos y exposicion potencial.

INTERFAZ PUBLICA (lo unico que otros modulos pueden importar):

    from modules.compliance import ComplianceFacade, ComplianceReport, ...
"""
from modules.compliance.config import ComplianceSettings
from modules.compliance.domain import (
    MONTO_NO_DETERMINADO,
    ROTULO_EXPOSICION,
    Categoria,
    ComplianceError,
    Enlace,
    EstadoPlazo,
    EstadoPropuesta,
    EvidenciaInterna,
    EvidenciaInvalida,
    Exposicion,
    Infraccion,
    Obligacion,
    PropuestaNoEncontrada,
    ResultadoPlazo,
    TipoPropuesta,
)
from modules.compliance.evidence import CsvEvidenceSource, EvidenceSource
from modules.compliance.facade import ComplianceFacade
from modules.compliance.reporting import ComplianceReport, EvaluacionCaso, InfraccionReporte, ItemReporte

__all__ = [
    "MONTO_NO_DETERMINADO",
    "ROTULO_EXPOSICION",
    "Categoria",
    "ComplianceError",
    "ComplianceFacade",
    "ComplianceReport",
    "ComplianceSettings",
    "CsvEvidenceSource",
    "Enlace",
    "EstadoPlazo",
    "EstadoPropuesta",
    "EvidenceSource",
    "EvidenciaInterna",
    "EvidenciaInvalida",
    "Exposicion",
    "Infraccion",
    "EvaluacionCaso",
    "InfraccionReporte",
    "ItemReporte",
    "Obligacion",
    "PropuestaNoEncontrada",
    "ResultadoPlazo",
    "TipoPropuesta",
]
__all__ += ["ExtractionJobs", "create_compliance_router"]


def __getattr__(name: str):
    # Perezoso: quien solo usa la fachada no necesita cargar FastAPI.
    if name in ("create_compliance_router", "ExtractionJobs"):
        from modules.compliance.api import router as _r

        return getattr(_r, name)
    raise AttributeError(name)
