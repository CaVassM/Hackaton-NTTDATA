import pytest
from fastapi.testclient import TestClient

from modules.rag.api.app import create_app
from modules.rag.tests.conftest import BASE, CAMBIO, N_ARCHIVOS


@pytest.fixture
def client(rag):
    with TestClient(create_app(rag)) as c:
        yield c


def test_search(client, art2):
    old, new = art2
    r = client.post("/rag/search", json={"query": "plazo para responder reclamos", "fecha": "2026-06-01", "top_k": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["fecha"] == "2026-06-01" and body["fecha_por_defecto"] is False
    cita = next(f["cita"] for f in body["fragmentos"] if f["cita"]["version_id"] == old.version_id)
    assert cita["fue_modificada"] is True and cita["version_vigente_actual_id"] == new.version_id


def test_search_valida_entrada(client):
    assert client.post("/rag/search", json={"query": "x"}).status_code == 422
    assert client.post("/rag/search", json={"query": "plazo", "top_k": 500}).status_code == 422


def test_vigente(client):
    r = client.get("/rag/vigente", params={"norma": BASE, "articulo": "2", "fecha": CAMBIO.isoformat()})
    assert r.status_code == 200 and "quince" in r.json()["version"]["texto"]
    # Existe pero no regia: 200 con version null, no 404.
    r = client.get("/rag/vigente", params={"norma": BASE, "articulo": "2", "fecha": "2020-01-01"})
    assert r.status_code == 200 and r.json()["version"] is None
    r = client.get("/rag/vigente", params={"norma": BASE, "articulo": "2"})
    assert r.json()["fecha_por_defecto"] is True


def test_historial_y_404(client):
    r = client.get("/rag/historial", params={"norma": BASE, "articulo": "2"})
    assert r.status_code == 200 and len(r.json()) == 2
    assert client.get("/rag/historial", params={"norma": "Resolución SBS N° 1-1990", "articulo": "1"}).status_code == 404
    assert client.get("/rag/version/9999").status_code == 404


def test_endpoints_de_version(client, art2):
    old, new = art2
    assert client.get(f"/rag/version/{new.version_id}").json()["reemplaza_a"] == old.version_id
    r = client.get(f"/rag/version/{old.version_id}/vigente", params={"fecha": CAMBIO.isoformat()})
    assert r.json()["vigente"] is False
    assert [v["version_id"] for v in client.get(f"/rag/version/{old.version_id}/posteriores").json()] == [new.version_id]


def test_ingest_rechaza_rutas_fuera_de_raw(client):
    assert client.post("/rag/ingest", json={"ruta": "../../"}).status_code == 400
    r = client.post("/rag/ingest", json={"ruta": "sinteticos"})
    assert r.status_code == 200 and len(r.json()["normas_omitidas"]) == N_ARCHIVOS


def test_search_con_filtro_de_norma(client):
    r = client.post("/rag/search", json={"query": "plazo de reclamos", "norma": BASE, "top_k": 5})
    assert r.status_code == 200 and all(f["cita"]["norma"] == BASE for f in r.json()["fragmentos"])
    assert client.post("/rag/search", json={"query": "plazo", "norma": "Res SBS 1-1990"}).status_code == 404
