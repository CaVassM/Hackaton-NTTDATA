"""Esquemas JSON que el LLM debe cumplir (chat_json los fuerza en Ollama).

Desviacion consciente del esquema original: plazo_unidad admite "horas",
porque el ROS (art. 58 de la 2660-2015) fija "veinticuatro horas (24)".
"""
from typing import Literal

from pydantic import BaseModel, Field


class ObligacionLLM(BaseModel):
    sujeto: str = Field(..., description="Quien esta obligado, p. ej. 'la empresa', 'el oficial de cumplimiento'")
    accion_requerida: str
    evento_disparador: str | None = None
    plazo_texto: str | None = None
    plazo_valor: int | None = None
    plazo_unidad: Literal["horas", "dias", "meses", "anios"] | None = None
    tipo_plazo: Literal["calendario", "habil", "periodico"] | None = None
    evidencia_requerida: str | None = None
    cita_textual: str = Field(..., description="Fragmento LITERAL y contiguo del articulo")


class ExtraccionObligaciones(BaseModel):
    impone_obligacion: bool
    obligaciones: list[ObligacionLLM] = Field(default_factory=list)


class InfraccionLLM(BaseModel):
    codigo_numeral: str | None = None
    descripcion: str
    gravedad: Literal["leve", "grave", "muy_grave"] | None = None
    sancion_texto: str | None = None
    multa_min_uit: float | None = None
    multa_max_uit: float | None = None
    cita_textual: str
    # Confirmacion del enlace con la categoria buscada (en la misma llamada).
    relacionada_con_categoria: bool = False
    motivo_relacion: str = ""


class ExtraccionInfracciones(BaseModel):
    contiene_infracciones: bool
    infracciones: list[InfraccionLLM] = Field(default_factory=list)
