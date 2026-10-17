"""DTOs de la API. Se construyen desde las dataclasses del dominio (from_attributes)."""
from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=1000, examples=["¿Cuál es el plazo para atender un reclamo?"])
    fecha: date | None = Field(None, description="Fecha de vigencia a consultar. Omitida = hoy.")
    top_k: int = Field(5, ge=1, le=50)
    incluir_proyectos: bool = False
    norma: str | None = Field(None, description="Restringe a una norma, p. ej. 'Resolución SBS N° 2660-2015'.")


class IngestRequest(BaseModel):
    ruta: str | None = Field(
        None, description="Carpeta o archivo, relativo a data/raw. Omitido = data/raw completo.",
        examples=["sinteticos"],
    )


class CitaOut(_Out):
    norma: str
    articulo: str
    version_id: int
    vigente_desde: date
    vigente_hasta: date | None
    fue_modificada: bool
    version_vigente_actual_id: int | None
    score: float
    creada_por: str
    reemplaza_a: int | None
    es_proyecto: bool


class FragmentoOut(_Out):
    texto: str
    cita: CitaOut


class SearchResponse(_Out):
    query: str
    fecha: date
    fecha_por_defecto: bool
    fragmentos: list[FragmentoOut]


class VersionOut(_Out):
    version_id: int
    texto: str
    norma_codigo: str
    norma_titulo: str
    articulo_numero: str
    vigente_desde: date
    vigente_hasta: date | None
    creada_por_codigo: str
    estado_norma_creadora: str
    reemplaza_a: int | None


class VigenteResponse(BaseModel):
    norma: str
    articulo: str
    fecha: date
    fecha_por_defecto: bool
    # null no es error: el articulo existe pero no regia en esa fecha.
    version: VersionOut | None


class VigenteEnResponse(BaseModel):
    version_id: int
    fecha: date
    vigente: bool


class CambiosOut(_Out):
    codigo: str
    introducidos: list[VersionOut]
    recibidos: list[VersionOut]


class IngestResponse(_Out):
    archivos: int
    normas_nuevas: list[str]
    normas_omitidas: list[str]
    versiones_creadas: int
    versiones_cerradas: int
    modificaciones_aplicadas: list[str]
    advertencias: list[str]
    embebidas: int
    segundos: float
