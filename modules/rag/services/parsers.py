"""Parseo de normas (.txt / .pdf) a estructuras intermedias.

Formato de entrada:
  1. Cabecera opcional `CLAVE: valor` terminada en una linea `---`
     (CODIGO, TITULO, TIPO, FECHA_EMISION, ESTADO, VIGENCIA_DESDE).
  2. Cuerpo con articulos "Artículo N.- ...".
Si falta la cabecera (PDFs reales) se deducen los metadatos con heuristicas.

Detalle clave: las modificatorias citan el texto nuevo ENTRE COMILLAS, y ese
texto empieza con "Artículo 2.- ...". Antes de partir por articulos se
enmascaran los bloques citados; si no, el articulo citado se confundiria con
un articulo propio de la modificatoria.
"""
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from modules.rag.domain import EstadoNorma, IngestaError

_MESES = {
    m: i
    for i, m in enumerate(
        "enero febrero marzo abril mayo junio julio agosto setiembre octubre noviembre diciembre".split(), 1
    )
}
_MESES["septiembre"] = 9

_FECHA_ES = re.compile(
    r"(\d{1,2})\s+de\s+(" + "|".join(_MESES) + r")\s+(?:de|del)\s+(\d{4})", re.IGNORECASE
)
_CODIGO_SBS = re.compile(
    r"(?:Resoluci[oó]n|Res\.)\s+(?:de\s+)?SBS\s*N?\s*[°º.]*\s*(\d{1,6})\s*-\s*(\d{4})", re.IGNORECASE
)
_HEADER_LINE = re.compile(r"^([A-Z_]+)\s*:\s*(.*)$")
_QUOTED = re.compile(r"“[^”]*”|\"[^\"]*\"", re.DOTALL)
_PLACEHOLDER = re.compile(r"\x00(\d+)\x00")
_ARTICULO = re.compile(
    r"^[ \t]*Art[íi]culo\s+(\d+(?:\s*-\s*[A-Z])?|[ÚU]nico)\s*[°º]?\s*(?:\.\s*-|\.|-|–|—|:)",
    re.MULTILINE,
)
# "Modificar el artículo N ... Resolución SBS N° X". El tramo intermedio no puede
# cruzar un bloque citado (\x00): asi no se engancha con la cita de otra cosa.
_MODIFICA = re.compile(
    r"Modif(?:icar|[íi]quese)\s+el\s+art[íi]culo\s+(\d+(?:-[A-Z])?)\s*[°º]?"
    r"[^\x00]*?(Resoluci[oó]n\s+SBS\s+N\s*[°º.]*\s*\d{1,6}\s*-\s*\d{4})",
    re.IGNORECASE | re.DOTALL,
)
_VIGENCIA_FECHA = re.compile(
    r"vigencia\s+(?:a\s+partir\s+del?|desde\s+el)\s+(?:d[íi]a\s+)?(.{0,40})", re.IGNORECASE
)
_VIGENCIA_SIGUIENTE = re.compile(r"vigencia\s+(?:a\s+partir\s+)?del?\s+d[íi]a\s+siguiente", re.IGNORECASE)


@dataclass(frozen=True)
class ArticuloParseado:
    numero: str
    texto: str


@dataclass(frozen=True)
class Modificacion:
    articulo_numero: str  # articulo de la norma objetivo
    norma_objetivo: str  # codigo normalizado de la norma modificada
    nuevo_texto: str
    origen_articulo: str  # articulo de la modificatoria que la ordena


@dataclass
class NormaParseada:
    codigo: str
    titulo: str
    fecha_emision: date
    tipo: str
    estado: EstadoNorma
    vigencia_desde: date
    fuente: str
    articulos: list[ArticuloParseado] = field(default_factory=list)
    modificaciones: list[Modificacion] = field(default_factory=list)


# ----------------------------------------------------------------- helpers
def normalizar_codigo(raw: str) -> str:
    """Forma canonica para que "Res. SBS N.° 01234-2025" y "Resolución SBS N°
    1234-2025" sean la misma norma. Un proyecto conserva su codigo propio."""
    raw = " ".join(raw.split())
    if raw.lower().startswith("proyecto"):
        return raw
    m = _CODIGO_SBS.search(raw)
    if m:
        return f"Resolución SBS N° {int(m.group(1))}-{m.group(2)}"
    return raw


def parse_fecha_es(text: str) -> date | None:
    m = _FECHA_ES.search(text)
    if not m:
        return None
    return date(int(m.group(3)), _MESES[m.group(2).lower()], int(m.group(1)))


def _parse_iso(value: str, campo: str, fuente: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise IngestaError(f"{fuente}: {campo} invalida ({value!r}), se espera AAAA-MM-DD") from exc


def _normaliza_numero(num: str) -> str:
    num = re.sub(r"\s+", "", num)
    return "Único" if num.lower() in ("único", "unico") else num.upper()


def _split_header(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    first = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    if first is None or not _HEADER_LINE.match(lines[first].strip()):
        return {}, text
    header: dict[str, str] = {}
    for i in range(first, len(lines)):
        ln = lines[i].strip()
        if ln == "---":
            return header, "\n".join(lines[i + 1 :])
        m = _HEADER_LINE.match(ln)
        if m:
            header[m.group(1)] = m.group(2).strip()
    return {}, text  # habia "CLAVE:" pero sin separador: no era cabecera


def _mask_quotes(body: str) -> tuple[str, list[str]]:
    quotes: list[str] = []

    def repl(m: re.Match) -> str:
        quotes.append(m.group(0))
        return f"\x00{len(quotes) - 1}\x00"

    return _QUOTED.sub(repl, body), quotes


def _unmask(text: str, quotes: list[str]) -> str:
    return _PLACEHOLDER.sub(lambda m: quotes[int(m.group(1))], text)


def _clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def split_articulos(body: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Devuelve [(numero, texto_enmascarado)] y la lista de citas enmascaradas."""
    masked, quotes = _mask_quotes(body)
    matches = list(_ARTICULO.finditer(masked))
    out = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(masked)
        out.append((_normaliza_numero(m.group(1)), masked[m.start() : end]))
    return out, quotes


def detectar_modificaciones(numero: str, masked_text: str, quotes: list[str]) -> list[Modificacion]:
    mods = []
    for m in _MODIFICA.finditer(masked_text):
        cita = _PLACEHOLDER.search(masked_text, m.end())
        if not cita:
            continue  # "modificar" sin texto nuevo citado: no hay version que crear
        nuevo = quotes[int(cita.group(1))].strip("“”\"").strip()
        mods.append(
            Modificacion(
                articulo_numero=_normaliza_numero(m.group(1)),
                norma_objetivo=normalizar_codigo(m.group(2)),
                nuevo_texto=_clean(nuevo),
                origen_articulo=numero,
            )
        )
    return mods


# ------------------------------------------------------------ heuristicas
def _deducir_estado(body: str) -> EstadoNorma:
    head = body[:800].lower()
    if "proyecto" in head or "prepublica" in head or "pre publica" in head:
        return EstadoNorma.PROYECTO
    return EstadoNorma.VIGENTE


def _deducir_vigencia(body: str, emision: date) -> date:
    if _VIGENCIA_SIGUIENTE.search(body):
        return emision + timedelta(days=1)
    m = _VIGENCIA_FECHA.search(body)
    if m and (f := parse_fecha_es(m.group(1))):
        return f
    return emision


def _deducir_titulo(body: str, codigo: str) -> str:
    for ln in body.splitlines():
        ln = ln.strip()
        if ln and ln != codigo and ("reglamento" in ln.lower() or "aprueba" in ln.lower()):
            return ln[:300]
    return codigo


# ---------------------------------------------------------------- publico
def parse_text(text: str, fuente: str) -> NormaParseada:
    header, body = _split_header(text)

    codigo_raw = header.get("CODIGO") or (m.group(0) if (m := _CODIGO_SBS.search(body)) else "")
    if not codigo_raw:
        raise IngestaError(f"{fuente}: no se encontro el codigo de la norma (CODIGO: o 'Resolución SBS N° X')")
    codigo = normalizar_codigo(codigo_raw)

    if "FECHA_EMISION" in header:
        emision = _parse_iso(header["FECHA_EMISION"], "FECHA_EMISION", fuente)
    else:
        lima = re.search(r"Lima,\s*(.{0,40})", body)
        emision = (lima and parse_fecha_es(lima.group(1))) or parse_fecha_es(body)
        if emision is None:
            raise IngestaError(f"{fuente}: no se encontro la fecha de emision")

    estado = EstadoNorma(header["ESTADO"].lower()) if "ESTADO" in header else _deducir_estado(body)
    vigencia = (
        _parse_iso(header["VIGENCIA_DESDE"], "VIGENCIA_DESDE", fuente)
        if "VIGENCIA_DESDE" in header
        else _deducir_vigencia(body, emision)
    )

    norma = NormaParseada(
        codigo=codigo,
        titulo=header.get("TITULO") or _deducir_titulo(body, codigo),
        fecha_emision=emision,
        tipo=header.get("TIPO", "circular" if "circular" in codigo.lower() else "resolucion"),
        estado=estado,
        vigencia_desde=vigencia,
        fuente=fuente,
    )

    articulos, quotes = split_articulos(body)
    if not articulos:
        raise IngestaError(f"{fuente}: no se encontraron articulos ('Artículo N.- ...')")
    vistos: set[str] = set()
    for numero, masked in articulos:
        if numero in vistos:
            raise IngestaError(f"{fuente}: articulo {numero} duplicado")
        vistos.add(numero)
        norma.articulos.append(ArticuloParseado(numero, _clean(_unmask(masked, quotes))))
        norma.modificaciones.extend(detectar_modificaciones(numero, masked, quotes))
    return norma


def read_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return path.read_text(encoding="utf-8")
    if suffix == ".pdf":
        import fitz  # pymupdf; perezoso: solo hace falta si hay PDFs

        with fitz.open(path) as doc:
            return "\n".join(page.get_text() for page in doc)
    raise IngestaError(f"Formato no soportado: {path.name}")


def parse_file(path: Path) -> NormaParseada:
    return parse_text(read_file(path), fuente=path.name)
