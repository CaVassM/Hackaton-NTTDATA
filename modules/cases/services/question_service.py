"""Pregunta normativa suelta.

  planner (LLM chat_json) -> texto_vigente | busqueda hibrida (rag)
  -> respuesta LLM con citas -> solo se aceptan citas a version_id RECUPERADOS
     cuyo texto exista literal en esa version (si no, se descartan)
  -> guardia de cifras -> auditoria.
Sin fragmentos recuperados: 200 con sin_fundamento=true y sin auditar.
"""
import re
import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from modules.audit import Decision
from modules.cases.domain import CitaCaso, QuestionInput, QuestionResult
from modules.cases.ports import AuditGateway, RagGateway
from modules.cases.services.case_service import cita_de
from modules.cases.services.claim_builder import ClaimBuilder, norm_ws
from modules.cases.services.numbers import numeros_nuevos
from modules.rag import RagError
from shared.llm import LLMClient
from shared.logging import get_logger

log = get_logger(__name__)


class Plan(BaseModel):
    accion: Literal["texto_vigente", "busqueda"]
    norma: str | None = None
    articulo: str | None = None
    consulta: str


class CitaLLM(BaseModel):
    version_id: int
    texto: str


class RespuestaLLM(BaseModel):
    respuesta: str
    citas: list[CitaLLM] = Field(default_factory=list)


_PLANNER = (
    "Decides como buscar normativa SBS para responder una pregunta. Si la pregunta nombra una norma Y un "
    "articulo concretos (p. ej. 'articulo 58 de la Resolucion SBS 2660-2015'), accion=texto_vigente con norma "
    "y articulo. En cualquier otro caso accion=busqueda y consulta = la pregunta reformulada con terminos normativos."
)
_RESPONDER = (
    "Respondes preguntas de cumplimiento LA/FT usando SOLO los fragmentos dados (cada uno con su version_id). "
    "En citas, copia LITERALMENTE la oracion que sustenta la respuesta e indica su version_id. "
    "No agregues cifras ni normas que no esten en los fragmentos."
)


def _primera_oracion(texto: str, max_len: int = 400) -> str:
    t = norm_ws(texto)
    partes = re.split(r"(?<=\.)\s+", t)
    # Saltar el encabezado "Articulo N.- Titulo" si viene solo.
    elegida = next((p for p in partes[1:] if len(p) > 40), partes[0]) if len(partes) > 1 else partes[0]
    return elegida[:max_len]


class QuestionService:
    def __init__(self, rag: RagGateway, audit: AuditGateway, llm: LLMClient | None, top_k: int = 3):
        self.rag, self.audit, self.llm, self.top_k = rag, audit, llm, top_k

    def _plan(self, q: QuestionInput) -> Plan:
        if self.llm is None:
            return Plan(accion="busqueda", consulta=q.pregunta)
        try:
            return self.llm.chat_json([{"role": "system", "content": _PLANNER},
                                       {"role": "user", "content": q.pregunta}], Plan, think=False)
        except Exception as exc:  # noqa: BLE001
            log.warning("Planner fallo (%s); busqueda directa", exc)
            return Plan(accion="busqueda", consulta=q.pregunta)

    def ask(self, q: QuestionInput) -> QuestionResult:
        t0 = time.perf_counter()
        tiempos: dict[str, float] = {}
        fecha = q.fecha or self.rag.hoy()
        plan = self._plan(q)
        tiempos["planner_ms"] = round((time.perf_counter() - t0) * 1000, 1)

        fragmentos: dict[int, str] = {}
        if plan.accion == "texto_vigente" and plan.norma and plan.articulo:
            try:
                v = self.rag.texto_vigente(plan.norma, plan.articulo, fecha)
                if v is not None:
                    fragmentos[v.version_id] = v.texto
            except RagError as exc:
                log.info("texto_vigente no resolvio (%s); se busca", exc)
        if not fragmentos:
            for f in self.rag.search(plan.consulta or q.pregunta, fecha, self.top_k).fragmentos:
                fragmentos[f.cita.version_id] = f.texto
        citas = [cita_de(self.rag, vid, fecha) for vid in fragmentos]
        tiempos["rag_ms"] = round((time.perf_counter() - t0) * 1000 - tiempos["planner_ms"], 1)

        if not fragmentos:
            return QuestionResult(pregunta=q.pregunta, fecha=fecha, plan=plan.model_dump(), citas=[], claims=[],
                                  respuesta="No se encontro normativa vigente en el corpus para esta pregunta.",
                                  respuesta_origen="sin_fundamento", sin_fundamento=True, audit_result=None,
                                  publicable=False, tiempos_ms=tiempos)

        b = ClaimBuilder(set(fragmentos))
        descartadas: list[dict] = []
        respuesta, origen = "", "plantilla"
        if self.llm is not None:
            contexto = "\n\n".join(f"[version_id={vid}]\n{txt[:3000]}" for vid, txt in fragmentos.items())
            try:
                out = self.llm.chat_json([{"role": "system", "content": _RESPONDER},
                                          {"role": "user", "content": f"PREGUNTA: {q.pregunta}\n\nFRAGMENTOS:\n{contexto}"}],
                                         RespuestaLLM, think=False)
                for c in out.citas:
                    if c.version_id not in fragmentos:
                        descartadas.append({"version_id": c.version_id, "texto": c.texto[:300], "motivo": "version_id no recuperado"})
                    elif norm_ws(c.texto).strip("\"“”") not in norm_ws(fragmentos[c.version_id]):
                        descartadas.append({"version_id": c.version_id, "texto": c.texto[:300], "motivo": "cita no literal"})
                    else:
                        b.normativa(c.texto.strip("\"“” "), c.version_id, "pregunta")
                respuesta, origen = out.respuesta.strip(), "llm"
            except Exception as exc:  # noqa: BLE001
                log.warning("Respuesta con LLM fallo (%s); plantilla", exc)
        if not b.claims:  # sin citas validas: la cita la elige el codigo, no el LLM
            vid = next(iter(fragmentos))
            b.normativa(_primera_oracion(fragmentos[vid]), vid, "pregunta")
        fuentes = [c.text for c in b.claims]
        if origen != "llm" or not respuesta or numeros_nuevos(respuesta, fuentes + [q.pregunta]):
            c0 = b.claims[0]
            ci = next(c for c in citas if c.version_id == c0.version_ref)
            respuesta, origen = f"Segun {ci.norma}, art. {ci.articulo} (version {ci.version_id}): «{c0.text}»", "plantilla"
        tiempos["respuesta_ms"] = round((time.perf_counter() - t0) * 1000 - sum(tiempos.values()), 1)

        audit_result, audit_error = None, None
        try:
            audit_result = self.audit.evaluate({
                "interaction_id": f"q-{uuid.uuid4().hex[:12]}", "user_id": q.user_id, "role": q.rol,
                "query": q.pregunta, "effective_date": fecha.isoformat(), "use_case": "consulta_normativa",
                "candidate": {"text": respuesta[:20000], "claims": [
                    {"claim_id": c.claim_id, "text": c.text, "type": c.type, "evidence_ids": c.evidence_ids}
                    for c in b.claims]},
            })
        except Exception as exc:  # noqa: BLE001
            log.exception("Auditoria de la pregunta fallo")
            audit_error = f"{type(exc).__name__}: {exc}"
        tiempos["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return QuestionResult(
            pregunta=q.pregunta, fecha=fecha, plan=plan.model_dump(), citas=citas, claims=b.claims,
            citas_descartadas=descartadas + b.rechazados, respuesta=respuesta, respuesta_origen=origen,
            sin_fundamento=False, audit_result=audit_result, auditoria_error=audit_error,
            publicable=bool(audit_result and audit_result.decision in {Decision.ALLOW, Decision.WARN}),
            tiempos_ms=tiempos,
        )
