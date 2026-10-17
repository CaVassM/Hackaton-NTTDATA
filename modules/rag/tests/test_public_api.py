"""Contrato publico del modulo y frontera de imports entre modulos."""
import re

import modules.rag as rag_pkg
from modules.rag import RagFacade
from shared.config import PROJECT_ROOT

_IMPORT_INTERNAL = re.compile(r"^\s*(?:from|import)\s+modules\.rag\.", re.MULTILINE)


def test_facade_expone_lo_que_consumen_otros_modulos():
    for metodo in (
        "ingest", "search", "texto_vigente", "historial", "cambios_por_norma",
        "get_version", "vigente_en", "versiones_posteriores", "health",
    ):
        assert callable(getattr(RagFacade, metodo)), metodo


def test_exporta_entidades_y_router():
    for nombre in ("RagFacade", "RagSettings", "Cita", "Fragmento", "VersionDetalle", "ResultadoBusqueda"):
        assert nombre in rag_pkg.__all__
    assert callable(rag_pkg.create_rag_router)


def test_ningun_otro_modulo_importa_internals_de_rag():
    """Fuera de modules/rag solo se permite `from modules.rag import ...`."""
    infractores = []
    for py in PROJECT_ROOT.rglob("*.py"):
        rel = py.relative_to(PROJECT_ROOT)
        if rel.parts[:2] == ("modules", "rag") or any(p.startswith(".") for p in rel.parts):
            continue
        if _IMPORT_INTERNAL.search(py.read_text(encoding="utf-8", errors="ignore")):
            infractores.append(str(rel))
    assert not infractores, f"Importan internals de rag: {infractores}"


def test_shared_no_depende_de_modulos():
    for py in (PROJECT_ROOT / "shared").rglob("*.py"):
        assert not re.search(r"^\s*(?:from|import)\s+modules\b", py.read_text(encoding="utf-8"), re.MULTILINE), py
