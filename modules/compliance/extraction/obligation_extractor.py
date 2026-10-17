"""Extraccion de obligaciones GUIADA POR EL RAG (offline).

Por categoria:
  RagFacade.search(descripcion_busqueda, fecha, norma=2660-2015, top_k=5)
  -> el LLM extrae SOLO del articulo recuperado (una llamada por articulo)
  -> citation_check: cita literal en la version + plazo_valor dentro de la cita
  -> propuesta (estado='propuesta') con version_id, categoria y score.
Lo que no pasa la verificacion se descarta y queda en el log JSONL.
"""
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from modules.compliance.domain import Categoria, Obligacion
from modules.compliance.extraction.citation_check import cita_literal, limpiar_cita, numero_en_cita
from modules.compliance.extraction.llm_cache import CachedStructuredLLM
from modules.compliance.extraction.schemas import ExtraccionObligaciones, ObligacionLLM
from modules.compliance.repositories import SqliteComplianceRepository
from modules.rag import Fragmento, RagFacade
from shared.logging import JsonlWriter, get_logger

log = get_logger(__name__)

SYSTEM_OBLIGACIONES = """Eres un analista de cumplimiento LA/FT en Peru. Lees UN articulo de un reglamento de la SBS y extraes las obligaciones que impone.
Reglas estrictas:
1. Usa EXCLUSIVAMENTE el texto del articulo. No inventes ni completes con conocimiento externo.
2. cita_textual: copia LITERAL y CONTIGUA del articulo (una o dos oraciones completas) que sustenta la obligacion. No resumas ni cambies palabras.
3. plazo_valor: solo si el articulo escribe un numero explicito para el plazo (p. ej. "diez (10) años" -> 10). Si no hay numero explicito, null y describe el plazo en plazo_texto. Si das plazo_valor, la cita_textual DEBE ser la oracion donde aparece ese plazo (con el numero).
4. plazo_unidad: horas | dias | meses | anios. tipo_plazo: calendario | habil (solo si dice "dias habiles") | periodico (frecuencia, p. ej. "al año", "anualmente").
5. Extrae solo obligaciones relacionadas con la CATEGORIA indicada. Si el articulo no impone ninguna, impone_obligacion=false y obligaciones=[].
Responde solo el JSON."""


@dataclass
class ExtractionSummary:
    tipo: str
    categorias: list[str] = field(default_factory=list)
    articulos: int = 0
    llamadas_llm: int = 0
    desde_cache: int = 0
    propuestas_nuevas: int = 0
    duplicadas: int = 0
    descartadas: int = 0
    errores: int = 0


def _user_prompt(cat: Categoria, frag: Fragmento) -> str:
    return (
        f"CATEGORIA: {cat.codigo} - {cat.nombre}. {cat.descripcion_busqueda}\n"
        f"NORMA: {frag.cita.norma}, articulo {frag.cita.articulo}\n"
        f"TEXTO DEL ARTICULO:\n<<<\n{frag.texto}\n>>>\n"
        "Extrae solo las obligaciones de este articulo relacionadas con la categoria."
    )


def verificar_obligacion(o: ObligacionLLM, texto_version: str) -> str | None:
    """None si pasa; si no, el motivo de descarte."""
    if not cita_literal(o.cita_textual, texto_version):
        return "cita_textual no existe literalmente en la version"
    if o.plazo_valor is not None and not numero_en_cita(o.plazo_valor, o.cita_textual):
        return f"plazo_valor {o.plazo_valor} no aparece en la cita"
    return None


class ObligationExtractor:
    def __init__(
        self,
        rag: RagFacade,
        llm: CachedStructuredLLM,
        repo: SqliteComplianceRepository,
        *,
        norma: str,
        top_k: int = 5,
        event_log: JsonlWriter | None = None,
    ):
        self.rag = rag
        self.llm = llm
        self.repo = repo
        self.norma = norma
        self.top_k = top_k
        self.event_log = event_log

    def run(
        self,
        categorias: list[Categoria],
        fecha: date | None = None,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> ExtractionSummary:
        s = ExtractionSummary(tipo="obligaciones", categorias=[c.codigo for c in categorias])
        trabajo = [(c, f) for c in categorias
                   for f in self.rag.search(c.descripcion_busqueda, fecha, self.top_k, norma=self.norma).fragmentos]
        for i, (cat, frag) in enumerate(trabajo, 1):
            if progress:
                progress(i, len(trabajo), f"{cat.codigo} art. {frag.cita.articulo}")
            self._procesar(cat, frag, s)
        log.info("Extraccion de obligaciones: %s", s)
        return s

    def _procesar(self, cat: Categoria, frag: Fragmento, s: ExtractionSummary) -> None:
        s.articulos += 1
        messages = [{"role": "system", "content": SYSTEM_OBLIGACIONES},
                    {"role": "user", "content": _user_prompt(cat, frag)}]
        out, meta = self.llm.extract(frag.cita.version_id, messages, ExtraccionObligaciones)
        s.desde_cache += int(meta["cached"])
        s.llamadas_llm += int(not meta["cached"])
        evento = {"evento": "compliance.extract", "tipo": "obligacion", "categoria": cat.codigo,
                  "version_id": frag.cita.version_id, "articulo": frag.cita.articulo, **meta,
                  "aceptadas": [], "descartes": []}
        if out is None:
            s.errores += 1
        else:
            for o in out.obligaciones if out.impone_obligacion else []:
                motivo = verificar_obligacion(o, frag.texto)
                if motivo:
                    s.descartadas += 1
                    evento["descartes"].append({"motivo": motivo, "cita": o.cita_textual[:300]})
                    log.info("Descartada (%s art. %s): %s", cat.codigo, frag.cita.articulo, motivo)
                    continue
                guardada = self.repo.insert_obligacion(Obligacion(
                    id=None, codigo="", categoria=cat.codigo, sujeto=o.sujeto, accion_requerida=o.accion_requerida,
                    evento_disparador=o.evento_disparador, plazo_texto=o.plazo_texto, plazo_valor=o.plazo_valor,
                    plazo_unidad=o.plazo_unidad, tipo_plazo=o.tipo_plazo, evidencia_requerida=o.evidencia_requerida,
                    cita_textual=limpiar_cita(o.cita_textual), version_id=frag.cita.version_id,
                    norma_codigo=frag.cita.norma, articulo_numero=frag.cita.articulo,
                    score_recuperacion=frag.cita.score, modelo=self.llm.model_name,
                ))
                if guardada is None:
                    s.duplicadas += 1
                else:
                    s.propuestas_nuevas += 1
                    evento["aceptadas"].append(guardada.codigo)
        if self.event_log:
            self.event_log.write(evento)
