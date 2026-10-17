"""Reintentos con backoff exponencial solo para errores transitorios."""
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

import httpx
import ollama

from shared.logging import get_logger

log = get_logger(__name__)
R = TypeVar("R")


def is_transient(exc: BaseException) -> bool:
    """Un 4xx (modelo inexistente, schema invalido) no se arregla reintentando."""
    if isinstance(exc, (ConnectionError, httpx.TransportError)):
        return True
    if isinstance(exc, ollama.ResponseError):
        return exc.status_code >= 500 or exc.status_code == -1
    return False


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 3
    backoff_s: float = 1.0

    def run(self, fn: Callable[[], R], *, what: str) -> R:
        attempt = 0
        while True:
            try:
                return fn()
            except Exception as exc:
                if attempt >= self.max_retries or not is_transient(exc):
                    raise
                delay = self.backoff_s * (2**attempt)
                log.warning("%s fallo (%s); reintento %d en %.1fs", what, exc, attempt + 1, delay)
                time.sleep(delay)
                attempt += 1
