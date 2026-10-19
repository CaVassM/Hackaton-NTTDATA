"""Implementaciones de LLMClient y EmbeddingClient sobre la libreria `ollama`."""
import json
from collections.abc import Sequence
from typing import Any

import ollama
from pydantic import BaseModel

from shared.config import BaseAppSettings
from shared.llm.interfaces import ChatMessage, EmbeddingClient, LLMClient
from shared.llm.retry import RetryPolicy
from shared.logging import get_logger

log = get_logger(__name__)

# qwen3-embedding es instruction-aware: la CONSULTA lleva la instruccion de la
# tarea y los DOCUMENTOS van tal cual. Ponerla en ambos lados degrada el recall.
QUERY_INSTRUCTION = (
    "Instruct: Dada una consulta sobre normativa bancaria, recupera los artículos relevantes\n"
    "Query: "
)


def _retry_from(settings: BaseAppSettings) -> RetryPolicy:
    return RetryPolicy(settings.ollama_max_retries, settings.ollama_retry_backoff_s)


class OllamaLLMClient(LLMClient):
    def __init__(
        self,
        model: str,
        *,
        host: str = "http://127.0.0.1:11434",
        timeout_s: float = 120.0,
        retry: RetryPolicy | None = None,
        default_think: bool = False,
        default_options: dict[str, Any] | None = None,
        client: ollama.Client | None = None,
    ):
        self.model_name = model
        self.default_think = default_think
        self.default_options = default_options or {}
        self._retry = retry or RetryPolicy()
        self._client = client or ollama.Client(host=host, timeout=timeout_s)
        # Se aprende en la primera llamada: modelos como gemma3 rechazan `think`.
        self._supports_think = True

    @classmethod
    def from_settings(cls, settings: BaseAppSettings) -> "OllamaLLMClient":
        return cls(
            settings.llm_model,
            host=settings.ollama_host,
            timeout_s=settings.ollama_timeout_s,
            retry=_retry_from(settings),
            default_think=settings.llm_think,
            default_options={
                "temperature": settings.llm_temperature,
                "num_ctx": settings.llm_num_ctx,
            },
        )

    # ------------------------------------------------------------------ helpers
    def _opts(self, options: dict[str, Any] | None) -> dict[str, Any]:
        return {**self.default_options, **(options or {})}

    def _think(self, think: bool | None) -> bool | None:
        if not self._supports_think:
            return None
        return self.default_think if think is None else think

    def _call(self, fn_name: str, *, think: bool | None, **kwargs: Any) -> Any:
        fn = getattr(self._client, fn_name)

        def once() -> Any:
            try:
                return fn(model=self.model_name, think=self._think(think), **kwargs)
            except ollama.ResponseError as exc:
                if "does not support thinking" in str(exc) and self._supports_think:
                    log.info("%s no soporta 'think'; se omite en adelante", self.model_name)
                    self._supports_think = False
                    return fn(model=self.model_name, **kwargs)
                raise

        return self._retry.run(once, what=f"ollama.{fn_name}")

    # --------------------------------------------------------------- interfaz
    def generate(self, prompt, *, system=None, think=None, options=None) -> str:
        resp = self._call("generate", prompt=prompt, system=system, think=think, options=self._opts(options))
        return resp.response

    def chat(self, messages: Sequence[ChatMessage], *, think=None, options=None) -> str:
        resp = self._call("chat", messages=list(messages), think=think, options=self._opts(options))
        return resp.message.content

    def chat_json(self, messages, schema, *, think=None, options=None):
        is_model = isinstance(schema, type) and issubclass(schema, BaseModel)
        json_schema = schema.model_json_schema() if is_model else schema
        resp = self._call(
            "chat",
            messages=list(messages),
            format=json_schema,
            think=think,
            # temperature 0: la salida estructurada no gana nada con variedad.
            options=self._opts({"temperature": 0, **(options or {})}),
        )
        content = resp.message.content
        return schema.model_validate_json(content) if is_model else json.loads(content)


class OllamaEmbeddingClient(EmbeddingClient):
    def __init__(
        self,
        model: str,
        *,
        host: str = "http://127.0.0.1:11434",
        timeout_s: float = 120.0,
        retry: RetryPolicy | None = None,
        batch_size: int = 32,
        query_instruction: str = QUERY_INSTRUCTION,
        client: ollama.Client | None = None,
    ):
        self.model_name = model
        self.batch_size = batch_size
        self.query_instruction = query_instruction
        self._retry = retry or RetryPolicy()
        self._client = client or ollama.Client(host=host, timeout=timeout_s)

    @classmethod
    def from_settings(cls, settings: BaseAppSettings) -> "OllamaEmbeddingClient":
        return cls(
            settings.embed_model,
            host=settings.ollama_host,
            timeout_s=settings.ollama_timeout_s,
            retry=_retry_from(settings),
            batch_size=settings.embed_batch_size,
        )

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        resp = self._retry.run(
            lambda: self._client.embed(model=self.model_name, input=inputs),
            what="ollama.embed",
        )
        return [list(v) for v in resp.embeddings]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            out.extend(self._embed(list(texts[i : i + self.batch_size])))
        return out

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self.query_instruction + text])[0]
