"""Busqueda hibrida con filtro temporal.

  pregunta -> [BM25 | denso] -> fusion RRF -> filtro de vigencia en SQL
           -> reranker (opcional) -> top_k con Cita

Solo la PREGUNTA se vectoriza aqui; los documentos se embebieron en la ingesta.
Si no llega fecha, el CODIGO usa hoy (reloj inyectable para tests).
"""
import time
from collections.abc import Callable, Sequence
from datetime import date

from modules.rag.domain import Cita, Fragmento, ResultadoBusqueda
from modules.rag.repositories import InfoCita, LexicalRepository, SqlRepository, VectorRepository
from modules.rag.services.reranker import NoOpReranker, Reranker
from shared.llm import EmbeddingClient
from shared.logging import JsonlWriter, get_logger

log = get_logger(__name__)


def rrf(rankings: Sequence[Sequence[int]], k: int = 60) -> dict[int, float]:
    """Reciprocal Rank Fusion: suma 1/(k + rank) por cada lista donde aparece.

    Solo usa posiciones, no scores: BM25 y coseno viven en escalas distintas y
    no se pueden sumar directamente.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, vid in enumerate(ranking, start=1):
            scores[vid] = scores.get(vid, 0.0) + 1.0 / (k + rank)
    return scores


class RetrievalService:
    def __init__(
        self,
        sql: SqlRepository,
        vectors: VectorRepository,
        lexical: LexicalRepository,
        embedder: EmbeddingClient,
        reranker: Reranker | None = None,
        *,
        rrf_k: int = 60,
        candidates_k: int = 30,
        search_log: JsonlWriter | None = None,
        today: Callable[[], date] = date.today,
    ):
        self.sql = sql
        self.vectors = vectors
        self.lexical = lexical
        self.embedder = embedder
        self.reranker = reranker or NoOpReranker()
        self.rrf_k = rrf_k
        self.candidates_k = candidates_k
        self.search_log = search_log
        self.today = today

    def search(
        self,
        query: str,
        fecha: date | None = None,
        top_k: int = 5,
        incluir_proyectos: bool = False,
    ) -> ResultadoBusqueda:
        t0 = time.perf_counter()
        tiempos: dict[str, float] = {}

        def lap(nombre: str, desde: float) -> float:
            ahora = time.perf_counter()
            tiempos[nombre] = round((ahora - desde) * 1000, 2)
            return ahora

        fecha_por_defecto = fecha is None
        hoy = self.today()
        fecha = fecha or hoy

        t = time.perf_counter()
        q_emb = self.embedder.embed_query(query)
        t = lap("embed_ms", t)

        # Se indexan todas las versiones: muchas candidatas pueden caer en el
        # filtro de fecha. Si quedan menos de top_k y los recuperadores venian
        # "llenos", se amplia la red y se reintenta.
        k = max(self.candidates_k, top_k)
        total = max(self.vectors.count(), self.lexical.count())
        while True:
            dense = self.vectors.query(q_emb, k)
            lex = self.lexical.search(query, k)
            fused = rrf([[v for v, _ in dense], [v for v, _ in lex]], self.rrf_k)
            ordered = sorted(fused, key=fused.get, reverse=True)
            vigentes = self.sql.filtrar_vigentes(ordered, fecha, incluir_proyectos)
            kept = [v for v in ordered if v in vigentes]
            saturado = len(dense) >= k or len(lex) >= k
            if len(kept) >= top_k or not saturado or k >= total:
                break
            k *= 2
        t = lap("retrieval_ms", t)

        if self.reranker.enabled and kept:
            # El reranker cuesta (p. ej. una llamada LLM por candidato): solo la cabeza.
            pool = kept[: top_k * 3]
            textos = {d.version_id: d.texto for d in self.sql.get_detalles(pool)}
            ranked = self.reranker.rerank(query, [(v, textos[v]) for v in pool if v in textos], top_k)
            t = lap("rerank_ms", t)
        else:
            ranked = [(v, fused[v]) for v in kept[:top_k]]

        info = self.sql.info_citas([v for v, _ in ranked], hoy)
        fragmentos = [self._fragmento(info[v], score) for v, score in ranked if v in info]
        lap("citas_ms", t)
        tiempos["total_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        if self.search_log:
            self.search_log.write(
                {
                    "evento": "rag.search",
                    "query": query,
                    "fecha": fecha,
                    "fecha_por_defecto": fecha_por_defecto,
                    "incluir_proyectos": incluir_proyectos,
                    "top_k": top_k,
                    "candidatos_denso": [v for v, _ in dense],
                    "candidatos_lexico": [v for v, _ in lex],
                    "descartados_por_vigencia": len(ordered) - len(kept),
                    "resultado_ids": [f.cita.version_id for f in fragmentos],
                    "reranker": self.reranker.enabled,
                    "tiempos": tiempos,
                }
            )
        return ResultadoBusqueda(query, fecha, fecha_por_defecto, fragmentos)

    @staticmethod
    def _fragmento(i: InfoCita, score: float) -> Fragmento:
        d = i.detalle
        return Fragmento(
            texto=d.texto,
            cita=Cita(
                norma=d.norma_codigo,
                articulo=d.articulo_numero,
                version_id=d.version_id,
                vigente_desde=d.vigente_desde,
                vigente_hasta=d.vigente_hasta,
                fue_modificada=i.tiene_posterior,
                version_vigente_actual_id=i.version_vigente_actual_id,
                score=round(float(score), 6),
                creada_por=d.creada_por_codigo,
                reemplaza_a=d.reemplaza_a,
                es_proyecto=d.es_proyecto,
            ),
        )
