import shutil
from datetime import date

from modules.rag.tests.conftest import BASE, CAMBIO, MOD, N_ARCHIVOS, N_VERSIONES, PROY, SINTETICOS, make_facade


def test_ingesta_cierra_version_y_enlaza_reemplaza_a(rag, art2):
    old, new = art2
    assert old.vigente_hasta == CAMBIO  # cerrada, "hasta" exclusivo
    assert new.vigente_desde == CAMBIO and new.vigente_hasta is None
    assert new.reemplaza_a == old.version_id
    assert new.creada_por_codigo == MOD and old.creada_por_codigo == BASE
    assert "treinta (30)" in old.texto and "quince (15)" in new.texto


def test_articulos_no_modificados_siguen_abiertos(rag):
    for numero in ("1", "3"):
        (v,) = rag.historial(BASE, numero)
        assert v.vigente_hasta is None


def test_reporte(empty_rag):
    r = empty_rag.ingest(SINTETICOS)
    assert r.archivos == N_ARCHIVOS and len(r.normas_nuevas) == N_ARCHIVOS
    assert r.versiones_cerradas == 1
    assert r.versiones_creadas == N_VERSIONES
    assert r.embebidas == N_VERSIONES
    assert any(PROY in a for a in r.advertencias)


def test_ingesta_idempotente(rag):
    antes = rag.health()["indices"]
    r = rag.ingest(SINTETICOS)
    assert len(r.normas_omitidas) == N_ARCHIVOS and r.versiones_creadas == 0 and r.embebidas == 0
    assert rag.health()["indices"] == antes


def test_proyecto_no_cierra_versiones(rag):
    assert len(rag.historial(BASE, "2")) == 2  # el proyecto proponia una 3ra (10 dias)
    assert not any("diez (10)" in v.texto for v in rag.historial(BASE, "2"))


def test_orden_de_archivos_no_importa(tmp_path):
    # La modificatoria se nombra para que se lea ANTES que la base.
    src = tmp_path / "raw"
    src.mkdir()
    shutil.copy(SINTETICOS / "02_res_sbs_567_2026_modificatoria.txt", src / "a_mod.txt")
    shutil.copy(SINTETICOS / "01_res_sbs_1234_2025_base.txt", src / "b_base.txt")
    rag = make_facade(tmp_path)
    r = rag.ingest(src)
    assert r.versiones_cerradas == 1 and not r.advertencias


def test_modificatoria_de_norma_inexistente_advierte(tmp_path):
    rag = make_facade(tmp_path)
    r = rag.ingest(SINTETICOS / "02_res_sbs_567_2026_modificatoria.txt")
    assert any("no esta ingestada" in a for a in r.advertencias)
    assert r.versiones_cerradas == 0


def test_metadatos_de_chroma_reflejan_el_cierre(rag, art2):
    old, new = art2
    col = rag._ingestion.vectors._col  # interno: solo para verificar el indice
    metas = dict(zip(*[col.get(ids=[str(old.version_id), str(new.version_id)])[k] for k in ("ids", "metadatas")]))
    assert metas[str(old.version_id)]["vigente_hasta"] == CAMBIO.isoformat()
    assert metas[str(new.version_id)]["vigente_hasta"] == ""
    assert metas[str(new.version_id)]["creada_por"] == MOD


def test_reindex_repara_indices(rag):
    # Simula un corte tras el commit SQL: se borra un vector y reindex lo repone.
    col = rag._ingestion.vectors._col
    col.delete(ids=["1"])
    assert rag.reindex() == 1
    assert rag.health()["indices"]["vectores"] == N_VERSIONES


def test_texto_vigente_respeta_fecha_de_proyecto(rag):
    # El intervalo del proyecto cubriria hoy, pero un proyecto no rige.
    assert rag.texto_vigente(PROY, "1", date(2026, 10, 1)) is None
