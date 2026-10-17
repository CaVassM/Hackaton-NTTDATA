"""Consultas temporales deterministas. Cada una es una funcion con SQL fijo:
el LLM (de otros modulos) puede elegir QUE funcion llamar, nunca escribe SQL.
"""
from collections.abc import Callable
from datetime import date

from modules.rag.domain import (
    ArticuloNoEncontrado,
    CambiosNorma,
    NormaNoEncontrada,
    VersionDetalle,
    VersionNoEncontrada,
)
from modules.rag.repositories import SqlRepository
from modules.rag.services.parsers import normalizar_codigo


class TemporalService:
    def __init__(self, sql: SqlRepository, today: Callable[[], date] = date.today):
        self.sql = sql
        self.today = today

    # --------------------------------------------------------------- helpers
    def _norma(self, codigo: str) -> str:
        cod = normalizar_codigo(codigo)
        if self.sql.get_norma(cod) is None:
            raise NormaNoEncontrada(codigo)
        return cod

    def _articulo(self, norma: str, articulo: str) -> tuple[str, str]:
        cod = self._norma(norma)
        num = str(articulo).strip()
        if self.sql.get_articulo(cod, num) is None:
            raise ArticuloNoEncontrado(f"{cod} art. {num}")
        return cod, num

    # --------------------------------------------------------------- publico
    def texto_vigente(self, norma: str, articulo: str, fecha: date | None = None) -> VersionDetalle | None:
        """Version que regia en `fecha` (hoy si None). None = el articulo existe
        pero no regia en esa fecha (antes de su vigencia, o es un proyecto)."""
        cod, num = self._articulo(norma, articulo)
        return self.sql.version_en_fecha(cod, num, fecha or self.today())

    def listar_versiones(self, norma: str, fecha: date | None = None) -> list[VersionDetalle]:
        """Versiones de los articulos de `norma` que regian en `fecha` (hoy si None),
        una por articulo, incluidas las creadas por modificatorias."""
        cod = self._norma(norma)
        f = fecha or self.today()
        return [d for d in self.sql.versiones_de_norma(cod) if d.vigente_en(f)]

    def resolver_codigo(self, norma: str) -> str:
        """Codigo canonico de una norma existente (NormaNoEncontrada si no existe)."""
        return self._norma(norma)

    def historial(self, norma: str, articulo: str) -> list[VersionDetalle]:
        cod, num = self._articulo(norma, articulo)
        return self.sql.historial(cod, num)

    def cambios_por_norma(self, codigo: str) -> CambiosNorma:
        cod = self._norma(codigo)
        introducidos = [d for d in self.sql.versiones_creadas_por(cod) if d.norma_codigo != cod]
        recibidos = [d for d in self.sql.versiones_de_norma(cod) if d.creada_por_codigo != cod]
        return CambiosNorma(cod, introducidos, recibidos)

    def get_version(self, version_id: int) -> VersionDetalle:
        d = self.sql.get_detalle(version_id)
        if d is None:
            raise VersionNoEncontrada(str(version_id))
        return d

    def vigente_en(self, version_id: int, fecha: date) -> bool:
        return self.get_version(version_id).vigente_en(fecha)

    def versiones_posteriores(self, version_id: int) -> list[VersionDetalle]:
        self.get_version(version_id)  # 404 explicito en vez de lista vacia ambigua
        return self.sql.versiones_posteriores(version_id)
