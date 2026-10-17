"""Segmenta el texto de un anexo de infracciones por numeral ("2.1.", "3.10")."""
import re

_NUMERAL = re.compile(r"(?m)^[ \t]*(\d{1,2}(?:\.\d{1,3}){1,2})\.?[ \t]+(?=\S)")


def encabezado(texto: str) -> str:
    """Primera linea no vacia (p. ej. 'Artículo 2.- Infracciones graves ...')."""
    return next((ln.strip() for ln in texto.splitlines() if ln.strip()), "")


def segmentar(texto: str) -> list[tuple[str | None, str]]:
    """[(codigo_numeral, texto_del_numeral)]. Sin numerales: [(None, texto)]."""
    ms = list(_NUMERAL.finditer(texto))
    if not ms:
        return [(None, texto.strip())]
    out = []
    for i, m in enumerate(ms):
        fin = ms[i + 1].start() if i + 1 < len(ms) else len(texto)
        out.append((m.group(1), texto[m.start():fin].strip()))
    return out
