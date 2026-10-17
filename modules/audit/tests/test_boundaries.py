"""Regla de dependencias de audit: solo shared/* y la API publica de modules.rag."""
import re

from shared.config import PROJECT_ROOT

AUDIT = PROJECT_ROOT / "modules" / "audit"
_IMPORT = re.compile(r"^\s*(?:from|import)\s+([\w.]+)", re.MULTILINE)


def _imports():
    for py in AUDIT.rglob("*.py"):
        for mod in _IMPORT.findall(py.read_text(encoding="utf-8")):
            yield py.relative_to(PROJECT_ROOT), mod


def test_audit_solo_usa_la_api_publica_de_rag():
    malos = [(str(p), m) for p, m in _imports() if m.startswith("modules.rag.")]
    assert not malos, malos


def test_audit_no_importa_otros_modulos():
    malos = [(str(p), m) for p, m in _imports()
             if m.startswith("modules.") and not m.startswith(("modules.audit", "modules.rag"))]
    assert not malos, malos


def test_nanda_no_importa_modulos():
    for py in (PROJECT_ROOT / "nanda").rglob("*.py"):
        if "tests" in py.parts:
            continue
        assert not [m for m in _IMPORT.findall(py.read_text(encoding="utf-8")) if m.startswith("modules")], py
