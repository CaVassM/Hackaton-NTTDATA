"""Settings del modulo audit. Hereda Ollama/LLM/rutas de shared/config."""
from pathlib import Path

from shared.config import PROJECT_ROOT, BaseAppSettings

_HERE = Path(__file__).resolve().parent


class AuditSettings(BaseAppSettings):
    # Politica versionada: cada AuditResult lleva su policy_version.
    audit_policy_path: Path = _HERE / "policies" / "aml-audit-v1.yaml"

    # --- A2A ---
    # URL publica con la que el auditor se anuncia en su Agent Card.
    a2a_public_url: str = "http://localhost:8100"
    # Autenticacion: token -> identidad. JSON en .env:
    #   A2A_AGENT_TOKENS='{"copilot": "token-largo-y-aleatorio"}'
    # Vacio = nadie entra (default seguro).
    a2a_agent_tokens: dict[str, str] = {}
    # Autorizacion: identidades que pueden pedir auditorias. JSON en .env:
    #   A2A_ALLOWED_AGENTS='["copilot"]'
    a2a_allowed_agents: list[str] = ["copilot"]

    @property
    def audit_log_path(self) -> Path:
        return self.log_dir / "audit_events.jsonl"


def default_registry_path() -> Path:
    return PROJECT_ROOT / "nanda" / "registry.yaml"
