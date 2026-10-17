"""Fuente de evidencia interna (la prepara otro companero). Formato minimo
acordado (D3), una fila por caso:

    obligacion_codigo, sujeto_id, fecha_evento, fecha_cumplimiento, fecha_corte

obligacion_codigo: categoria (BAN-004) o una obligacion concreta (BAN-004-05).
fecha_cumplimiento y fecha_corte pueden ir vacias.
"""
from abc import ABC, abstractmethod

from modules.compliance.domain import EvidenciaInterna, Obligacion


class EvidenceSource(ABC):
    @abstractmethod
    def load(self) -> list[EvidenciaInterna]: ...

    def para(self, o: Obligacion) -> list[EvidenciaInterna]:
        """Filas que aplican a la obligacion: por su codigo o por su categoria."""
        return [e for e in self.load() if e.obligacion_codigo in (o.codigo, o.categoria)]
