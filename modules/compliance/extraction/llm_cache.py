"""LLM estructurado con cache por (version_id, modelo, hash del prompt).

Reanudable: si la extraccion se corta, al relanzarla las respuestas ya
obtenidas salen de la cache y no se vuelve a llamar al modelo.
JSON invalido / error del modelo: un reintento y luego None (nunca se
inventa una respuesta por defecto).
"""
import hashlib
import json
import time
from collections.abc import Sequence
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from modules.compliance.repositories import SqliteComplianceRepository
from shared.llm import ChatMessage, LLMClient
from shared.logging import get_logger

log = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)


class CachedStructuredLLM:
    def __init__(self, llm: LLMClient, repo: SqliteComplianceRepository, *, think: bool = False, num_ctx: int = 16384):
        self.llm = llm
        self.repo = repo
        self.think = think
        self.num_ctx = num_ctx

    @property
    def model_name(self) -> str:
        return self.llm.model_name

    @staticmethod
    def prompt_hash(messages: Sequence[ChatMessage], schema: type[BaseModel]) -> str:
        payload = json.dumps({"m": list(messages), "s": schema.model_json_schema()}, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def extract(self, version_id: int, messages: Sequence[ChatMessage], schema: type[T]) -> tuple[T | None, dict]:
        """Devuelve (resultado o None, meta {cached, ms, intentos, error})."""
        ph = self.prompt_hash(messages, schema)
        key = hashlib.sha256(f"{version_id}|{self.model_name}|{ph}".encode()).hexdigest()
        if (hit := self.repo.cache_get(key)) is not None:
            return schema.model_validate_json(hit), {"cached": True, "ms": 0, "intentos": 0}

        t0 = time.perf_counter()
        error = None
        for intento in (1, 2):
            try:
                out = self.llm.chat_json(messages, schema, think=self.think, options={"num_ctx": self.num_ctx})
                self.repo.cache_put(key, version_id, self.model_name, ph, out.model_dump_json())
                return out, {"cached": False, "ms": round((time.perf_counter() - t0) * 1000), "intentos": intento}
            except (ValidationError, ValueError) as exc:  # JSON invalido o fuera de esquema
                error = f"{type(exc).__name__}: {str(exc)[:200]}"
                log.warning("Respuesta invalida del LLM (version %s, intento %d): %s", version_id, intento, error)
            except Exception as exc:  # noqa: BLE001 - Ollama caido, timeout...: no tumbar toda la extraccion
                error = f"{type(exc).__name__}: {str(exc)[:200]}"
                log.warning("Fallo del LLM (version %s, intento %d): %s", version_id, intento, error)
        return None, {"cached": False, "ms": round((time.perf_counter() - t0) * 1000), "intentos": 2, "error": error}
