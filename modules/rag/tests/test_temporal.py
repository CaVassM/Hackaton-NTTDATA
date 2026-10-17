from datetime import date, timedelta

import pytest

from modules.rag import ArticuloNoEncontrado, EstadoNorma, NormaNoEncontrada, RagError, VersionNoEncontrada
from modules.rag.tests.conftest import BASE, CAMBIO, HOY, MOD, PROY


@pytest.mark.parametrize(
    ("fecha", "esperado"),
    [
        (date(2025, 3, 31), None),  # antes de que la norma base entre en vigor
        (date(2025, 4, 1), "treinta (30)"),  # justo en la vigencia de la base
        (CAMBIO - timedelta(days=1), "treinta (30)"),  # un dia ANTES del cambio
        (CAMBIO, "quince (15)"),  # JUSTO en el cambio: "hasta" es exclusivo
        (CAMBIO + timedelta(days=1), "quince (15)"),  # despues del cambio
    ],
)
def test_vigencia_antes_en_y_despues_del_cambio(rag, fecha, esperado):
    v = rag.texto_vigente(BASE, "2", fecha)
    if esperado is None:
        assert v is None
    else:
        assert esperado in v.texto


def test_sin_fecha_usa_hoy(rag):
    assert rag.hoy() == HOY
    assert "quince (15)" in rag.texto_vigente(BASE, "2").texto


def test_acepta_codigo_en_otra_forma_y_fecha_iso(rag):
    assert "treinta" in rag.texto_vigente("Res. SBS N.° 01234-2025", "2", "2026-01-01").texto


def test_get_version_metadatos(rag, art2):
    old, new = art2
    v = rag.get_version(new.version_id)
    assert (v.norma_codigo, v.articulo_numero, v.vigente_desde, v.vigente_hasta) == (BASE, "2", CAMBIO, None)
    assert v.creada_por_codigo == MOD and v.estado_norma_creadora == EstadoNorma.VIGENTE
    assert v.reemplaza_a == old.version_id


def test_vigente_en_fronteras(rag, art2):
    old, new = art2
    assert rag.vigente_en(old.version_id, CAMBIO - timedelta(days=1))
    assert not rag.vigente_en(old.version_id, CAMBIO)
    assert rag.vigente_en(new.version_id, CAMBIO)
    assert not rag.vigente_en(new.version_id, CAMBIO - timedelta(days=1))


def test_vigente_en_proyecto_siempre_false(rag):
    (v,) = rag.historial(PROY, "1")
    assert v.estado_norma_creadora == EstadoNorma.PROYECTO
    assert not rag.vigente_en(v.version_id, HOY)


def test_versiones_posteriores(rag, art2):
    old, new = art2
    assert [v.version_id for v in rag.versiones_posteriores(old.version_id)] == [new.version_id]
    assert rag.versiones_posteriores(new.version_id) == []


def test_cambios_por_norma(rag, art2):
    _, new = art2
    mod = rag.cambios_por_norma(MOD)
    assert [v.version_id for v in mod.introducidos] == [new.version_id] and mod.recibidos == []
    base = rag.cambios_por_norma(BASE)
    assert [v.version_id for v in base.recibidos] == [new.version_id] and base.introducidos == []


def test_errores_explicitos(rag):
    with pytest.raises(NormaNoEncontrada):
        rag.texto_vigente("Resolución SBS N° 1-1999", "1")
    with pytest.raises(ArticuloNoEncontrado):
        rag.historial(BASE, "99")
    with pytest.raises(VersionNoEncontrada):
        rag.get_version(9999)
    with pytest.raises(RagError):
        rag.vigente_en(1, "31/12/2026")


# --- listar_versiones (lo usa modules/compliance) ---
def test_listar_versiones_vigentes_por_fecha(rag, art2):
    old, new = art2
    antes = {v.articulo_numero: v.version_id for v in rag.listar_versiones(BASE, CAMBIO - timedelta(days=1))}
    despues = {v.articulo_numero: v.version_id for v in rag.listar_versiones("Res. SBS 1234-2025", CAMBIO)}
    assert set(antes) == set(despues) == {"1", "2", "3"}  # una version por articulo
    assert antes["2"] == old.version_id and despues["2"] == new.version_id
    assert rag.listar_versiones(BASE, date(2025, 3, 1)) == []  # antes de la vigencia


def test_listar_versiones_excluye_proyectos_y_valida_norma(rag):
    assert rag.listar_versiones(PROY) == []
    with pytest.raises(NormaNoEncontrada):
        rag.listar_versiones("Resolución SBS N° 1-1990")
