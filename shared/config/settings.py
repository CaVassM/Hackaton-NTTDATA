"""Settings base del proyecto, leidos de variables de entorno / .env.

Cada modulo hereda de BaseAppSettings y agrega lo suyo. A diferencia de un
modulo de constantes, aqui NO se valida nada al importar: la validacion ocurre
al instanciar, asi los tests pueden construir settings a medida sin .env.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Este archivo vive en shared/config/, asi que la raiz esta dos niveles arriba.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class BaseAppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Rutas ---
    data_dir: Path = PROJECT_ROOT / "data"
    log_dir: Path = PROJECT_ROOT / "data" / "processed" / "logs"

    # --- Ollama ---
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_timeout_s: float = 120.0
    ollama_max_retries: int = 3
    ollama_retry_backoff_s: float = 1.0

    # --- LLM ---
    llm_model: str = "qwen3.5:4b"
    llm_think: bool = False
    llm_temperature: float = 0.0
    # Sin esto Ollama usa su contexto por defecto y TRUNCA en silencio desde el
    # inicio del prompt, comiendose el system prompt.
    llm_num_ctx: int = 8192

    # --- Embeddings ---
    embed_model: str = "qwen3-embedding:0.6b-q8_0"
    embed_batch_size: int = 32

    log_level: str = "INFO"


@lru_cache
def get_base_settings() -> BaseAppSettings:
    return BaseAppSettings()
