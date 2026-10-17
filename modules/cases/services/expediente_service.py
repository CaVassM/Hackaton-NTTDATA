"""Analisis DETERMINISTA de expedientes (formato del equipo) + auditoria.

  descripcion -> resultado (reglas YAML) -> modalidad -> articulo DL 1106
  -> fechas internas (columnas o texto) -> atraso -> claims -> auditoria
El LLM no decide nada aqui: es un clasificador por reglas versionadas, para
que el mismo expediente de siempre el mismo resultado y sea explicable.
La norma solo se CITA (version_id) si el DL 1106 esta ingerido en el RAG.
"""
import re
import time
import unicodedata
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from modules.cases.domain import CasesError
from modules.cases.domain.expediente import ExpedienteInput, ExpedienteResult
from modules.cases.ports import AuditGateway, RagGateway
from modules.cases.services.claim_builder import ClaimBuilder
from modules.rag import RagError
from shared.logging import get_logger

log = get_logger(__name__)


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return re.sub(r"\s+", " ", "".join(c for c in t if not unicodedata.combining(c)))


class ReglasExpediente:
    def __init__(self, path: Path):
        try:
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
            self.version = raw["version"]
            self.resultado = [(r["resultado"], r["nombre"], re.compile(r["patron"])) for r in raw["resultado"]]
            self.modalidades = [(m["modalidad"], str(m["articulo"]), re.compile(m["patron"]), m["razon"])
                                for m in raw["modalidades"]]
            self.fechas = {k: re.compile(v) for k, v in raw["fechas"].items()}
            self.norma = raw["norma"]
            self.textos = raw["textos"]
        except (OSError, KeyError, TypeError, re.error, yaml.YAMLError) as exc:
            raise CasesError(f"expedientes.yaml invalido en {path}: {exc}") from exc


class ExpedienteService:
    def __init__(self, rag: RagGateway, audit: AuditGateway, reglas: ReglasExpediente):
        self.rag, self.audit, self.reglas = rag, audit, reglas
        self._citas: dict[str, Any] = {}  # articulo -> VersionDetalle | None (cache por proceso)

    # ---------------------------------------------------------- clasificacion
    def clasificar(self, texto: str) -> tuple[str, list[str]]:
        t = norm(texto)
        senales = [nombre for res, nombre, rx in self.reglas.resultado if rx.search(t)]
        for res, nombre, rx in self.reglas.resultado:  # la primera regla que coincide gana
            if rx.search(t):
                return res, senales
        return "INFORMACION_INSUFICIENTE", ["sin_senales_reconocibles"]

    def modalidad(self, texto: str) -> tuple[str, str, str]:
        t = norm(texto)
        for mod, art, rx, razon in self.reglas.modalidades:
            if rx.search(t):
                return mod, art, razon
        mod, art, _, razon = self.reglas.modalidades[-1]
        return mod, art, razon

    def fechas(self, inp: ExpedienteInput) -> tuple[date | None, date | None, date | None, str]:
        t = norm(inp.descripcion_caso)

        def del_texto(clave):
            m = self.reglas.fechas[clave].search(t)
            return date.fromisoformat(m.group(1)) if m else None

        reg = inp.fecha_registro or del_texto("registro")
        lim = inp.fecha_limite_interna or del_texto("limite")
        ate = inp.fecha_atencion or del_texto("atencion")
        origen = "columnas" if any((inp.fecha_registro, inp.fecha_limite_interna, inp.fecha_atencion)) else "texto"
        return reg, lim, ate, origen

    def _cita(self, articulo: str):
        if articulo not in self._citas:
            try:
                self._citas[articulo] = self.rag.texto_vigente(self.reglas.norma["norma_rag"], articulo)
            except RagError:
                self._citas[articulo] = None
        return self._citas[articulo]

    # ----------------------------------------------------------------- caso
    def analizar(self, inp: ExpedienteInput) -> ExpedienteResult:
        t0 = time.perf_counter()
        resultado, senales = self.clasificar(inp.descripcion_caso)
        mod, art, razon = self.modalidad(inp.descripcion_caso)
        reg, lim, ate, origen_fechas = self.fechas(inp)
        txt = self.reglas.textos[resultado]

        if lim and ate:
            dias = max(0, (ate - lim).days)
            alerta_plazo = "SI" if dias > 0 else "NO"
            explicacion = (f"Atencion registrada {dias} dias calendario despues de la fecha limite interna ({lim}); "
                           f"atencion {ate}. No es un plazo legal del DL 1106." if dias else
                           f"Atencion registrada el {ate}, dentro del plazo interno que vence el {lim}. "
                           "No es validacion de plazos legales.")
        else:
            dias, alerta_plazo = None, "NO_DETERMINABLE"
            explicacion = ("La entrada no trae fecha limite interna ni fecha de atencion: el atraso interno no se "
                           "puede calcular (no se asume que este en plazo).")
        alerta_norm = "SI" if resultado == "POSIBLE_INCUMPLIMIENTO" else "NO"
        tipo = {("SI", "SI"): "AMBAS", ("SI", "NO"): "NORMATIVA", ("NO", "SI"): "PLAZO_INTERNO"}.get(
            (alerta_norm, alerta_plazo), "NINGUNA")

        cita = self._cita(art)
        fuente_legal = (f"{cita.norma_codigo}, art. {cita.articulo_numero} (version {cita.version_id})" if cita
                        else self.reglas.norma["fuente_legal_sin_corpus"])

        # Claims: la norma solo si fue RECUPERADA; el resto son datos/inferencias pendientes.
        b = ClaimBuilder({cita.version_id} if cita else set())
        if cita:
            b.normativa(cita.texto[:1500], cita.version_id, "norma_dl1106")
        b.dato(f"Expediente {inp.id_caso}: senales detectadas {', '.join(senales) or 'ninguna'}.", "senales")
        if dias is not None:
            b.dato(f"Expediente {inp.id_caso}: fecha limite interna {lim}, atencion {ate}, atraso {dias} dias.", "plazo")
        b.inferencia(f"Expediente {inp.id_caso}: {resultado}; modalidad a contrastar {mod} "
                     f"(art. {art} DL 1106). Hipotesis de contraste, no imputacion.", "clasificacion")

        audit_result, audit_error = None, None
        try:
            audit_result = self.audit.evaluate({
                "interaction_id": f"{inp.id_caso}-{uuid.uuid4().hex[:8]}", "user_id": inp.user_id, "role": inp.rol,
                "query": f"Analisis de expediente {inp.id_caso}: {inp.descripcion_caso}"[:4000],
                "use_case": "evaluacion_caso",
                "candidate": {"text": " ".join(c.text for c in b.claims)[:20000],
                              "claims": [{"claim_id": c.claim_id, "text": c.text, "type": c.type,
                                          "evidence_ids": c.evidence_ids} for c in b.claims]},
            })
        except Exception as exc:  # noqa: BLE001 - fail-closed
            log.exception("Auditoria del expediente %s fallo", inp.id_caso)
            audit_error = f"{type(exc).__name__}: {exc}"

        fila = {
            "id_caso": inp.id_caso,
            "resultado_esperado": resultado,
            "cumple_segun_evidencia": txt["cumple"],
            "por_que_si_o_no": txt["por_que"].format(senales=", ".join(senales) or "sin senales"),
            "hechos_relevantes_del_caso": inp.descripcion_caso,
            "evidencia_o_faltantes": txt["evidencia"],
            "modalidad_analisis": mod,
            "norma_a_consultar": self.reglas.norma["etiqueta"].format(articulo=art),
            "razon_de_aplicacion_normativa": f"{razon} Es una hipotesis de contraste, no una imputacion firme.",
            "alerta_normativa_esperada": alerta_norm,
            "alerta_plazo_interno_esperada": alerta_plazo,
            "tipo_alerta_esperada": tipo,
            "fecha_registro": reg, "fecha_limite_interna": lim, "fecha_atencion": ate,
            "dias_de_retraso_interno": dias,
            "explicacion_plazo": explicacion + (" (fechas tomadas de columnas)" if origen_fechas == "columnas" and dias is not None else ""),
            "prioridad": txt["prioridad"],
            "sancion_aplicable": self.reglas.textos["sancion"],
            "limitacion_de_la_evaluacion": txt["limitacion"],
            "fuente_patron": "",  # requiere el informe de sentencias (no ingerido)
            "fuente_legal": fuente_legal,
            "revision_humana": "PENDIENTE",
            "decision_auditoria": audit_result.decision.value if audit_result else "SIN_AUDITORIA",
            "audit_id": audit_result.audit_id if audit_result else "",
            "version_id_citada": cita.version_id if cita else "",
            "senales_detectadas": "|".join(senales),
            "reglas_version": self.reglas.version,
        }
        return ExpedienteResult(fila=fila, audit_result=audit_result, auditoria_error=audit_error,
                                tiempos_ms={"total_ms": round((time.perf_counter() - t0) * 1000, 1)})
