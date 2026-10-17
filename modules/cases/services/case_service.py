"""Evaluacion de un caso.

  validar -> evento->categoria (yaml) -> obligaciones VALIDADAS (compliance)
  -> motor de plazos (compliance) -> citas vigentes en fecha_evento (rag)
  -> ClaimBuilder determinista -> resumen (LLM con guardia de cifras)
  -> auditoria -> CaseResult
Una obligacion no validada NUNCA aporta plazo: se informa como "sin validar".
"""
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from modules.audit import Decision
from modules.cases.domain import (
    CaseInput,
    CaseResult,
    CitaCaso,
    ExposicionCaso,
    ObligacionCaso,
    PlazoCaso,
)
from modules.cases.ports import AuditGateway, ComplianceGateway, RagGateway
from modules.cases.services.claim_builder import ClaimBuilder
from modules.cases.services.eventos import CatalogoEventos
from modules.cases.services.summarizer import Summarizer
from modules.compliance import ROTULO_EXPOSICION, EvidenciaInterna
from shared.logging import get_logger

log = get_logger(__name__)
PUBLICABLES = {Decision.ALLOW, Decision.WARN}


def cita_de(rag: RagGateway, version_id: int, fecha) -> CitaCaso:
    d = rag.get_version(version_id)
    post = rag.versiones_posteriores(version_id)
    return CitaCaso(
        version_id=version_id, norma=d.norma_codigo, articulo=d.articulo_numero,
        vigente_desde=d.vigente_desde, vigente_hasta=d.vigente_hasta,
        vigente_en_fecha=rag.vigente_en(version_id, fecha), modificada_despues=bool(post),
        version_vigente_actual_id=post[-1].version_id if post else version_id,
        sintetica=d.norma_codigo.upper().startswith("SINTETICO"),
    )


def _rango(mn, mx, smn, smx) -> str:
    if mn is None and mx is None:
        return "monto no determinado"
    txt = f"{mn if mn is not None else 'sin minimo'} a {mx if mx is not None else 'sin maximo'} UIT"
    if smx is not None:
        txt += f" (S/ {smn if smn is not None else 'sin minimo'} a S/ {smx})"
    return txt


class CaseService:
    def __init__(self, rag: RagGateway, compliance: ComplianceGateway, audit: AuditGateway,
                 catalogo: CatalogoEventos, summarizer: Summarizer):
        self.rag, self.compliance, self.audit = rag, compliance, audit
        self.catalogo, self.summarizer = catalogo, summarizer

    def evaluate(self, inp: CaseInput) -> CaseResult:
        t0 = time.perf_counter()
        tiempos: dict[str, float] = {}

        def lap(nombre: str, desde: float) -> float:
            ahora = time.perf_counter()
            tiempos[nombre] = round((ahora - desde) * 1000, 1)
            return ahora

        evento = self.catalogo.resolver(inp.tipo_evento)
        fecha_ref = inp.fecha_referencia or self.rag.hoy()  # el CODIGO pone hoy
        case = inp.model_copy(update={"fecha_referencia": fecha_ref})
        t = lap("validacion_ms", t0)

        evid = EvidenciaInterna(evento.categoria, inp.case_id, inp.fecha_evento, inp.fecha_cumplimiento, fecha_ref)
        ev = self.compliance.evaluar_caso(evento.categoria, [evid], fecha_ref, list(evento.obligaciones) or None)
        t = lap("compliance_ms", t)

        # Citas: SOLO lo que se recupera aqui puede citarse despues.
        recuperados: set[int] = set()
        obligaciones, plazos, exposicion, advertencias = [], [], [], []
        for it in ev.items:
            o = it.obligacion
            c = cita_de(self.rag, o.version_id, inp.fecha_evento)
            recuperados.add(o.version_id)
            if not c.vigente_en_fecha:
                advertencias.append(f"{o.codigo}: la version citada (v{o.version_id}) no estaba vigente el {inp.fecha_evento}")
            obligaciones.append(ObligacionCaso(codigo=o.codigo, estado_validacion="validada", sujeto=o.sujeto,
                                               accion_requerida=o.accion_requerida, plazo_texto=o.plazo_texto,
                                               cita_textual=o.cita_textual, cita=c))
            plazos += [PlazoCaso(**asdict(r)) for r in it.casos]
            for ir in it.infracciones:
                i, x = ir.infraccion, ir.exposicion
                ci = cita_de(self.rag, i.version_id, inp.fecha_evento)
                recuperados.add(i.version_id)
                exposicion.append(ExposicionCaso(
                    obligacion_codigo=o.codigo, infraccion_numeral=i.codigo_numeral, gravedad=i.gravedad,
                    descripcion=i.descripcion, cita=ci, multa_min_uit=x.multa_min_uit, multa_max_uit=x.multa_max_uit,
                    min_soles=x.min_soles, max_soles=x.max_soles, monto_determinado=x.monto_determinado,
                    nota=x.nota, rotulo=x.rotulo))
        for o in ev.sin_validar:
            obligaciones.append(ObligacionCaso(codigo=o.codigo, estado_validacion="propuesta", sujeto=o.sujeto,
                                               accion_requerida=o.accion_requerida, plazo_texto=o.plazo_texto,
                                               cita_textual=o.cita_textual))
        listados = {o.codigo for o in obligaciones}
        for cod in evento.obligaciones:
            if cod in listados:
                continue
            o = self.compliance.obligacion(cod)
            obligaciones.append(ObligacionCaso(codigo=cod, estado_validacion=o.revision.estado.value if o else "no_encontrada"))
        if any(e.cita.sintetica for e in exposicion):
            advertencias.append("La exposicion usa un anexo de infracciones SINTETICO (no normativa real).")
        t = lap("rag_ms", t)

        b = ClaimBuilder(recuperados)
        for it in ev.items:
            o = it.obligacion
            b.normativa(o.cita_textual, o.version_id, "obligacion")
            for c in it.casos:
                limite = f", fecha limite {c.fecha_limite}" if c.fecha_limite else ""
                b.dato(f"Caso {c.sujeto_id}: obligacion {o.codigo}, estado {c.estado}{limite}, atraso {c.dias_atraso} dias.",
                       "plazo", o.version_id)
            for ir in it.infracciones:
                b.normativa(ir.infraccion.cita_textual, ir.infraccion.version_id, "infraccion")
            b.inferencia(f"{ROTULO_EXPOSICION} por {o.codigo}: "
                         f"{_rango(*it.rango_uit, *it.rango_soles) if it.infracciones else 'monto no determinado (sin infraccion validada)'}.",
                         "exposicion", o.version_id)
        for o in obligaciones:
            if o.estado_validacion != "validada":
                b.dato(f"Obligacion {o.codigo} {o.estado_validacion}: no se calcula plazo ni exposicion.", "sin_validar")
        if not ev.items:
            b.dato(f"Sin obligaciones validadas aplicables a {evento.categoria} para {inp.tipo_evento} "
                   f"({ev.pendientes_categoria} propuestas pendientes de validacion).", "sin_fundamento")
        t = lap("claims_ms", t)

        plantilla = " ".join(c.text for c in b.claims if c.type != "normativa")
        contexto = [inp.case_id, str(inp.fecha_evento), str(inp.fecha_cumplimiento or ""), str(fecha_ref)]
        resumen, origen = self.summarizer.resumir(b.claims, plantilla, contexto)
        t = lap("resumen_ms", t)

        audit_result, audit_error = None, None
        try:
            audit_result = self.audit.evaluate({
                "interaction_id": f"{inp.case_id}-{uuid.uuid4().hex[:8]}",
                "user_id": inp.user_id,
                "role": inp.rol,
                "query": f"Evaluacion de caso {inp.tipo_evento}. {inp.descripcion or ''}".strip()[:4000],
                "effective_date": inp.fecha_evento.isoformat(),  # la norma debe regir al ocurrir el evento
                "use_case": "evaluacion_caso",
                "candidate": {"text": resumen[:20000],
                              "claims": [{"claim_id": c.claim_id, "text": c.text, "type": c.type,
                                          "evidence_ids": c.evidence_ids} for c in b.claims][:50]},
            })
        except Exception as exc:  # noqa: BLE001 - fail-closed: sin auditoria no es publicable
            log.exception("Auditoria del caso %s fallo", inp.case_id)
            audit_error = f"{type(exc).__name__}: {exc}"
        lap("auditoria_ms", t)
        tiempos["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)

        return CaseResult(
            case=case, categoria=evento.categoria, evento_descripcion=evento.descripcion,
            obligaciones=obligaciones, plazos=plazos, exposicion=exposicion,
            claims=b.claims, claims_rechazados=b.rechazados, resumen=resumen, resumen_origen=origen,
            audit_result=audit_result, auditoria_error=audit_error,
            publicable=bool(audit_result and audit_result.decision in PUBLICABLES),
            sin_fundamento=not ev.items, advertencias=advertencias, tiempos_ms=tiempos,
            evaluado_en=datetime.now(timezone.utc),
        )
