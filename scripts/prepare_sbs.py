"""Convierte los PDFs/textos oficiales de la SBS en .txt limpios que el parser
de rag ingiere sin cambios (rag NO se toca).

    python scripts/prepare_sbs.py            # data/raw/sbs -> data/raw/sbs_txt
    python -m modules.rag.cli ingest data/raw/sbs_txt

Por que hace falta (ver README, "Corpus normativo"):
  - Los PDFs dicen "Resolución S.B.S." y el parser de rag busca "SBS": sin
    cabecera tomaria como codigo la PRIMERA norma citada en el texto.
  - Pie de pagina ("Los Laureles N° 214...") y numeracion "14 / 55" partirian
    las citas literales que cruzan un salto de pagina.
  - Notas al pie ("5 Artículo modificado por...") y sus llamadas pegadas a la
    palabra ("Sospechosas13") ensucian titulos y citas.
  - La 2660 trae al final una lista que repite titulos de articulos (rompe la
    ingesta por "duplicado") y los anexos (se pegarian al ultimo articulo).

Solo se conserva el cuerpo articulado del reglamento. Cada fuente declara su
cabecera de forma EXPLICITA (codigo, fechas, estado): nada se adivina.
"""
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "raw" / "sbs"
DST = ROOT / "data" / "raw" / "sbs_txt"


@dataclass
class Fuente:
    patron: str  # glob dentro de data/raw/sbs
    salida: str
    cabecera: dict[str, str]
    inicio: str  # regex: primer caracter del cuerpo que se conserva
    fin: list[str] = field(default_factory=list)  # regex: el cuerpo termina en el primero que aparezca
    nota: str = ""


FUENTES = [
    Fuente(
        patron="*2660-2015*.pdf",
        salida="2660-2015.txt",
        cabecera={
            "CODIGO": "Resolución SBS N° 2660-2015",
            "TITULO": "Reglamento de Gestión de Riesgos de Lavado de Activos y del Financiamiento del "
                      "Terrorismo (texto concordado del PDF provisto: incluye la Res. SBS N° 4705-2017)",
            "TIPO": "resolucion",
            "FECHA_EMISION": "2015-05-14",
            "ESTADO": "vigente",
            # Conservadora: el PDF es un texto concordado con cambios de la
            # 4705-2017 (06/12/2017) y no trae el texto anterior. Antes de esa
            # fecha no afirmamos ningun texto.
            "VIGENCIA_DESDE": "2017-12-06",
        },
        inicio=r"(?m)^[ \t]*Artículo 1°\.-",
        fin=[r"(?m)^[ \t]*DISPOSICIONES COMPLEMENTARIAS", r"(?m)^[ \t]*Artículo Segundo"],
        nota="Se descartan disposiciones complementarias, articulos de la resolucion y anexos.",
    ),
    Fuente(
        patron="2755-2018*.pdf",
        salida="2755-2018.txt",
        cabecera={
            "CODIGO": "Resolución SBS N° 2755-2018",
            "TITULO": "Reglamento de Infracciones y Sanciones de la SBS (cuerpo del reglamento; "
                      "los anexos de tipificacion NO estan en el PDF provisto)",
            "TIPO": "resolucion",
            "FECHA_EMISION": "2018-07-16",
            "ESTADO": "vigente",
            "VIGENCIA_DESDE": "",  # se completa leyendo el Articulo Tercero (ver _vigencia_2755)
        },
        inicio=r"(?m)^[ \t]*Artículo 1\.",
        fin=[r"(?m)^[ \t]*DISPOSICIONES COMPLEMENTARIAS", r"(?m)^[ \t]*Artículo Segundo"],
    ),
]

_PIE = re.compile(r"(?im)^.*Los\s+Laureles\s+N\S*\s*214.*$")
_PAGINA = re.compile(r"(?m)^[ \t]*\d{1,3}\s*/\s*\d{1,3}[ \t]*$")
_NOTA = re.compile(
    r"(?im)^[ \t]*\d{1,2}[ \t]+(?:P[áa]rrafo|Literal|Art[íi]culo|T[íi]tulo|Rubro|Numeral|Inciso|"
    r"Cap[íi]tulo|Subcap[íi]tulo|Definici[óo]n|Anexo|Texto|Acr[óo]nimo|Secci[óo]n)s?\b[^\n]*"
    r"(?:modificad|incorporad|sustituid|derogad|eliminad)[^\n]*$"
)
# Llamada de nota pegada a una palabra en minuscula: "Sospechosas13 " / "manera3:".
_LLAMADA = re.compile(r"(?<=[a-záéíóúñ)])\d{1,2}(?=[ \t]*$|[ \t]*[:;,.]|[ \t]+[A-ZÁÉÍÓÚ])", re.MULTILINE)
_MESES = {m: i for i, m in enumerate(
    "enero febrero marzo abril mayo junio julio agosto setiembre octubre noviembre diciembre".split(), 1)}
_MESES["septiembre"] = 9


def leer(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        import fitz  # pymupdf

        with fitz.open(path) as doc:
            return "\n".join(page.get_text() for page in doc)
    return path.read_text(encoding="utf-8")


def limpiar(texto: str) -> str:
    texto = _PIE.sub("", texto)
    texto = _PAGINA.sub("", texto)
    texto = _NOTA.sub("", texto)
    texto = _LLAMADA.sub("", texto)
    texto = re.sub(r"[ \t]+\n", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip() + "\n"


def recortar(texto: str, f: Fuente) -> str:
    m = re.search(f.inicio, texto)
    if not m:
        raise SystemExit(f"{f.salida}: no se encontro el inicio del cuerpo ({f.inicio})")
    fin = min((x.start() for p in f.fin if (x := re.search(p, texto[m.start():]))), default=None)
    return texto[m.start(): m.start() + fin] if fin else texto[m.start():]


def _vigencia_2755(texto: str) -> str:
    m = re.search(r"Artículo Tercero\.-[^.]*?vigencia[^.]*?(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", texto, re.S)
    if m and m.group(2).lower() in _MESES:
        return f"{int(m.group(3)):04d}-{_MESES[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    if re.search(r"Artículo Tercero\.-[^.]*?d[íi]a siguiente", texto, re.S):
        # "entra en vigencia al dia siguiente de su publicacion": la fecha de
        # publicacion NO consta en el PDF. Aproximacion: emision (16/07/2018) + 1.
        print("[aviso] 2755-2018: vigencia aproximada 2018-07-17 (publicacion no consta en el PDF)")
        return "2018-07-17"
    raise SystemExit("2755-2018: no se pudo leer la vigencia del Articulo Tercero; fijala a mano")


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    hechos = 0
    for f in FUENTES:
        encontrados = sorted(SRC.glob(f.patron))
        if not encontrados:
            print(f"[omitido] {f.patron}: no esta en {SRC}")
            continue
        crudo = leer(encontrados[0])
        cab = dict(f.cabecera)
        if f.salida.startswith("2755") and not cab["VIGENCIA_DESDE"]:
            cab["VIGENCIA_DESDE"] = _vigencia_2755(crudo)
        cuerpo = limpiar(recortar(crudo, f))
        n_art = len(re.findall(r"(?m)^[ \t]*Artículo \d+", cuerpo))
        cabecera = "\n".join(f"{k}: {v}" for k, v in cab.items())
        aviso = ("CORPUS DE TRABAJO: texto limpiado automaticamente desde " + encontrados[0].name +
                 ". No garantiza ser la version consolidada oficial vigente; validar contra el portal de la SBS.")
        (DST / f.salida).write_text(f"{cabecera}\n---\n{aviso}\n\n{cuerpo}", encoding="utf-8")
        print(f"[ok] {f.salida}: {n_art} articulos, {len(cuerpo):,} caracteres. {f.nota}")
        hechos += 1
    return 0 if hechos else 1


if __name__ == "__main__":
    sys.exit(main())
