"""CLI del modulo rag.

    python -m modules.rag.cli ingest data/raw/sinteticos
    python -m modules.rag.cli search "plazo para atender reclamos" --fecha 2026-06-01
    python -m modules.rag.cli vigente "Resolución SBS N° 1234-2025" 2 --fecha 2026-06-30
    python -m modules.rag.cli historial "Res. SBS 1234-2025" 2
    python -m modules.rag.cli health
"""
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Optional

import typer

from modules.rag import RagError, RagFacade
from shared.logging import configure_logging

app = typer.Typer(add_completion=False, help="RAG temporal sobre normativa SBS")

# La consola de Windows no siempre es UTF-8 y la normativa trae tildes y "N°".
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _rag() -> RagFacade:
    configure_logging()
    return RagFacade.from_settings()


def _fecha(value: Optional[str]) -> Optional[date]:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise typer.BadParameter("Formato AAAA-MM-DD")


def _dump(obj) -> None:
    typer.echo(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


@app.command()
def ingest(carpeta: Path = typer.Argument(None, help="Carpeta o archivo (default: data/raw)")):
    """Parsea normas, versiona articulos y construye los indices."""
    _dump(asdict(_rag().ingest(carpeta)))


@app.command()
def search(
    pregunta: str,
    fecha: Optional[str] = typer.Option(None, help="AAAA-MM-DD; default hoy"),
    top_k: int = typer.Option(5, "--top-k"),
    proyectos: bool = typer.Option(False, "--proyectos", help="Incluir proyectos normativos"),
    norma: Optional[str] = typer.Option(None, help="Restringir a una norma, p. ej. 'Res. SBS 2660-2015'"),
):
    """Busqueda hibrida filtrada por vigencia."""
    res = _rag().search(pregunta, _fecha(fecha), top_k, proyectos, norma=norma)
    origen = " (hoy, por defecto)" if res.fecha_por_defecto else ""
    typer.echo(f"Vigencia al {res.fecha}{origen} - {len(res.fragmentos)} resultado(s)\n")
    for i, f in enumerate(res.fragmentos, 1):
        c = f.cita
        hasta = c.vigente_hasta or "vigente"
        typer.echo(f"[{i}] {c.norma}, art. {c.articulo}  (version {c.version_id}, {c.vigente_desde} -> {hasta})")
        if c.creada_por != c.norma:
            typer.echo(f"    texto introducido por {c.creada_por}")
        if c.es_proyecto:
            typer.echo("    PROYECTO: no es normativa vigente")
        if c.fue_modificada:
            typer.echo(f"    AVISO: modificado posteriormente; version vigente hoy: {c.version_vigente_actual_id}")
        typer.echo(f"    score={c.score}\n    {f.texto[:300]}\n")


@app.command()
def vigente(norma: str, articulo: str, fecha: Optional[str] = typer.Option(None)):
    """Texto vigente de un articulo en una fecha."""
    v = _rag().texto_vigente(norma, articulo, _fecha(fecha))
    _dump(asdict(v) if v else {"version": None, "detalle": "el articulo no regia en esa fecha"})


@app.command()
def historial(norma: str, articulo: str):
    """Todas las versiones de un articulo."""
    _dump([asdict(v) for v in _rag().historial(norma, articulo)])


@app.command()
def health():
    """Estado de Ollama e indices."""
    _dump(_rag().health())


def main() -> None:
    try:
        app()
    except RagError as exc:
        typer.echo(f"Error: {type(exc).__name__}: {exc}", err=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
