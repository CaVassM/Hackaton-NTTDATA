"""Guardia de numeros: un texto generado no puede introducir cifras que no esten
en su fuente (claims / citas). Compara enteros en cifras y en palabras."""
import re
import unicodedata

_PALABRAS = {
    "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
    "nueve": 9, "diez": 10, "once": 11, "doce": 12, "quince": 15, "veinte": 20, "veinticuatro": 24,
    "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "noventa": 90, "cien": 100,
}


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def numeros(text: str) -> set[int]:
    t = _norm(text)
    # "50,000" / "50.000" / "50 000" -> 50000 ; "2026-09-15" -> 2026, 9, 15
    out = {int(re.sub(r"[.,\s]", "", m)) for m in re.findall(r"\d{1,3}(?:[.,\s]\d{3})+(?![\d])", t)}
    out |= {int(m) for m in re.findall(r"\d+", t)}
    out |= {v for w, v in _PALABRAS.items() if re.search(rf"\b{w}\b", t)}
    return out


def numeros_nuevos(generado: str, fuentes: list[str]) -> set[int]:
    permitidos = set().union(*(numeros(f) for f in fuentes)) if fuentes else set()
    return numeros(generado) - permitidos
