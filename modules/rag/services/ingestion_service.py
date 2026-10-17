"""Ingesta OFFLINE: archivos -> SQLite (norma/articulo/version) -> indices.

Flujo:
  1. Parsear todos los archivos y ordenarlos por fecha (la base debe existir
     antes que su modificatoria, sin importar el nombre del archivo).
  2. Por norma, en UNA transaccion: insertar norma, articulos y versiones; por
     cada modificatoria, cerrar la version abierta del articulo objetivo y
     crear la nueva enlazada con `reemplaza_a`.
  3. Sincronizar indices desde SQLite: embeber solo versiones nuevas, refrescar
     metadatos (vigente_hasta cambia al cerrar) y reconstruir BM25.

Idempotente: una norma cuyo codigo ya existe se omite.
"""
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from modules.rag.domain import EstadoNorma, IngestaError, Norma, Version, VersionDetalle
from modules.rag.repositories import LexicalRepository, SqlRepository, VectorRepository, metadata_for
from modules.rag.services.parsers import NormaParseada, parse_file
from shared.llm import EmbeddingClient
from shared.logging import get_logger

log = get_logger(__name__)

EXTENSIONES = (".txt", ".pdf")


@dataclass
class IngestReport:
    archivos: int = 0
    normas_nuevas: list[str] = field(default_factory=list)
    normas_omitidas: list[str] = field(default_factory=list)
    versiones_creadas: int = 0
    versiones_cerradas: int = 0
    modificaciones_aplicadas: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)
    embebidas: int = 0
    segundos: float = 0.0


def texto_indexable(d: VersionDetalle) -> str:
    """Lo que se embebe/tokeniza. Anteponer norma y titulo da contexto a
    articulos cortos que por si solos no dicen de que reglamento son."""
    return f"{d.norma_codigo}. {d.norma_titulo}\n{d.texto}"


class IngestionService:
    def __init__(
        self,
        sql: SqlRepository,
        vectors: VectorRepository,
        lexical: LexicalRepository,
        embedder: EmbeddingClient,
        parser: Callable[[Path], NormaParseada] = parse_file,
    ):
        self.sql = sql
        self.vectors = vectors
        self.lexical = lexical
        self.embedder = embedder
        self.parser = parser

    # ---------------------------------------------------------------- publico
    def ingest_path(self, path: Path) -> IngestReport:
        t0 = time.perf_counter()
        report = IngestReport()
        path = Path(path)
        if path.is_file():
            files = [path]
        elif path.is_dir():
            files = sorted(p for p in path.rglob("*") if p.suffix.lower() in EXTENSIONES)
        else:
            raise IngestaError(f"No existe: {path}")
        report.archivos = len(files)

        parsed: list[NormaParseada] = []
        for f in files:
            try:
                parsed.append(self.parser(f))
            except IngestaError as exc:
                report.advertencias.append(str(exc))
                log.warning("%s", exc)

        parsed.sort(key=lambda n: (n.fecha_emision, n.vigencia_desde, n.codigo))
        for norma in parsed:
            self._apply(norma, report)

        report.embebidas = self.sync_indexes()
        report.segundos = round(time.perf_counter() - t0, 3)
        log.info(
            "Ingesta: %d nuevas, %d omitidas, %d versiones (+%d cerradas), %d embebidas",
            len(report.normas_nuevas), len(report.normas_omitidas),
            report.versiones_creadas, report.versiones_cerradas, report.embebidas,
        )
        return report

    def sync_indexes(self) -> int:
        """Pone Chroma y BM25 al dia con SQLite. Devuelve cuantas se embebieron.

        Como SQLite es la fuente de verdad, esto tambien repara indices si una
        ingesta anterior se corto despues del commit SQL.
        """
        detalles = self.sql.all_detalles()
        existentes = self.vectors.existing_ids()

        nuevos = [d for d in detalles if d.version_id not in existentes]
        if nuevos:
            embs = self.embedder.embed_documents([texto_indexable(d) for d in nuevos])
            self.vectors.upsert(
                [d.version_id for d in nuevos], embs, [d.texto for d in nuevos], [self._meta(d) for d in nuevos]
            )
        viejos = [d for d in detalles if d.version_id in existentes]
        if viejos:
            self.vectors.update_metadata([d.version_id for d in viejos], [self._meta(d) for d in viejos])

        self.lexical.rebuild([d.version_id for d in detalles], [texto_indexable(d) for d in detalles])
        return len(nuevos)

    # -------------------------------------------------------------- internos
    @staticmethod
    def _meta(d: VersionDetalle) -> dict:
        return metadata_for(
            d.norma_codigo,
            d.articulo_numero,
            d.vigente_desde.isoformat(),
            d.vigente_hasta.isoformat() if d.vigente_hasta else None,
            d.creada_por_codigo,
        )

    def _apply(self, np: NormaParseada, report: IngestReport) -> None:
        if self.sql.get_norma(np.codigo):
            report.normas_omitidas.append(np.codigo)
            return

        with self.sql.transaction():
            norma_id = self.sql.insert_norma(
                Norma(None, np.codigo, np.titulo, np.fecha_emision, np.tipo, np.estado), fuente=np.fuente
            )
            for art in np.articulos:
                a = self.sql.get_or_create_articulo(norma_id, art.numero)
                self.sql.insert_version(Version(None, a.id, art.texto, np.vigencia_desde, None, norma_id))
                report.versiones_creadas += 1

            if np.estado == EstadoNorma.PROYECTO:
                # Un proyecto NUNCA cierra versiones: aun no es derecho vigente.
                if np.modificaciones:
                    report.advertencias.append(
                        f"{np.codigo}: proyecto con {len(np.modificaciones)} modificacion(es) "
                        "propuesta(s); no se aplican"
                    )
            else:
                for mod in np.modificaciones:
                    self._apply_modificacion(np, norma_id, mod, report)

        report.normas_nuevas.append(np.codigo)

    def _apply_modificacion(self, np: NormaParseada, norma_id: int, mod, report: IngestReport) -> None:
        objetivo = self.sql.get_norma(mod.norma_objetivo)
        if objetivo is None:
            report.advertencias.append(
                f"{np.codigo} art. {mod.origen_articulo}: modifica {mod.norma_objetivo}, que no esta ingestada"
            )
            return

        articulo = self.sql.get_articulo(objetivo.codigo, mod.articulo_numero)
        if articulo is None:
            report.advertencias.append(
                f"{np.codigo}: el art. {mod.articulo_numero} no existia en {objetivo.codigo}; se incorpora"
            )
            articulo = self.sql.get_or_create_articulo(objetivo.id, mod.articulo_numero)

        desde = np.vigencia_desde
        anterior = self.sql.get_open_version(articulo.id)
        if anterior is not None:
            if anterior.vigente_desde >= desde:
                report.advertencias.append(
                    f"{np.codigo}: vigencia {desde} no es posterior a la version vigente del art. "
                    f"{mod.articulo_numero} ({anterior.vigente_desde}); se ignora"
                )
                return
            self.sql.close_version(anterior.id, desde)
            report.versiones_cerradas += 1

        self.sql.insert_version(
            Version(
                None, articulo.id, mod.nuevo_texto, desde, None, norma_id,
                reemplaza_a=anterior.id if anterior else None,
            )
        )
        report.versiones_creadas += 1
        report.modificaciones_aplicadas.append(
            f"{objetivo.codigo} art. {mod.articulo_numero} <- {np.codigo} (desde {desde})"
        )
