"""Formato de expedientes del equipo (entrada id_caso + descripcion_caso;
salida con las columnas de resultados_esperados_casos_rag_detallados.csv)."""
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from modules.audit import AuditResult

# Orden EXACTO de columnas del CSV de resultados esperados del equipo.
COLUMNAS_SALIDA = [
    "id_caso", "resultado_esperado", "cumple_segun_evidencia", "por_que_si_o_no", "hechos_relevantes_del_caso",
    "evidencia_o_faltantes", "modalidad_analisis", "norma_a_consultar", "razon_de_aplicacion_normativa",
    "alerta_normativa_esperada", "alerta_plazo_interno_esperada", "tipo_alerta_esperada", "fecha_registro",
    "fecha_limite_interna", "fecha_atencion", "dias_de_retraso_interno", "explicacion_plazo", "prioridad",
    "sancion_aplicable", "limitacion_de_la_evaluacion", "fuente_patron", "fuente_legal", "revision_humana",
]
# Columnas propias del agente (al final, no rompen el formato del equipo).
COLUMNAS_EXTRA = ["decision_auditoria", "audit_id", "version_id_citada", "senales_detectadas", "reglas_version"]


class ExpedienteInput(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True, json_schema_extra={"examples": [{
        "id_caso": "SYN-0003",
        "descripcion_caso": "Un grupo de personas ... Registro del expediente: 2026-03-19. Fecha objetivo de atención "
                            "interna: 2026-03-31. Fecha de atención registrada: 2026-04-06.",
    }]})

    id_caso: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._\-]+$")
    descripcion_caso: str = Field(..., min_length=10, max_length=20000)
    # Opcionales: si el equipo las envia como columnas, mandan sobre lo extraido del texto.
    fecha_registro: date | None = None
    fecha_limite_interna: date | None = None
    fecha_atencion: date | None = None
    user_id: str = "equipo"
    rol: str = "analista"


class ExpedienteResult(BaseModel):
    fila: dict[str, Any]  # columnas COLUMNAS_SALIDA + COLUMNAS_EXTRA (valores str)
    audit_result: AuditResult | None
    auditoria_error: str | None = None
    tiempos_ms: dict[str, float]

    def as_row(self) -> dict[str, str]:
        return {c: "" if self.fila.get(c) is None else str(self.fila.get(c)) for c in COLUMNAS_SALIDA + COLUMNAS_EXTRA}
