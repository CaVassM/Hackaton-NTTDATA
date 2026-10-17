"""Contratos de LLM y embeddings. Los servicios dependen de ESTO, no de Ollama.

Asi los tests inyectan fakes deterministas y, si manana se cambia de runtime,
solo se escribe otra implementacion.
"""
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, Literal, TypedDict, TypeVar, overload

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMClient(ABC):
    """Cliente de generacion.

    `think` es por llamada: None usa el default del cliente (LLM_THINK), True o
    False lo pisa solo para esa llamada.
    """

    model_name: str

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        think: bool | None = None,
        options: dict[str, Any] | None = None,
    ) -> str: ...

    @abstractmethod
    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        think: bool | None = None,
        options: dict[str, Any] | None = None,
    ) -> str: ...

    @overload
    def chat_json(
        self,
        messages: Sequence[ChatMessage],
        schema: type[T],
        *,
        think: bool | None = None,
        options: dict[str, Any] | None = None,
    ) -> T: ...

    @overload
    def chat_json(
        self,
        messages: Sequence[ChatMessage],
        schema: dict[str, Any],
        *,
        think: bool | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def chat_json(self, messages, schema, *, think=None, options=None):
        """Chat con salida forzada a un JSON schema.

        Si `schema` es un modelo Pydantic devuelve la instancia validada; si es
        un dict (JSON schema) devuelve el dict parseado.
        """


class EmbeddingClient(ABC):
    """Embeddings asimetricos: documento y consulta pueden codificarse distinto."""

    model_name: str

    @abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    @abstractmethod
    def embed_query(self, text: str) -> list[float]: ...
