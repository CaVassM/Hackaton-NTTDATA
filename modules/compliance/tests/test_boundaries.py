"""compliance solo importa shared/* y la API publica de modules.rag y modules.audit."""
import re

from shared.config import PROJECT_ROOT

_IMPORT = re.compile(r"^\s*(?:from|import)\s+([\w.]+)", re.MULTILINE)


def test_compliance_solo_usa_apis_publicas():
    malos = []
    for py in (PROJECT_ROOT / "modules" / "compliance").rglob("*.py"):
        for mod in _IMPORT.findall(py.read_text(encoding="utf-8")):
            if mod.startswith("modules.") and not (mod.startswith("modules.compliance") or mod in ("modules.rag", "modules.audit")):
                malos.append((str(py.relative_to(PROJECT_ROOT)), mod))
    assert not malos, malos
