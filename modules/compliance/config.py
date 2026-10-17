"""Settings del modulo compliance. Hereda Ollama/LLM/rutas de shared/config."""
from pathlib import Path

from shared.config import PROJECT_ROOT, BaseAppSettings

_HERE = Path(__file__).resolve().parent


class ComplianceSettings(BaseAppSettings):
    compliance_dir: Path = PROJECT_ROOT / "data" / "processed" / "compliance"
    categorias_path: Path = _HERE / "config" / "categorias.yaml"

    # Normas fuente. Cambiables por .env (p. ej. para usar un anexo SINTETICO
    # de demo); el reporte siempre muestra de que norma sale cada cita.
    norma_obligaciones: str = "Resolución SBS N° 2660-2015"
    norma_infracciones: str = "Resolución SBS N° 2755-2018"

    # --- extraccion guiada por el RAG ---
    extraction_top_k: int = 5
    extraction_think: bool = False
    # Articulos largos (p. ej. art. 49) + prompt: el contexto por defecto truncaria.
    extraction_num_ctx: int = 16384

    # --- plazos y exposicion ---
    evidence_csv: Path = PROJECT_ROOT / "data" / "raw" / "compliance" / "evidencia_sintetica.csv"
    feriados_path: Path = PROJECT_ROOT / "data" / "raw" / "compliance" / "feriados.csv"
    por_vencer_dias: int = 7
    # Valor de la UIT en soles. SIN default a proposito: si no se configura,
    # no se calculan soles (nunca se inventa el valor).
    uit_valor: float | None = None

    @property
    def sqlite_path(self) -> Path:
        return self.compliance_dir / "compliance.sqlite"

    @property
    def extraction_log_path(self) -> Path:
        return self.log_dir / "compliance_extraction.jsonl"
