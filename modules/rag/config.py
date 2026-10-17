"""Settings del modulo rag. Hereda Ollama/LLM/embeddings de shared/config."""
from pathlib import Path

from shared.config import PROJECT_ROOT, BaseAppSettings


class RagSettings(BaseAppSettings):
    # Todo lo que genera la ingesta vive bajo rag_dir (SQLite, Chroma, BM25).
    rag_dir: Path = PROJECT_ROOT / "data" / "processed" / "rag"
    rag_raw_dir: Path = PROJECT_ROOT / "data" / "raw"

    # RRF: k=60 es el valor del paper original; amortigua el peso del rank 1.
    rag_rrf_k: int = 60
    # Candidatos por recuperador ANTES del filtro de vigencia. Se indexan todas
    # las versiones, asi que parte de estos caen al filtrar por fecha.
    rag_candidates_k: int = 30
    rag_default_top_k: int = 5

    use_reranker: bool = False

    @property
    def sqlite_path(self) -> Path:
        return self.rag_dir / "rag.sqlite"

    @property
    def chroma_dir(self) -> Path:
        return self.rag_dir / "chroma"

    @property
    def bm25_path(self) -> Path:
        return self.rag_dir / "bm25.json"

    @property
    def search_log_path(self) -> Path:
        return self.log_dir / "rag_search.jsonl"
