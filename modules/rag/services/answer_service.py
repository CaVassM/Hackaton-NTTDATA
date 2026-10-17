"""Generacion de respuesta: SOLO interfaz + stub.

La respuesta con LLM la implementa otro modulo (orquestador). Este stub
extractivo existe para que la UI y los tests de integracion tengan algo que
consumir sin LLM, y para fijar el contrato.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

from modules.rag.domain import Cita, ResultadoBusqueda


@dataclass(frozen=True, slots=True)
class Respuesta:
    texto: str
    citas: list[Cita]
    generada_por: str


class AnswerService(ABC):
    @abstractmethod
    def answer(self, pregunta: str, resultado: ResultadoBusqueda) -> Respuesta: ...


class StubAnswerService(AnswerService):
    """Devuelve los fragmentos recuperados tal cual, con su referencia."""

    def answer(self, pregunta, resultado):
        if not resultado.fragmentos:
            return Respuesta("No se encontro normativa vigente para la consulta.", [], "stub")
        partes = []
        for f in resultado.fragmentos:
            aviso = " [MODIFICADO POSTERIORMENTE]" if f.cita.fue_modificada else ""
            partes.append(f"{f.cita.norma}, art. {f.cita.articulo}{aviso}:\n{f.texto}")
        return Respuesta("\n\n".join(partes), [f.cita for f in resultado.fragmentos], "stub")
