from pathlib import Path

import yaml

from modules.compliance.domain import Categoria, ComplianceError


def load_categorias(path: Path) -> list[Categoria]:
    """Categorias ordenadas por prioridad (la demo, prioridad 1, va primero)."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        cats = [Categoria(c["codigo"], c["nombre"], c["descripcion_busqueda"], int(c.get("prioridad", 9)))
                for c in raw["categorias"]]
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise ComplianceError(f"categorias.yaml invalido en {path}: {exc}") from exc
    if len({c.codigo for c in cats}) != len(cats):
        raise ComplianceError("categorias.yaml: codigos duplicados")
    return sorted(cats, key=lambda c: (c.prioridad, c.codigo))


def seleccionar(cats: list[Categoria], codigos: list[str] | None) -> list[Categoria]:
    if not codigos:
        return cats
    pedidos = {c.strip().upper() for c in codigos}
    desconocidos = pedidos - {c.codigo for c in cats}
    if desconocidos:
        raise ComplianceError(f"Categorias desconocidas: {sorted(desconocidos)}")
    return [c for c in cats if c.codigo in pedidos]
