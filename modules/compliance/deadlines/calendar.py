"""Aritmetica de plazos. Determinista, sin LLM.

Convenciones (documentadas en el README):
  - dias calendario: fecha_evento + N.
  - dias habiles: se cuentan desde el dia habil siguiente al evento; no
    cuentan sabados, domingos ni feriados (lista configurable).
  - horas: la evidencia trae FECHAS, no horas; N horas = ceil(N/24) dias
    (24 h -> dia siguiente). Granularidad de dia: un cumplimiento el mismo
    dia limite cuenta como en plazo aunque haya sido horas despues.
  - meses / anios: misma fecha del mes destino (31/01 + 1 mes -> 28/02).
"""
import calendar as _cal
import csv
import math
from datetime import date, timedelta
from pathlib import Path

from shared.logging import get_logger

log = get_logger(__name__)


def es_habil(d: date, feriados: set[date]) -> bool:
    return d.weekday() < 5 and d not in feriados


def sumar_habiles(inicio: date, n: int, feriados: set[date]) -> date:
    d, contados = inicio, 0
    while contados < n:
        d += timedelta(days=1)
        if es_habil(d, feriados):
            contados += 1
    return d


def sumar_meses(inicio: date, meses: int) -> date:
    total = inicio.month - 1 + meses
    y, m = inicio.year + total // 12, total % 12 + 1
    return date(y, m, min(inicio.day, _cal.monthrange(y, m)[1]))


def sumar_plazo(inicio: date, valor: int, unidad: str, tipo: str | None, feriados: set[date]) -> date:
    if valor < 0:
        raise ValueError("plazo negativo")
    if unidad == "horas":
        dias = math.ceil(valor / 24)
        return sumar_habiles(inicio, dias, feriados) if tipo == "habil" else inicio + timedelta(days=dias)
    if unidad == "dias":
        return sumar_habiles(inicio, valor, feriados) if tipo == "habil" else inicio + timedelta(days=valor)
    if unidad == "meses":
        return sumar_meses(inicio, valor)
    if unidad == "anios":
        return sumar_meses(inicio, 12 * valor)
    raise ValueError(f"unidad de plazo desconocida: {unidad!r}")


def load_feriados(path: Path) -> set[date]:
    """CSV con columna `fecha` (AAAA-MM-DD). Si no existe, sin feriados (y aviso)."""
    path = Path(path)
    if not path.exists():
        log.warning("Sin archivo de feriados (%s): los dias habiles solo excluyen fines de semana", path)
        return set()
    with path.open(encoding="utf-8") as f:
        return {date.fromisoformat(r["fecha"].strip()) for r in csv.DictReader(f) if r.get("fecha", "").strip()}
