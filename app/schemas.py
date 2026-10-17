from typing import Any, Literal

from pydantic import BaseModel


class HealthOut(BaseModel):
    status: Literal["ok", "degradado"]
    version: str
    ollama: dict[str, Any]
    modelos: dict[str, str]
    bases: dict[str, Any]
    audit_mode: str
    policy_version: str
    nanda: dict[str, Any]
