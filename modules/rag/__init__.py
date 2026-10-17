"""Modulo RAG temporal sobre normativa SBS.

INTERFAZ PUBLICA (lo unico que otros modulos pueden importar):

    from modules.rag import RagFacade, RagSettings, Cita, VersionDetalle, ...

Todo lo demas (services, repositories, api, bootstrap) es interno y puede
cambiar sin aviso. Un test verifica que ningun otro modulo importe internals.
"""
from typing import TYPE_CHECKING, Any

from modules.rag.config import RagSettings
from modules.rag.domain import (
    Articulo,
    ArticuloNoEncontrado,
    CambiosNorma,
    Cita,
    EstadoNorma,
    Fragmento,
    IngestaError,
    Norma,
    NormaNoEncontrada,
    RagError,
    ResultadoBusqueda,
    Version,
    VersionDetalle,
    VersionNoEncontrada,
)
from modules.rag.facade import RagFacade
from modules.rag.services.answer_service import Respuesta
from modules.rag.services.ingestion_service import IngestReport

if TYPE_CHECKING:
    from modules.rag.api.router import create_rag_router

__all__ = [
    "Articulo",
    "ArticuloNoEncontrado",
    "CambiosNorma",
    "Cita",
    "EstadoNorma",
    "Fragmento",
    "IngestReport",
    "IngestaError",
    "Norma",
    "NormaNoEncontrada",
    "RagError",
    "RagFacade",
    "RagSettings",
    "Respuesta",
    "ResultadoBusqueda",
    "Version",
    "VersionDetalle",
    "VersionNoEncontrada",
    "create_rag_router",
]


def __getattr__(name: str) -> Any:
    # Perezoso: quien solo usa la fachada no necesita cargar FastAPI.
    if name == "create_rag_router":
        from modules.rag.api.router import create_rag_router

        return create_rag_router
    raise AttributeError(name)
