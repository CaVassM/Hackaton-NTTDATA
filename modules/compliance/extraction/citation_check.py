"""Verificacion determinista OBLIGATORIA de lo que propone el LLM.

  - cita_literal: la cita existe tal cual en el texto de la version
    (solo se normalizan espacios / saltos de linea y comillas externas).
  - numero_en_cita: un numero que el LLM afirma (plazo, multa) aparece en la
    cita, en cifras ("24", "(10)") o en palabras ("veinticuatro").
Si algo falla, la propuesta se descarta (obligaciones) o el dato se anula
(montos de infracciones). Nunca se "corrige" lo que dijo el LLM.
"""
import re

MIN_CITA = 20  # una cita de 2 palabras ("deben informar") no prueba nada

_PALABRAS = {
    1: "uno|una|un", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco", 6: "seis", 7: "siete", 8: "ocho",
    9: "nueve", 10: "diez", 11: "once", 12: "doce", 13: "trece", 14: "catorce", 15: "quince",
    16: "dieciseis|dieciséis", 18: "dieciocho", 20: "veinte", 24: "veinticuatro", 25: "veinticinco",
    30: "treinta", 45: "cuarenta y cinco", 48: "cuarenta y ocho", 60: "sesenta", 72: "setenta y dos",
    90: "noventa", 100: "cien", 120: "ciento veinte", 180: "ciento ochenta", 365: "trescientos sesenta y cinco",
}
_COMILLAS = "\"'“”‘’«»"


def norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def limpiar_cita(cita: str) -> str:
    return norm_ws(cita).strip(_COMILLAS).strip()


def cita_literal(cita: str, texto: str) -> bool:
    c = limpiar_cita(cita)
    return len(c) >= MIN_CITA and c in norm_ws(texto)


def numero_en_cita(valor: float | int, cita: str) -> bool:
    if float(valor).is_integer():
        n = int(valor)
        cifras = [str(n), f"{n:,}".replace(",", "."), f"{n:,}".replace(",", " ")]
    else:
        n = None
        cifras = [str(valor), str(valor).replace(".", ",")]
    if any(re.search(rf"(?<![\d.,]){re.escape(c)}(?![\d])", cita) for c in cifras):
        return True
    palabras = _PALABRAS.get(n) if n is not None else None
    return bool(palabras and re.search(rf"(?i)\b({palabras})\b", cita))
