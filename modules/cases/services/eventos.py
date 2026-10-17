"""Catalogo tipo_evento -> categoria BAN (determinista, desde eventos.yaml)."""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from modules.cases.domain import CasesError, CaseValidationError


@dataclass(frozen=True)
class Evento:
    tipo: str
    categoria: str
    descripcion: str
    fecha_evento: str
    obligaciones: tuple[str, ...] = field(default_factory=tuple)


class CatalogoEventos:
    def __init__(self, path: Path):
        try:
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
            self.eventos = {
                tipo: Evento(tipo, e["categoria"].upper(), e.get("descripcion", ""), e.get("fecha_evento", ""),
                             tuple(c.upper() for c in e.get("obligaciones", []) or []))
                for tipo, e in raw["eventos"].items()
            }
        except (OSError, KeyError, TypeError, AttributeError, yaml.YAMLError) as exc:
            raise CasesError(f"eventos.yaml invalido en {path}: {exc}") from exc

    @property
    def tipos(self) -> list[str]:
        return sorted(self.eventos)

    def resolver(self, tipo: str) -> Evento:
        if tipo not in self.eventos:
            raise CaseValidationError("tipo_evento", f"tipo_evento desconocido: {tipo!r}", self.tipos)
        return self.eventos[tipo]
