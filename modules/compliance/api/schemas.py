from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class ExtractRequest(BaseModel):
    tipo: Literal["obligaciones", "infracciones", "todo"] = "obligaciones"
    categorias: list[str] | None = Field(None, examples=[["BAN-004", "BAN-005", "BAN-007"]])
    fecha: date | None = None


class ReviewRequest(BaseModel):
    aprobar: bool
    revisor: str = Field(..., min_length=1, max_length=128)
    comentario: str | None = Field(None, max_length=2000)


class ReportRequest(BaseModel):
    fecha_corte: date | None = None
    categorias: list[str] | None = None
    auditar: bool = False
