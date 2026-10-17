"""Logging de texto para consola, comun a todos los modulos."""
import logging

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_configured = False


def configure_logging(level: str = "INFO") -> None:
    """Configura el logger raiz una sola vez (idempotente)."""
    global _configured
    if _configured:
        return
    logging.basicConfig(level=level.upper(), format=_FORMAT)
    # chromadb y httpx son muy verbosos en INFO.
    for noisy in ("httpx", "chromadb", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
