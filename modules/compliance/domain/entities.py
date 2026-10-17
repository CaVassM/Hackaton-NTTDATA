"""Entidades del modulo compliance. Puras: sin SQL, sin LLM, sin RAG."""
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

ROTULO_EXPOSICION = "exposición potencial, no sanción determinada"
MONTO_NO_DETERMINADO = "monto no determinado"


class EstadoPropuesta(StrEnum):
    PROPUESTA = "propuesta"
    VALIDADA = "validada"
    RECHAZADA = "rechazada"


class TipoPropuesta(StrEnum):
    OBLIGACION = "obl"
    INFRACCION = "inf"
    ENLACE = "enl"


class EstadoPlazo(StrEnum):
    CUMPLIDO = "cumplido"
    ATRASADO = "atrasado"
    POR_VENCER = "por_vencer"
    SIN_PLAZO_DEFINIDO = "sin_plazo_definido"
    SIN_EVIDENCIA = "sin_evidencia"


# Orden de gravedad para resumir varias filas de evidencia en un estado.
GRAVEDAD_ESTADO = {
    EstadoPlazo.ATRASADO: 4,
    EstadoPlazo.POR_VENCER: 3,
    EstadoPlazo.SIN_PLAZO_DEFINIDO: 2,
    EstadoPlazo.SIN_EVIDENCIA: 1,
    EstadoPlazo.CUMPLIDO: 0,
}


@dataclass(frozen=True)
class Categoria:
    codigo: str
    nombre: str
    descripcion_busqueda: str
    prioridad: int = 9


@dataclass(frozen=True)
class Revision:
    estado: EstadoPropuesta = EstadoPropuesta.PROPUESTA
    revisado_por: str | None = None
    revisado_en: datetime | None = None
    comentario: str | None = None


@dataclass(frozen=True)
class Obligacion:
    id: int | None
    codigo: str  # BAN-004-01: categoria + correlativo
    categoria: str
    sujeto: str
    accion_requerida: str
    evento_disparador: str | None
    plazo_texto: str | None
    plazo_valor: int | None
    plazo_unidad: str | None  # horas | dias | meses | anios
    tipo_plazo: str | None  # calendario | habil | periodico
    evidencia_requerida: str | None
    cita_textual: str
    version_id: int
    norma_codigo: str
    articulo_numero: str
    score_recuperacion: float
    modelo: str
    revision: Revision = field(default_factory=Revision)

    @property
    def proposal_id(self) -> str:
        return f"{TipoPropuesta.OBLIGACION}-{self.id}"


@dataclass(frozen=True)
class Infraccion:
    id: int | None
    codigo_numeral: str | None
    descripcion: str
    gravedad: str | None  # leve | grave | muy_grave
    sancion_texto: str | None
    multa_min_uit: float | None
    multa_max_uit: float | None
    cita_textual: str
    version_id: int
    norma_codigo: str
    articulo_numero: str
    modelo: str
    revision: Revision = field(default_factory=Revision)

    @property
    def proposal_id(self) -> str:
        return f"{TipoPropuesta.INFRACCION}-{self.id}"


@dataclass(frozen=True)
class Enlace:
    """Categoria de obligacion -> infraccion que sanciona su incumplimiento."""

    id: int | None
    categoria: str
    infraccion_id: int
    score: float  # score de recuperacion del RAG
    relacionada: bool  # confirmacion del LLM
    motivo: str
    revision: Revision = field(default_factory=Revision)

    @property
    def proposal_id(self) -> str:
        return f"{TipoPropuesta.ENLACE}-{self.id}"


@dataclass(frozen=True)
class EvidenciaInterna:
    """Una fila del CSV de evidencia interna (formato acordado D3)."""

    obligacion_codigo: str  # BAN-004 (categoria) o BAN-004-01 (obligacion concreta)
    sujeto_id: str
    fecha_evento: date
    fecha_cumplimiento: date | None
    fecha_corte: date | None = None
    fila: int | None = None  # linea en el CSV, para trazabilidad


@dataclass(frozen=True)
class ResultadoPlazo:
    obligacion_codigo: str
    sujeto_id: str | None
    estado: EstadoPlazo
    fecha_evento: date | None = None
    fecha_limite: date | None = None
    fecha_referencia: date | None = None  # cumplimiento, o corte si no se cumplio
    dias_atraso: int = 0
    dias_para_vencer: int | None = None
    detalle: str = ""


@dataclass(frozen=True)
class Exposicion:
    infraccion_id: int
    gravedad: str | None
    multa_min_uit: float | None
    multa_max_uit: float | None
    min_soles: float | None
    max_soles: float | None
    monto_determinado: bool
    nota: str
    rotulo: str = ROTULO_EXPOSICION
