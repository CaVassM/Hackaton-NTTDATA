"""API unificada sobre el stack de prueba de cases (rag/compliance/audit reales, LLM falso)."""
import pytest
from fastapi.testclient import TestClient

from app.main import AppSettings, Container, create_app
from modules.cases.tests.conftest import caso, make_cases, stack  # noqa: F401 - fixture de sesion


@pytest.fixture
def client(stack, tmp_path):  # noqa: F811
    cases, _ = make_cases(stack, tmp_path, texto="Resumen sin cifras nuevas.")
    container = Container(stack["rag"], stack["audit"], stack["compliance"], cases, AppSettings())
    with TestClient(create_app(container), raise_server_exceptions=False) as c:
        c.container = container
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    h = r.json()
    assert h["policy_version"] == "aml-audit-v2" and h["audit_mode"] == "direct"
    assert h["bases"]["rag"]["versiones_sql"] > 0 and h["bases"]["audit"]["cadena_ok"] is True
    assert h["bases"]["compliance"]["obligaciones"]["validada"] >= 2
    assert "reachable" in h["ollama"] and h["status"] in ("ok", "degradado")


def test_cors_permite_origenes_del_frontend(client):
    r = client.options("/health", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "content-type",
    })
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "GET" in r.headers["access-control-allow-methods"]


def test_cors_permite_el_frontend_en_vercel(client):
    r = client.options("/cases", headers={
        "Origin": "https://hackaton-nttdata.vercel.app",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://hackaton-nttdata.vercel.app"


def test_schema_para_los_equipos(client):
    s = client.get("/cases/schema").json()
    assert {"operacion_calificada_sospechosa", "ingreso_empleado"} <= set(s["tipos_evento"])
    assert "tipo_evento" in s["case_input"]["properties"] and "fecha_evento" in s["case_input"]["required"]
    assert s["csv_columnas"][0] == "case_id"


def test_evaluate_ok_y_422(client):
    r = client.post("/cases/evaluate", json=caso())
    assert r.status_code == 200 and r.json()["audit_result"]["decision"] == "ESCALATE"
    assert client.get("/cases/ROS-2026-0115").json()["case"]["case_id"] == "ROS-2026-0115"
    assert client.get("/cases/NO-EXISTE").status_code == 404

    malo = client.post("/cases/evaluate", json=caso(tipo_evento="inventado"))
    assert malo.status_code == 422
    (err,) = malo.json()["detail"]
    assert err["loc"] == ["body", "tipo_evento"] and "ingreso_empleado" in err["valores_validos"]
    assert client.post("/cases/evaluate", json={"case_id": "x"}).status_code == 422
    assert client.post("/cases/evaluate", json=caso(fecha_cumplimiento="2020-01-01")).status_code == 422


def test_batch_csv_multipart_y_json(client):
    csv_text = ("case_id,user_id,rol,tipo_evento,fecha_evento,fecha_cumplimiento,fecha_referencia\n"
                "C1,u,analista,ingreso_empleado,2026-08-03,2026-08-28,2026-10-17\n"
                "C2,u,analista,ingreso_empleado,2026-08-17,,2026-10-17\n"
                "C3,u,analista,no_existe,2026-08-17,,\n")
    r = client.post("/cases/batch", files={"file": ("casos.csv", csv_text.encode(), "text/csv")})
    assert r.status_code == 200
    items = r.json()
    assert [i["ok"] for i in items] == [True, True, False]
    assert [i["result"]["plazos"][0]["estado"] for i in items[:2]] == ["cumplido", "atrasado"]
    r = client.post("/cases/batch", json=[caso(case_id="J1")])
    assert r.status_code == 200 and r.json()[0]["ok"]
    assert client.post("/cases/batch", content=b"no es json", headers={"content-type": "application/json"}).status_code == 422
    listado = client.get("/cases").json()
    assert {"C1", "C2", "J1"} <= {c["case_id"] for c in listado}


def test_audit_y_compliance_montados(client):
    assert client.get("/audit/verify-chain").json()["ok"] is True
    assert client.get("/compliance/proposals?estado=validada").status_code == 200
    assert client.post("/rag/search", json={"query": "plazo del reporte de operaciones sospechosas", "top_k": 2}).status_code == 200


def test_error_no_controlado_devuelve_cuerpo(client, monkeypatch):
    monkeypatch.setattr(client.container.cases, "evaluate", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    r = client.post("/cases/evaluate", json=caso())
    assert r.status_code == 500 and r.json() == {"error": "RuntimeError", "detail": "boom"}
