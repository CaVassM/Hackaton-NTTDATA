"""Extraccion de infracciones guiada por el RAG + enlace categoria -> infraccion.

Por categoria:
  RagFacade.search(descripcion_busqueda, fecha, norma=<norma de infracciones>)
  -> segmenta cada articulo/anexo por numeral
  -> rankea numerales por similitud de embeddings con la categoria (top N)
  -> el LLM estructura el numeral y confirma si sanciona la categoria
  -> verificacion: cita literal (si no, se descarta); multas y gravedad solo si
     aparecen en el texto (si no, null)
  -> infraccion (propuesta) + enlace categoria->infraccion (propuesta)
     con score = similitud de recuperacion del numeral.
"""
import math
import re
from collections.abc import Callable
from datetime import date

from modules.compliance.domain import Categoria, Infraccion
from modules.compliance.extraction.annex_segmenter import encabezado, segmentar
from modules.compliance.extraction.citation_check import cita_literal, limpiar_cita, numero_en_cita
from modules.compliance.extraction.llm_cache import CachedStructuredLLM
from modules.compliance.extraction.obligation_extractor import ExtractionSummary
from modules.compliance.extraction.schemas import ExtraccionInfracciones, InfraccionLLM
from modules.compliance.repositories import SqliteComplianceRepository
from modules.rag import Fragmento, RagFacade
from shared.llm import EmbeddingClient
from shared.logging import JsonlWriter, get_logger

log = get_logger(__name__)

SYSTEM_INFRACCIONES = """Eres un analista de cumplimiento en Peru. Lees UN numeral de un anexo de infracciones y sanciones y lo estructuras.
Reglas estrictas:
1. Usa EXCLUSIVAMENTE el texto dado. No inventes.
2. cita_textual: copia LITERAL y CONTIGUA del numeral COMPLETO, incluida la oracion de la sancion/multa si existe (sin resumir).
3. gravedad: leve | grave | muy_grave solo si el texto (o el encabezado del articulo) lo dice; si no, null.
4. multa_min_uit / multa_max_uit: solo numeros que aparezcan escritos junto a "UIT" en el texto; si no, null. Si dice "hasta X UIT" sin minimo, multa_min_uit=null y multa_max_uit=X.
5. relacionada_con_categoria: true solo si esta infraccion sanciona el incumplimiento de la CATEGORIA indicada; explica en motivo_relacion en una frase.
Responde solo el JSON."""

_GRAVEDAD_RX = {"muy_grave": re.compile(r"(?i)muy\s+graves?"),
                "grave": re.compile(r"(?i)(?<!muy )\bgraves?\b"),
                "leve": re.compile(r"(?i)\bleves?\b")}


def _cos(a: list[float], b: list[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def verificar_infraccion(i: InfraccionLLM, texto_version: str, cabecera: str) -> tuple[InfraccionLLM | None, list[str]]:
    """(infraccion saneada o None si se descarta, notas)."""
    if not cita_literal(i.cita_textual, texto_version):
        return None, ["cita_textual no existe literalmente en la version"]
    notas, upd = [], {}
    for campo in ("multa_min_uit", "multa_max_uit"):
        v = getattr(i, campo)
        if v is not None and not numero_en_cita(v, i.cita_textual):
            upd[campo] = None
            notas.append(f"{campo}={v} no aparece en la cita: se anula")
    mn, mx = upd.get("multa_min_uit", i.multa_min_uit), upd.get("multa_max_uit", i.multa_max_uit)
    # "hasta N UIT" sin "de M": no hay minimo explicito (el LLM tiende a copiar N como minimo).
    if mn is not None and mn == mx and re.search(rf"hasta\s+{int(mx) if float(mx).is_integer() else mx}\s*UIT", i.cita_textual) \
            and not re.search(r"(?i)\bde\s+\d+(?:[.,]\d+)?\s+(?:hasta|a)\b", i.cita_textual):
        upd["multa_min_uit"] = None
        notas.append(f"'hasta {mx} UIT' no fija minimo: multa_min_uit se anula")
    if i.gravedad and not _GRAVEDAD_RX[i.gravedad].search(f"{cabecera}\n{i.cita_textual}"):
        upd["gravedad"] = None
        notas.append(f"gravedad '{i.gravedad}' no consta en el texto: se anula")
    return i.model_copy(update=upd), notas


class InfractionExtractor:
    def __init__(
        self,
        rag: RagFacade,
        llm: CachedStructuredLLM,
        repo: SqliteComplianceRepository,
        embedder: EmbeddingClient,
        *,
        norma: str,
        top_k: int = 5,
        max_numerales: int = 3,
        event_log: JsonlWriter | None = None,
    ):
        self.rag, self.llm, self.repo, self.embedder = rag, llm, repo, embedder
        self.norma, self.top_k, self.max_numerales, self.event_log = norma, top_k, max_numerales, event_log

    def _candidatos(self, cat: Categoria, fecha: date) -> list[tuple[Fragmento, str | None, str, float]]:
        frags = self.rag.search(cat.descripcion_busqueda, fecha, self.top_k, norma=self.norma).fragmentos
        segs = [(f, cod, txt) for f in frags for cod, txt in segmentar(f.texto)]
        if not segs:
            return []
        q = self.embedder.embed_query(cat.descripcion_busqueda)
        sims = [_cos(q, e) for e in self.embedder.embed_documents([t for _, _, t in segs])]
        ranked = sorted(zip(segs, sims), key=lambda p: p[1], reverse=True)[: self.max_numerales]
        return [(f, cod, txt, round(s, 4)) for (f, cod, txt), s in ranked]

    def run(self, categorias: list[Categoria], fecha: date,
            progress: Callable[[int, int, str], None] | None = None) -> ExtractionSummary:
        s = ExtractionSummary(tipo="infracciones", categorias=[c.codigo for c in categorias])
        trabajo = [(c, *x) for c in categorias for x in self._candidatos(c, fecha)]
        for n, (cat, frag, cod, txt, score) in enumerate(trabajo, 1):
            if progress:
                progress(n, len(trabajo), f"{cat.codigo} {frag.cita.norma[:20]} {cod or 'art. ' + frag.cita.articulo}")
            self._procesar(cat, frag, cod, txt, score, s)
        log.info("Extraccion de infracciones: %s", s)
        return s

    def _procesar(self, cat, frag: Fragmento, cod, txt: str, score: float, s: ExtractionSummary) -> None:
        s.articulos += 1
        cabecera = encabezado(frag.texto)
        messages = [
            {"role": "system", "content": SYSTEM_INFRACCIONES},
            {"role": "user", "content": (
                f"CATEGORIA: {cat.codigo} - {cat.nombre}. {cat.descripcion_busqueda}\n"
                f"NORMA: {frag.cita.norma}. ENCABEZADO: {cabecera}\n"
                f"NUMERAL {cod or '(sin numeral)'}:\n<<<\n{txt}\n>>>")},
        ]
        out, meta = self.llm.extract(frag.cita.version_id, messages, ExtraccionInfracciones)
        s.desde_cache += int(meta["cached"])
        s.llamadas_llm += int(not meta["cached"])
        evento = {"evento": "compliance.extract", "tipo": "infraccion", "categoria": cat.codigo,
                  "version_id": frag.cita.version_id, "numeral": cod, "score": score, **meta,
                  "aceptadas": [], "descartes": [], "notas": []}
        if out is None:
            s.errores += 1
        else:
            for raw in out.infracciones if out.contiene_infracciones else []:
                inf, notas = verificar_infraccion(raw, frag.texto, cabecera)
                evento["notas"] += notas
                if inf is None:
                    s.descartadas += 1
                    evento["descartes"].append({"motivo": notas[0], "cita": raw.cita_textual[:300]})
                    continue
                guardada = self.repo.insert_infraccion(Infraccion(
                    id=None, codigo_numeral=inf.codigo_numeral or cod, descripcion=inf.descripcion,
                    gravedad=inf.gravedad, sancion_texto=inf.sancion_texto, multa_min_uit=inf.multa_min_uit,
                    multa_max_uit=inf.multa_max_uit, cita_textual=limpiar_cita(inf.cita_textual),
                    version_id=frag.cita.version_id, norma_codigo=frag.cita.norma,
                    articulo_numero=frag.cita.articulo, modelo=self.llm.model_name,
                ))
                evento["aceptadas"].append(guardada.proposal_id)
                if inf.relacionada_con_categoria:
                    enl = self.repo.insert_enlace(cat.codigo, guardada.id, score, True, inf.motivo_relacion or "")
                    s.propuestas_nuevas += int(enl is not None)
                    s.duplicadas += int(enl is None)
        if self.event_log:
            self.event_log.write(evento)
