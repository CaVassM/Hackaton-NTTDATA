"""Healthcheck: Ollama responde y los modelos requeridos estan descargados."""
from collections.abc import Iterable
from dataclasses import dataclass, field

import ollama

from shared.config import BaseAppSettings


def _normalize(name: str) -> str:
    # Ollama lista "modelo:tag"; sin tag explicito el tag es "latest".
    return name if ":" in name else f"{name}:latest"


@dataclass
class HealthReport:
    host: str
    reachable: bool
    models: dict[str, bool] = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.reachable and all(self.models.values())

    @property
    def missing(self) -> list[str]:
        return [m for m, present in self.models.items() if not present]


def check_ollama(host: str, required_models: Iterable[str], timeout_s: float = 5.0) -> HealthReport:
    required = list(required_models)
    try:
        listed = ollama.Client(host=host, timeout=timeout_s).list()
    except Exception as exc:  # noqa: BLE001 - cualquier fallo = no disponible
        return HealthReport(host, reachable=False, models={m: False for m in required}, error=str(exc))

    available = {_normalize(m.model) for m in listed.models}
    return HealthReport(
        host,
        reachable=True,
        models={m: _normalize(m) in available for m in required},
    )


def check_ollama_from_settings(settings: BaseAppSettings) -> HealthReport:
    return check_ollama(settings.ollama_host, [settings.llm_model, settings.embed_model])
