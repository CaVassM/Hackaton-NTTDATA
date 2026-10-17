"""Extraccion de cifras verificables: montos, plazos y fechas.

Claim y evidencia pasan por el MISMO extractor y se comparan en forma
canonica, asi "15 días" coincide con "quince (15) días calendario" y
"S/ 50,000" con "S/50 000".
"""
import re
import unicodedata

_MESES = {
    m: i
    for i, m in enumerate(
        "enero febrero marzo abril mayo junio julio agosto setiembre octubre noviembre diciembre".split(), 1
    )
}
_MESES["septiembre"] = 9

_MONTO = re.compile(r"(s/|us\$|\$)\s*(\d[\d.,\s]*\d|\d)")
# "(15) dias" o "15 dias"; "24 horas"; "6 meses"
_PLAZO = re.compile(r"(\d+)\)?\s*(horas?|dias?|meses|mes|anos?)\b")
_FECHA_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_FECHA_ES = re.compile(r"\b(\d{1,2})\s+de\s+(" + "|".join(_MESES) + r")\s+(?:de|del)\s+(\d{4})")

_UNIDAD = {"hora": "hora", "horas": "hora", "dia": "dia", "dias": "dia", "mes": "mes", "meses": "mes",
           "ano": "ano", "anos": "ano"}


def normalize(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in norm if not unicodedata.combining(ch))


def _monto(moneda: str, raw: str) -> str:
    raw = re.sub(r"\s", "", raw)
    # Si el ULTIMO separador va seguido de 2 digitos son centimos: "50,000.00".
    # Con 3 digitos es separador de miles: "50,000" / "50.000".
    raw = re.sub(r"[.,]\d{2}$", "", raw)
    digits = re.sub(r"[.,]", "", raw)
    return f"{'s/' if moneda == 's/' else 'usd'}{int(digits)}"


def extract_facts(text: str) -> set[str]:
    """Hechos canonicos: 'monto:s/50000', 'plazo:15 dia', 'fecha:2026-07-01'."""
    t = normalize(text)
    facts = {f"monto:{_monto(m.group(1), m.group(2))}" for m in _MONTO.finditer(t)}
    facts |= {f"plazo:{int(m.group(1))} {_UNIDAD[m.group(2)]}" for m in _PLAZO.finditer(t)}
    facts |= {f"fecha:{m.group(1)}-{m.group(2)}-{m.group(3)}" for m in _FECHA_ISO.finditer(t)}
    facts |= {
        f"fecha:{int(m.group(3)):04d}-{_MESES[m.group(2)]:02d}-{int(m.group(1)):02d}" for m in _FECHA_ES.finditer(t)
    }
    return facts
