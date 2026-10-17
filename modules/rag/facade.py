"""RagFacade: la UNICA interfaz que los otros modulos usan de `rag`.

    from modules.rag import RagFacade
    rag = RagFacade.from_settings()
    rag.search("plazo de reclamos", fecha="2026-06-01")

Solo delega en los services; no tiene logica de negocio propia mas alla de
validar y normalizar argumentos (fechas como str ISO, top_k por defecto).
"""
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from modules.rag.config import RagSettings
from modules.rag.domain import CambiosNorma, RagError, ResultadoBusqueda, VersionDetalle
from modules.rag.services.answer_service import AnswerService, Respuesta
from modules.rag.services.ingestion_service import IngestionService, IngestReport
from modules.rag.services.retrieval_service import RetrievalService
from modules.rag.services.temporal_service import TemporalService

if TYPE_CHECKING:
    from shared.llm import EmbeddingClient, LLMClient

FechaLike = date | str | None
MAX_TOP_K = 50


def _fecha(value: FechaLike) -> date | None:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise RagError(f"Fecha invalida {value!r}; formato AAAA-MM-DD") from exc


class RagFacade:
    def __init__(
        self,
        *,
        settings: RagSettings,
        ingestion: IngestionService,
        retrieval: RetrievalService,
        temporal: TemporalService,
        answer: AnswerService,
        health_check: Callable[[], dict[str, Any]],
    ):
        self.settings = settings
        self._ingestion = ingestion
        self._retrieval = retrieval
        self._temporal = temporal
        self._answer = answer
        self._health_check = health_check

    @classmethod
    def from_settings(
        cls,
        settings: RagSettings | None = None,
        *,
        embedder: "EmbeddingClient | None" = None,
        llm: "LLMClient | None" = None,
        today: Callable[[], date] | None = None,
    ) -> "RagFacade":
        """Construye el grafo de dependencias. `embedder`, `llm` y `today` son
        inyectables (tests / otros runtimes)."""
        from modules.rag.bootstrap import build_facade

        return build_facade(settings, embedder=embedder, llm=llm, today=today)

    # -------------------------------------------------------------- ingesta
    def ingest(self, path: str | Path | None = None) -> IngestReport:
        return self._ingestion.ingest_path(Path(path) if path else self.settings.rag_raw_dir)

    def reindex(self) -> int:
        """Re-sincroniza Chroma/BM25 desde SQLite. Devuelve versiones embebidas."""
        return self._ingestion.sync_indexes()

    # ------------------------------------------------------------- busqueda
    def search(
        self,
        query: str,
        fecha: FechaLike = None,
        top_k: int | None = None,
        incluir_proyectos: bool = False,
    ) -> ResultadoBusqueda:
        """Busqueda hibrida filtrada por vigencia. Sin fecha => hoy."""
        if not query or not query.strip():
            raise RagError("query vacia")
        if top_k is None:  # `or` convertiria un top_k=0 invalido en el default
            top_k = self.settings.rag_default_top_k
        if not 1 <= top_k <= MAX_TOP_K:
            raise RagError(f"top_k debe estar entre 1 y {MAX_TOP_K}")
        return self._retrieval.search(query.strip(), _fecha(fecha), top_k, incluir_proyectos)

    def answer(self, pregunta: str, fecha: FechaLike = None, top_k: int | None = None) -> Respuesta:
        """Stub extractivo: la generacion con LLM es de otro modulo."""
        return self._answer.answer(pregunta, self.search(pregunta, fecha, top_k))

    # ------------------------------------------------------------ temporal
    def texto_vigente(self, norma: str, articulo: str, fecha: FechaLike = None) -> VersionDetalle | None:
        return self._temporal.texto_vigente(norma, articulo, _fecha(fecha))

    def historial(self, norma: str, articulo: str) -> list[VersionDetalle]:
        return self._temporal.historial(norma, articulo)

    def cambios_por_norma(self, codigo: str) -> CambiosNorma:
        return self._temporal.cambios_por_norma(codigo)

    def get_version(self, version_id: int) -> VersionDetalle:
        """Texto + metadatos (norma, articulo, desde, hasta, estado de la creadora)."""
        return self._temporal.get_version(version_id)

    def vigente_en(self, version_id: int, fecha: FechaLike) -> bool:
        f = _fecha(fecha)
        if f is None:
            raise RagError("vigente_en requiere fecha")
        return self._temporal.vigente_en(version_id, f)

    def versiones_posteriores(self, version_id: int) -> list[VersionDetalle]:
        return self._temporal.versiones_posteriores(version_id)

    # --------------------------------------------------------------- salud
    def hoy(self) -> date:
        """La fecha que el modulo usa como 'hoy' cuando no se pasa fecha."""
        return self._temporal.today()

    def health(self) -> dict[str, Any]:
        return self._health_check()
