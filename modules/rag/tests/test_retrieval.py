import json
from datetime import date

import pytest

from modules.rag import RagError
from modules.rag.services.retrieval_service import rrf
from modules.rag.tests.conftest import BASE, CAMBIO, HOY, PROY

Q = "plazo máximo para responder un reclamo en días calendario"


def _ids(res):
    return [f.cita.version_id for f in res.fragmentos]


def test_rrf_premia_aparecer_en_ambas_listas():
    s = rrf([[1, 2, 3], [3, 1]], k=60)
    assert max(s, key=s.get) == 1 and s[3] > s[2]


def test_search_con_fecha_anterior_devuelve_texto_viejo_y_marca_modificada(rag, art2):
    old, new = art2
    res = rag.search(Q, fecha=date(2026, 6, 1), top_k=5)
    assert res.fecha == date(2026, 6, 1) and not res.fecha_por_defecto
    assert old.version_id in _ids(res) and new.version_id not in _ids(res)
    cita = next(f.cita for f in res.fragmentos if f.cita.version_id == old.version_id)
    assert (cita.norma, cita.articulo) == (BASE, "2")
    assert cita.fue_modificada is True
    assert cita.version_vigente_actual_id == new.version_id
    assert cita.vigente_hasta == CAMBIO


def test_search_despues_del_cambio_devuelve_texto_nuevo(rag, art2):
    old, new = art2
    res = rag.search(Q, fecha=CAMBIO, top_k=5)
    assert new.version_id in _ids(res) and old.version_id not in _ids(res)
    cita = next(f.cita for f in res.fragmentos if f.cita.version_id == new.version_id)
    assert cita.fue_modificada is False and cita.version_vigente_actual_id == new.version_id
    assert cita.reemplaza_a == old.version_id


def test_search_sin_fecha_usa_hoy(rag):
    res = rag.search(Q)
    assert res.fecha == HOY and res.fecha_por_defecto


def test_todas_las_citas_estan_vigentes_en_la_fecha(rag):
    for f in [date(2025, 5, 1), date(2026, 6, 30), CAMBIO, HOY]:
        for frag in rag.search(Q, fecha=f, top_k=10).fragmentos:
            assert rag.vigente_en(frag.cita.version_id, f)


def test_antes_de_toda_vigencia_no_hay_resultados(rag):
    assert rag.search(Q, fecha=date(2024, 1, 1)).fragmentos == []


def test_proyecto_no_sale_como_vigente(rag):
    res = rag.search("plazo de diez (10) días calendario", top_k=10)
    assert all(not f.cita.es_proyecto for f in res.fragmentos)
    assert all(f.cita.norma != PROY for f in res.fragmentos)
    assert not any("diez (10)" in f.texto for f in res.fragmentos)


def test_proyecto_aparece_solo_si_se_pide_y_marcado(rag):
    res = rag.search("plazo de diez (10) días calendario", top_k=10, incluir_proyectos=True)
    proyectos = [f.cita for f in res.fragmentos if f.cita.norma == PROY]
    assert proyectos and all(c.es_proyecto for c in proyectos)


def test_log_jsonl_por_busqueda(rag):
    rag.search(Q, fecha=date(2026, 6, 1), top_k=2)
    lines = rag.settings.search_log_path.read_text(encoding="utf-8").splitlines()
    ev = json.loads(lines[-1])
    assert ev["evento"] == "rag.search" and ev["query"] == Q and ev["fecha"] == "2026-06-01"
    assert ev["resultado_ids"] and "total_ms" in ev["tiempos"] and "embed_ms" in ev["tiempos"]
    assert ev["descartados_por_vigencia"] >= 1  # la version nueva (15 dias) se filtro


def test_validacion_de_entrada(rag):
    with pytest.raises(RagError):
        rag.search("   ")
    with pytest.raises(RagError):
        rag.search(Q, top_k=0)
    with pytest.raises(RagError):
        rag.search(Q, fecha="2026-13-01")


def test_answer_stub_avisa_modificacion(rag):
    r = rag.answer(Q, fecha=date(2026, 6, 1), top_k=1)
    assert r.generada_por == "stub" and r.citas
    assert "MODIFICADO POSTERIORMENTE" in r.texto


def test_reranker_inyectado_reordena(tmp_path):
    from modules.rag.services.reranker import Reranker
    from modules.rag.tests.conftest import SINTETICOS, make_facade

    class Invertido(Reranker):
        def rerank(self, query, candidatos, top_n):
            return [(vid, float(i)) for i, (vid, _) in enumerate(reversed(candidatos))][:top_n]

    rag = make_facade(tmp_path)
    rag.ingest(SINTETICOS)
    base = _ids(rag.search(Q, top_k=3))
    rag._retrieval.reranker = Invertido()
    assert _ids(rag.search(Q, top_k=3)) != base


# --- filtro por norma (lo usa modules/compliance) ---
def test_search_filtra_por_norma(rag, art2):
    from modules.rag.tests.conftest import MOD

    res = rag.search(Q, top_k=10, norma="Res. SBS N.° 567-2026")  # cualquier forma del codigo
    assert res.fragmentos and all(f.cita.norma == MOD for f in res.fragmentos)
    # El art. 2 modificado pertenece a la norma BASE aunque lo creara la modificatoria.
    res_base = rag.search(Q, top_k=10, norma=BASE)
    assert all(f.cita.norma == BASE for f in res_base.fragmentos)
    assert art2[1].version_id in _ids(res_base)


def test_search_norma_inexistente_es_error(rag):
    from modules.rag import NormaNoEncontrada

    with pytest.raises(NormaNoEncontrada):
        rag.search(Q, norma="Resolución SBS N° 1-1990")
