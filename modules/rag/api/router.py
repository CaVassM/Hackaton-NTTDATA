"""Controladores delgados: validan entrada, delegan en RagFacade, mapean salida.

Endpoints sincronos a proposito: la fachada bloquea (SQLite, Ollama) y FastAPI
los ejecuta en su threadpool sin bloquear el event loop.
"""
from collections.abc import Callable
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from modules.rag.api.schemas import (
    CambiosOut,
    IngestRequest,
    IngestResponse,
    SearchRequest,
    SearchResponse,
    VersionOut,
    VigenteEnResponse,
    VigenteResponse,
)
from modules.rag.domain import (
    ArticuloNoEncontrado,
    IngestaError,
    NormaNoEncontrada,
    RagError,
    VersionNoEncontrada,
)
from modules.rag.facade import RagFacade

_NOT_FOUND = (NormaNoEncontrada, ArticuloNoEncontrado, VersionNoEncontrada)


def _http(exc: RagError) -> HTTPException:
    if isinstance(exc, _NOT_FOUND):
        return HTTPException(404, f"{type(exc).__name__}: {exc}")
    return HTTPException(400, str(exc))


def create_rag_router(get_facade: Callable[[], RagFacade]) -> APIRouter:
    """`get_facade` lo provee la app anfitriona (p. ej. lee app.state)."""
    router = APIRouter(prefix="/rag", tags=["rag"])
    Facade = Depends(get_facade)

    @router.post("/ingest", response_model=IngestResponse)
    def ingest(body: IngestRequest, rag: RagFacade = Facade):
        raw = rag.settings.rag_raw_dir.resolve()
        target = (raw / body.ruta).resolve() if body.ruta else raw
        # La API solo ingesta dentro de data/raw (el CLI acepta cualquier ruta).
        if not target.is_relative_to(raw):
            raise HTTPException(400, "La ruta debe estar dentro de data/raw")
        try:
            return IngestResponse.model_validate(rag.ingest(Path(target)))
        except IngestaError as exc:
            raise _http(exc) from exc

    @router.post("/search", response_model=SearchResponse)
    def search(body: SearchRequest, rag: RagFacade = Facade):
        try:
            res = rag.search(body.query, body.fecha, body.top_k, body.incluir_proyectos)
        except RagError as exc:
            raise _http(exc) from exc
        return SearchResponse.model_validate(res)

    @router.get("/vigente", response_model=VigenteResponse)
    def vigente(
        norma: str = Query(..., examples=["Resolución SBS N° 1234-2025"]),
        articulo: str = Query(..., examples=["2"]),
        fecha: date | None = None,
        rag: RagFacade = Facade,
    ):
        efectiva = fecha or rag.hoy()
        try:
            v = rag.texto_vigente(norma, articulo, efectiva)
        except RagError as exc:
            raise _http(exc) from exc
        return VigenteResponse(
            norma=norma, articulo=articulo, fecha=efectiva, fecha_por_defecto=fecha is None,
            version=VersionOut.model_validate(v) if v else None,
        )

    @router.get("/historial", response_model=list[VersionOut])
    def historial(norma: str, articulo: str, rag: RagFacade = Facade):
        try:
            return [VersionOut.model_validate(v) for v in rag.historial(norma, articulo)]
        except RagError as exc:
            raise _http(exc) from exc

    @router.get("/cambios", response_model=CambiosOut)
    def cambios(norma: str, rag: RagFacade = Facade):
        try:
            return CambiosOut.model_validate(rag.cambios_por_norma(norma))
        except RagError as exc:
            raise _http(exc) from exc

    @router.get("/version/{version_id}", response_model=VersionOut)
    def version(version_id: int, rag: RagFacade = Facade):
        try:
            return VersionOut.model_validate(rag.get_version(version_id))
        except RagError as exc:
            raise _http(exc) from exc

    @router.get("/version/{version_id}/vigente", response_model=VigenteEnResponse)
    def version_vigente_en(version_id: int, fecha: date, rag: RagFacade = Facade):
        try:
            return VigenteEnResponse(version_id=version_id, fecha=fecha, vigente=rag.vigente_en(version_id, fecha))
        except RagError as exc:
            raise _http(exc) from exc

    @router.get("/version/{version_id}/posteriores", response_model=list[VersionOut])
    def posteriores(version_id: int, rag: RagFacade = Facade):
        try:
            return [VersionOut.model_validate(v) for v in rag.versiones_posteriores(version_id)]
        except RagError as exc:
            raise _http(exc) from exc

    @router.get("/health")
    def health(rag: RagFacade = Facade):
        return rag.health()

    return router
