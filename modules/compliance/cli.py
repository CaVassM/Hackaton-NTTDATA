"""CLI del modulo compliance.

    python -m modules.compliance.cli extract-obligations --categorias BAN-004,BAN-005,BAN-007
    python -m modules.compliance.cli extract-obligations            # todas, por prioridad
"""
import json
import sys
from dataclasses import asdict
from datetime import date
from typing import Optional

import typer
from tqdm import tqdm

from modules.compliance.facade import ComplianceFacade
from shared.logging import configure_logging

app = typer.Typer(add_completion=False, help="Obligaciones LA/FT, plazos y exposicion potencial")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


@app.callback()
def _grupo() -> None:
    """Subcomandos: extract-obligations, extract-infractions, proposals, review, report."""


def _facade() -> ComplianceFacade:
    configure_logging()
    return ComplianceFacade.from_settings()


def _cats(value: Optional[str]) -> list[str] | None:
    return [c for c in value.split(",") if c.strip()] if value else None


def _fecha(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


def _dump(obj) -> None:
    typer.echo(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


class _Barra:
    """Barra de progreso (stderr): funciona tambien en background con log a archivo."""

    def __init__(self):
        self.bar = None

    def __call__(self, i: int, total: int, label: str) -> None:
        if self.bar is None:
            self.bar = tqdm(total=total, unit="art", file=sys.stderr, mininterval=1)
        self.bar.set_postfix_str(label)
        self.bar.update(1)


@app.command("extract-obligations")
def extract_obligations(
    categorias: Optional[str] = typer.Option(None, help="BAN-004,BAN-005 (default: todas por prioridad)"),
    fecha: Optional[str] = typer.Option(None, help="Fecha de vigencia AAAA-MM-DD (default hoy)"),
):
    """Extrae obligaciones (propuestas) guiadas por el RAG. Reanudable via cache."""
    _dump(asdict(_facade().extract_obligations(_cats(categorias), _fecha(fecha), progress=_Barra())))


if __name__ == "__main__":
    app()
