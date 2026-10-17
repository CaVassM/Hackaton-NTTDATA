"""Contrato de casos y preguntas. Pydantic: llegan de otros equipos por HTTP/CSV
y su validacion es regla de dominio. Puro: sin I/O."""
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modules.audit import AuditResult

Rol = Literal["analista", "oficial_cumplimiento"]
Moneda = Literal["PEN", "USD"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CaseInput(_Strict):
    case_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._\-]+$")
    user_id: str = Field(..., min_length=1, max_length=128)
    rol: Rol
    tipo_evento: str = Field(..., min_length=1, max_length=64, description="Ver GET /cases/schema")
    fecha_evento: date
    fecha_cumplimiento: date | None = None
    monto: float | None = Field(None, ge=0)
    moneda: Moneda = "PEN"
    descripcion: str | None = Field(None, max_length=2000)
    # None = el CODIGO usa hoy (nunca el cliente ni el LLM implicitamente).
    fecha_referencia: date | None = None

    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True,
        json_schema_extra={"examples": [{
            "case_id": "ROS-2026-0115", "user_id": "analista.01", "rol": "oficial_cumplimiento",
            "tipo_evento": "operacion_calificada_sospechosa", "fecha_evento": "2026-09-10",
            "fecha_cumplimiento": "2026-09-15", "monto": 185000, "moneda": "PEN",
            "descripcion": "Depositos fraccionados calificados como sospechosos",
        }]},
    )

    @model_validator(mode="after")
    def _fechas(self) -> "CaseInput":
        if self.fecha_cumplimiento and self.fecha_cumplimiento < self.fecha_evento:
            raise ValueError("fecha_cumplimiento no puede ser anterior a fecha_evento")
        if self.fecha_referencia and self.fecha_referencia < self.fecha_evento:
            raise ValueError("fecha_referencia no puede ser anterior a fecha_evento")
        return self


class CitaCaso(BaseModel):
    version_id: int
    norma: str
    articulo: str
    vigente_desde: date
    vigente_hasta: date | None
    vigente_en_fecha: bool  # vigente en la fecha del evento / de la pregunta
    modificada_despues: bool
    version_vigente_actual_id: int | None = None
    sintetica: bool = False


class CaseClaim(BaseModel):
    claim_id: str
    text: str
    type: Literal["normativa", "dato_caso", "inferencia"]
    evidence_ids: list[int] = Field(default_factory=list)  # lo que se envia al auditor
    version_ref: int | None = None  # version relacionada (tambien en dato_caso / inferencia)
    origen: str


class ObligacionCaso(BaseModel):
    codigo: str
    estado_validacion: Literal["validada", "propuesta", "rechazada", "no_encontrada"]
    sujeto: str | None = None
    accion_requerida: str | None = None
    plazo_texto: str | None = None
    cita_textual: str | None = None
    cita: CitaCaso | None = None


class PlazoCaso(BaseModel):
    obligacion_codigo: str
    sujeto_id: str | None = None
    estado: str
    fecha_evento: date | None = None
    fecha_limite: date | None = None
    fecha_referencia: date | None = None
    dias_atraso: int = 0
    dias_para_vencer: int | None = None
    detalle: str = ""


class ExposicionCaso(BaseModel):
    obligacion_codigo: str
    infraccion_numeral: str | None
    gravedad: str | None
    descripcion: str
    cita: CitaCaso
    multa_min_uit: float | None
    multa_max_uit: float | None
    min_soles: float | None
    max_soles: float | None
    monto_determinado: bool
    nota: str
    rotulo: str


class CaseResult(BaseModel):
    case: CaseInput
    categoria: str
    evento_descripcion: str
    obligaciones: list[ObligacionCaso]
    plazos: list[PlazoCaso]
    exposicion: list[ExposicionCaso]
    claims: list[CaseClaim]
    claims_rechazados: list[dict[str, Any]] = Field(default_factory=list)
    resumen: str
    resumen_origen: Literal["llm", "plantilla"]
    audit_result: AuditResult | None
    auditoria_error: str | None = None
    publicable: bool  # solo ALLOW / WARN; BLOCK, ESCALATE o sin auditoria => no
    sin_fundamento: bool  # sin obligaciones validadas aplicables
    advertencias: list[str] = Field(default_factory=list)
    tiempos_ms: dict[str, float]
    evaluado_en: datetime


class QuestionInput(_Strict):
    pregunta: str = Field(..., min_length=3, max_length=1000,
                          examples=["¿En qué plazo se debe comunicar un ROS a la UIF-Perú?"])
    fecha: date | None = Field(None, description="Fecha de vigencia. Omitida = hoy.")
    rol: Rol = "analista"
    user_id: str = Field("anonimo", min_length=1, max_length=128)


class QuestionResult(BaseModel):
    pregunta: str
    fecha: date
    plan: dict[str, Any]
    citas: list[CitaCaso]
    claims: list[CaseClaim]
    citas_descartadas: list[dict[str, Any]] = Field(default_factory=list)
    respuesta: str
    respuesta_origen: Literal["llm", "plantilla", "sin_fundamento"]
    sin_fundamento: bool
    audit_result: AuditResult | None
    auditoria_error: str | None = None
    publicable: bool
    tiempos_ms: dict[str, float]


class BatchItem(BaseModel):
    case_id: str | None
    ok: bool
    result: CaseResult | None = None
    error: str | None = None
