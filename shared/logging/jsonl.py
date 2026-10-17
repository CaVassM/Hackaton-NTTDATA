"""Escritor append-only de eventos en JSON Lines (un objeto JSON por linea)."""
import json
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


def _default(obj: Any) -> Any:
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"No serializable: {type(obj).__name__}")


class JsonlWriter:
    """Thread-safe: FastAPI atiende endpoints sincronos en un threadpool."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def write(self, event: dict[str, Any]) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(), **event}
        line = json.dumps(record, ensure_ascii=False, default=_default)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
