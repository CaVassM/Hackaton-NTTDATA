from datetime import date

import pytest

from modules.rag.domain import EstadoNorma, IngestaError
from modules.rag.services.parsers import normalizar_codigo, parse_file, parse_text
from modules.rag.tests.conftest import BASE, SINTETICOS


@pytest.mark.parametrize(
    "raw",
    ["Resolución SBS N° 1234-2025", "Res. SBS N.° 01234-2025", "RESOLUCION SBS Nº 1234 - 2025", "Resolución SBS N 1234-2025"],
)
def test_normalizar_codigo_variantes(raw):
    assert normalizar_codigo(raw) == BASE


def test_codigo_de_proyecto_no_se_confunde_con_la_norma_real():
    assert normalizar_codigo("Proyecto de Resolución SBS PR-045-2026").startswith("Proyecto")


def test_articulo_citado_no_se_parte_como_articulo_propio():
    mod = parse_file(SINTETICOS / "02_res_sbs_567_2026_modificatoria.txt")
    # Tiene "Artículo 1" y "Artículo 2" propios; el "Artículo 2.-" citado va dentro del 1.
    assert [a.numero for a in mod.articulos] == ["1", "2"]
    assert "quince (15)" in mod.articulos[0].texto
    assert "Vigencia" in mod.articulos[1].texto


def test_detecta_modificatoria():
    mod = parse_file(SINTETICOS / "02_res_sbs_567_2026_modificatoria.txt")
    assert len(mod.modificaciones) == 1
    m = mod.modificaciones[0]
    assert (m.articulo_numero, m.norma_objetivo, m.origen_articulo) == ("2", BASE, "1")
    assert m.nuevo_texto.startswith("Artículo 2.- Plazo de atención")
    assert "quince (15) días" in m.nuevo_texto and "“" not in m.nuevo_texto


def test_sin_cabecera_deduce_metadatos():
    texto = (
        "RESOLUCIÓN SBS N° 99-2026\nLima, 3 de febrero de 2026\n"
        "Aprueban Reglamento de Pruebas\n"
        "Artículo 1.- Uno.\nTexto uno.\n"
        "Artículo 2.- Vigencia\nLa presente entra en vigencia a partir del 1 de marzo de 2026.\n"
    )
    n = parse_text(texto, "x.txt")
    assert n.codigo == "Resolución SBS N° 99-2026"
    assert n.fecha_emision == date(2026, 2, 3)
    assert n.vigencia_desde == date(2026, 3, 1)
    assert n.estado == EstadoNorma.VIGENTE
    assert [a.numero for a in n.articulos] == ["1", "2"]


def test_vigencia_dia_siguiente():
    texto = "Resolución SBS N° 5-2026\nLima, 9 de enero de 2026\nArtículo 1.- Rige desde la vigencia del día siguiente de su publicación."
    assert parse_text(texto, "x").vigencia_desde == date(2026, 1, 10)


def test_sin_articulos_es_error():
    with pytest.raises(IngestaError):
        parse_text("CODIGO: Resolución SBS N° 1-2026\nFECHA_EMISION: 2026-01-01\n---\nsin articulos", "x")
