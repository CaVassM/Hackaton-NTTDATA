"""Entidades del dominio normativo. Puras: sin SQL, sin Chroma, sin Ollama.

Fechas de vigencia: intervalo semiabierto [vigente_desde, vigente_hasta).
`vigente_hasta=None` significa "sigue vigente". El dia en que entra en vigor
la version nueva, la vieja YA no rige: por eso "hasta" es exclusivo.
"""
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class EstadoNorma(StrEnum):
    VIGENTE = "vigente"
    PROYECTO = "proyecto"
    DEROGADA = "derogada"


def en_intervalo(fecha: date, desde: date, hasta: date | None) -> bool:
    """vigente_desde <= fecha < COALESCE(vigente_hasta, +inf)."""
    return desde <= fecha and (hasta is None or fecha < hasta)


@dataclass(frozen=True, slots=True)
class Norma:
    id: int | None
    codigo: str
    titulo: str
    fecha_emision: date
    tipo: str
    estado: EstadoNorma


@dataclass(frozen=True, slots=True)
class Articulo:
    id: int | None
    norma_id: int
    # Texto, no int: existen articulos como "2-A" o "15-B".
    numero: str


@dataclass(frozen=True, slots=True)
class Version:
    id: int | None
    articulo_id: int
    texto: str
    vigente_desde: date
    vigente_hasta: date | None
    creada_por: int  # FK norma: la que puso este texto en vigor
    reemplaza_a: int | None = None  # FK version: la que esta version sustituye

    def cubre(self, fecha: date) -> bool:
        """Solo el intervalo; la regla de 'proyecto' la aplica el servicio."""
        return en_intervalo(fecha, self.vigente_desde, self.vigente_hasta)


@dataclass(frozen=True, slots=True)
class VersionDetalle:
    """Version + contexto necesario para citarla sin mas consultas.

    Es lo que devuelve la fachada (get_version, historial, texto_vigente...).
    """

    version_id: int
    texto: str
    norma_codigo: str  # norma a la que pertenece el articulo
    norma_titulo: str
    articulo_numero: str
    vigente_desde: date
    vigente_hasta: date | None
    creada_por_codigo: str  # norma que creo ESTA version (base o modificatoria)
    estado_norma_creadora: EstadoNorma
    reemplaza_a: int | None

    @property
    def es_proyecto(self) -> bool:
        return self.estado_norma_creadora == EstadoNorma.PROYECTO

    def vigente_en(self, fecha: date) -> bool:
        # Un proyecto nunca rige, aunque su intervalo cubra la fecha.
        return not self.es_proyecto and en_intervalo(fecha, self.vigente_desde, self.vigente_hasta)


@dataclass(frozen=True, slots=True)
class Cita:
    """Referencia exacta a la fuente de un resultado."""

    norma: str
    articulo: str
    version_id: int
    vigente_desde: date
    vigente_hasta: date | None
    # True si existe una version posterior de este articulo (el texto citado
    # fue o sera reemplazado).
    fue_modificada: bool
    # Version que rige HOY; puede diferir de version_id si se consulto otra fecha.
    version_vigente_actual_id: int | None
    score: float
    creada_por: str = ""
    reemplaza_a: int | None = None
    es_proyecto: bool = False


@dataclass(frozen=True, slots=True)
class Fragmento:
    """Un resultado de busqueda: el texto recuperado y su cita."""

    texto: str
    cita: Cita


@dataclass(frozen=True, slots=True)
class ResultadoBusqueda:
    query: str
    fecha: date  # fecha efectivamente usada para el filtro de vigencia
    fecha_por_defecto: bool  # True si no se paso fecha y el codigo uso "hoy"
    fragmentos: list[Fragmento]


@dataclass(frozen=True, slots=True)
class CambiosNorma:
    codigo: str
    # Versiones que ESTA norma creo sobre articulos de otras normas (lo que modifico).
    introducidos: list[VersionDetalle]
    # Versiones de los articulos de ESTA norma creadas por otras (lo que le modificaron).
    recibidos: list[VersionDetalle]
