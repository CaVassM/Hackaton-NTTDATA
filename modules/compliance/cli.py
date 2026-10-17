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


@app.command("extract-infractions")
def extract_infractions(
    categorias: Optional[str] = typer.Option(None, help="BAN-004,BAN-005 (default: todas por prioridad)"),
    fecha: Optional[str] = typer.Option(None, help="Fecha de vigencia AAAA-MM-DD (default hoy)"),
):
    """Extrae infracciones + enlace categoria->infraccion (propuestas). Norma: NORMA_INFRACCIONES."""
    _dump(asdict(_facade().extract_infractions(_cats(categorias), _fecha(fecha), progress=_Barra())))


@app.command()
def proposals(
    tipo: Optional[str] = typer.Option(None, help="obl | inf | enl (default: todas)"),
    estado: str = typer.Option("propuesta", help="propuesta | validada | rechazada | todas"),
):
    """Lista propuestas con su cita para validacion humana."""
    from modules.compliance.domain import EstadoPropuesta, TipoPropuesta

    res = _facade().proposals(TipoPropuesta(tipo) if tipo else None,
                              None if estado == "todas" else EstadoPropuesta(estado))
    for o in res.get("obligaciones", []):
        plazo = f"{o.plazo_valor} {o.plazo_unidad} {o.tipo_plazo or ''}".strip() if o.plazo_unidad else "sin plazo"
        typer.echo(f"\n[{o.proposal_id}] {o.codigo} ({o.revision.estado}) {o.norma_codigo} art. {o.articulo_numero} v{o.version_id}")
        typer.echo(f"   {o.sujeto}: {o.accion_requerida}  | plazo: {plazo}")
        typer.echo(f"   CITA: \"{o.cita_textual}\"")
    for i in res.get("infracciones", []):
        multa = f"{i.multa_min_uit}-{i.multa_max_uit} UIT" if (i.multa_min_uit or i.multa_max_uit) else "sin multa en la cita"
        typer.echo(f"\n[{i.proposal_id}] numeral {i.codigo_numeral} ({i.revision.estado}) {i.norma_codigo} v{i.version_id}")
        typer.echo(f"   {i.gravedad or 'gravedad no consta'} | {multa} | {i.descripcion}")
        typer.echo(f"   CITA: \"{i.cita_textual}\"")
    for e in res.get("enlaces", []):
        typer.echo(f"\n[{e.proposal_id}] {e.categoria} -> inf-{e.infraccion_id} ({e.revision.estado}) score={e.score} | {e.motivo}")


@app.command()
def review(
    proposal_id: str = typer.Argument(..., help="obl-N | inf-N | enl-N"),
    revisor: str = typer.Option(..., help="Quien valida (queda registrado)"),
    aprobar: bool = typer.Option(True, "--aprobar/--rechazar"),
    comentario: Optional[str] = typer.Option(None),
):
    """Aprueba o rechaza una propuesta (validacion humana)."""
    _facade().review(proposal_id, aprobar, revisor, comentario)
    typer.echo(f"{proposal_id}: {'validada' if aprobar else 'rechazada'} por {revisor}")


@app.command()
def report(
    fecha_corte: Optional[str] = typer.Option(None, help="AAAA-MM-DD (default hoy)"),
    categorias: Optional[str] = typer.Option(None),
    auditar: bool = typer.Option(False, help="Pasar el reporte por modules/audit antes de mostrarlo"),
    json_out: bool = typer.Option(False, "--json"),
):
    """Reporte por obligacion VALIDADA: estado, atraso, infraccion y exposicion potencial."""
    from modules.audit import AuditFacade

    configure_logging()
    from modules.compliance import ComplianceFacade as CF
    from modules.rag import RagFacade

    rag = RagFacade.from_settings()
    facade = CF.from_settings(rag=rag, auditor=AuditFacade.from_settings(rag=rag) if auditar else None)
    rep, audit = facade.report(_fecha(fecha_corte), _cats(categorias), auditar=auditar)
    if json_out:
        _dump({"reporte": asdict(rep), "auditoria": audit.model_dump(mode="json") if audit else None})
        return
    typer.echo(f"REPORTE DE CUMPLIMIENTO al {rep.fecha_corte}  [{rep.rotulo}]")
    for a in rep.advertencias:
        typer.echo(f"  ! {a}")
    for it in rep.items:
        o = it.obligacion
        typer.echo(f"\n{o.codigo} | {it.estado.upper()} | atraso max {it.dias_atraso} d | {o.accion_requerida}")
        typer.echo(f"   cita obligacion: {o.norma_codigo} art. {o.articulo_numero} (version {o.version_id})")
        for c in it.casos:
            typer.echo(f"   - {c.sujeto_id or '-'}: {c.estado} limite={c.fecha_limite} atraso={c.dias_atraso} | {c.detalle}")
        for ir in it.infracciones:
            i, x = ir.infraccion, ir.exposicion
            marca = " [SINTETICA]" if ir.sintetica else ""
            rango = (f"{x.multa_min_uit}-{x.multa_max_uit} UIT" + (f" (S/ {x.min_soles}-{x.max_soles})" if x.max_soles else "")
                     if x.monto_determinado else "monto no determinado")
            typer.echo(f"   infraccion{marca}: {i.codigo_numeral} {i.gravedad or ''} v{i.version_id} -> {rango} | {x.nota}")
    p = rep.propuestas_pendientes
    typer.echo(f"\nPropuestas aun sin validar (no incluidas en el calculo): {p}")
    if audit:
        typer.echo(f"\nAUDITORIA: {audit.decision} (score {audit.score}) - {audit.checks['decision_reason']}")


if __name__ == "__main__":
    app()
