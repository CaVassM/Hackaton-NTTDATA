"""CLI de cases (usa la misma fachada que la API).

    python -m modules.cases.cli batch data/cases/ejemplos/plantilla.csv
    python -m modules.cases.cli batch data/cases/ejemplos/ingreso_empleado.json
    python -m modules.cases.cli question "¿En qué plazo se comunica un ROS?"
"""
import json
import sys
from pathlib import Path
from typing import Optional

import typer

from shared.logging import configure_logging

app = typer.Typer(add_completion=False, help="Evaluacion de casos de cumplimiento LA/FT")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


@app.callback()
def _grupo() -> None:
    """Subcomandos: batch, question, schema."""


def _facade():
    configure_logging()
    from modules.cases import CasesFacade

    return CasesFacade.from_settings()


@app.command()
def batch(archivo: Path, json_out: bool = typer.Option(False, "--json")):
    """Evalua un archivo .json (objeto o lista de CaseInput) o .csv (plantilla)."""
    f = _facade()
    texto = archivo.read_text(encoding="utf-8-sig")
    if archivo.suffix.lower() == ".csv":
        casos = f.parse_csv(texto)
    else:
        data = json.loads(texto)
        casos = data if isinstance(data, list) else [data]
    items = f.batch(casos)
    if json_out:
        typer.echo(json.dumps([i.model_dump(mode="json") for i in items], ensure_ascii=False, indent=2))
        return
    for i in items:
        if not i.ok:
            typer.echo(f"[ERROR] {i.case_id}: {i.error}")
            continue
        r = i.result
        dec = r.audit_result.decision if r.audit_result else f"SIN AUDITORIA ({r.auditoria_error})"
        estados = ", ".join(f"{p.obligacion_codigo}={p.estado}({p.dias_atraso}d)" for p in r.plazos) or "sin plazos"
        typer.echo(f"[{dec}] {r.case.case_id} {r.case.tipo_evento} -> {r.categoria} | {estados} | {r.tiempos_ms['total_ms']} ms")
        typer.echo(f"    {r.resumen[:300]}")


@app.command()
def question(pregunta: str, fecha: Optional[str] = typer.Option(None)):
    """Pregunta normativa auditada."""
    r = _facade().question({"pregunta": pregunta, "fecha": fecha})
    typer.echo(f"[{r.audit_result.decision if r.audit_result else 'SIN AUDITORIA'}] {r.respuesta}")
    for c in r.citas:
        typer.echo(f"   - {c.norma} art. {c.articulo} v{c.version_id} (vigente: {c.vigente_en_fecha})")


@app.command()
def schema():
    """Imprime el JSON Schema de CaseInput y los tipos de evento validos."""
    typer.echo(json.dumps(_facade().schema(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
