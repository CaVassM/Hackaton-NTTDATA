# Reutiliza las fixtures del auditor (rag sintetico, settings, spy) para el e2e del cliente.
from modules.audit.tests.conftest import audit, rag, settings, spy  # noqa: F401
