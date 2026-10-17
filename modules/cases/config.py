"""Settings del modulo cases. Hereda Ollama/LLM/rutas de shared/config."""
from pathlib import Path
from typing import Literal

from shared.config import PROJECT_ROOT, BaseAppSettings

_HERE = Path(__file__).resolve().parent


class CasesSettings(BaseAppSettings):
    cases_dir: Path = PROJECT_ROOT / "data" / "processed" / "cases"
    eventos_path: Path = _HERE / "config" / "eventos.yaml"
    expedientes_path: Path = _HERE / "config" / "expedientes.yaml"
    # direct = AuditFacade en proceso; a2a = agente auditor via nanda (A2A 1.0).
    cases_audit_mode: Literal["direct", "a2a"] = "direct"
    # Resumen con LLM (si False, siempre plantilla determinista).
    cases_summary_llm: bool = True
    question_top_k: int = 3

    @property
    def sqlite_path(self) -> Path:
        return self.cases_dir / "cases.sqlite"
