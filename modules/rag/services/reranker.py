"""Segunda etapa opcional del retrieval. Desactivada por defecto (USE_RERANKER=false).

Con el corpus pequeno de la hackaton, BM25+denso+RRF basta; el reranker por
LLM cuesta una llamada por candidato. Queda listo para activarlo si hace falta.
"""
from abc import ABC, abstractmethod
from collections.abc import Sequence

from pydantic import BaseModel, Field

from shared.llm import LLMClient
from shared.logging import get_logger

log = get_logger(__name__)


class Reranker(ABC):
    enabled: bool = True

    @abstractmethod
    def rerank(self, query: str, candidatos: Sequence[tuple[int, str]], top_n: int) -> list[tuple[int, float]]:
        """Recibe [(version_id, texto)] y devuelve [(version_id, score)] ordenado."""


class NoOpReranker(Reranker):
    """Conserva el orden de la fusion. `enabled=False` le indica al servicio
    que debe mantener el score RRF."""

    enabled = False

    def rerank(self, query, candidatos, top_n):
        return [(vid, 0.0) for vid, _ in candidatos[:top_n]]


class _Relevancia(BaseModel):
    relevancia: int = Field(ge=0, le=10)


class LLMReranker(Reranker):
    """Pointwise: el LLM puntua 0-10 cada (pregunta, articulo). Salida forzada a JSON."""

    _SYSTEM = (
        "Eres un evaluador de relevancia para normativa bancaria peruana. "
        "Puntua de 0 a 10 cuanto responde el ARTICULO a la CONSULTA. Responde solo el JSON."
    )

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def rerank(self, query, candidatos, top_n):
        scored = []
        for vid, texto in candidatos:
            try:
                out = self.llm.chat_json(
                    [
                        {"role": "system", "content": self._SYSTEM},
                        {"role": "user", "content": f"CONSULTA: {query}\n\nARTICULO:\n{texto[:2000]}"},
                    ],
                    _Relevancia,
                    think=False,
                )
                scored.append((vid, out.relevancia / 10))
            except Exception as exc:  # noqa: BLE001 - un candidato fallido no tumba la busqueda
                log.warning("Reranker fallo en version %s: %s", vid, exc)
                scored.append((vid, 0.0))
        scored.sort(key=lambda p: p[1], reverse=True)
        return scored[:top_n]
