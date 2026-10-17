import csv
from datetime import date
from pathlib import Path

from modules.compliance.domain import EvidenciaInterna, EvidenciaInvalida
from modules.compliance.evidence.interfaces import EvidenceSource

COLUMNAS = ("obligacion_codigo", "sujeto_id", "fecha_evento", "fecha_cumplimiento", "fecha_corte")
OBLIGATORIAS = ("obligacion_codigo", "sujeto_id", "fecha_evento")


def _fecha(valor: str | None, col: str, fila: int, oblig: bool) -> date | None:
    valor = (valor or "").strip()
    if not valor:
        if oblig:
            raise EvidenciaInvalida(f"fila {fila}: '{col}' es obligatoria")
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError as exc:
        raise EvidenciaInvalida(f"fila {fila}: '{col}'={valor!r} no es AAAA-MM-DD") from exc


class CsvEvidenceSource(EvidenceSource):
    """Estricto: una fila mal formada invalida la carga (no se adivinan fechas)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._cache: list[EvidenciaInterna] | None = None

    def load(self) -> list[EvidenciaInterna]:
        if self._cache is not None:
            return self._cache
        if not self.path.exists():
            raise EvidenciaInvalida(f"No existe el CSV de evidencia: {self.path}")
        with self.path.open(encoding="utf-8-sig", newline="") as f:  # -sig: CSV guardado desde Excel
            reader = csv.DictReader(f)
            faltan = [c for c in OBLIGATORIAS if c not in (reader.fieldnames or [])]
            if faltan:
                raise EvidenciaInvalida(f"Faltan columnas {faltan}; se esperan {list(COLUMNAS)}")
            out = []
            for n, row in enumerate(reader, start=2):
                codigo = (row.get("obligacion_codigo") or "").strip().upper()
                sujeto = (row.get("sujeto_id") or "").strip()
                if not codigo or not sujeto:
                    raise EvidenciaInvalida(f"fila {n}: obligacion_codigo y sujeto_id son obligatorios")
                out.append(EvidenciaInterna(
                    obligacion_codigo=codigo,
                    sujeto_id=sujeto,
                    fecha_evento=_fecha(row.get("fecha_evento"), "fecha_evento", n, True),
                    fecha_cumplimiento=_fecha(row.get("fecha_cumplimiento"), "fecha_cumplimiento", n, False),
                    fecha_corte=_fecha(row.get("fecha_corte"), "fecha_corte", n, False),
                    fila=n,
                ))
        self._cache = out
        return out
