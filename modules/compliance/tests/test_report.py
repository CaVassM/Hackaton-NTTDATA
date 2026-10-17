"""Validacion humana, exposicion y reporte (solo filas validadas)."""
import pytest
from fastapi.testclient import TestClient

from modules.audit import AuditFacade, AuditSettings, Decision
from modules.compliance import (
    MONTO_NO_DETERMINADO,
    ROTULO_EXPOSICION,
    ComplianceError,
    EstadoPlazo,
    Infraccion,
    PropuestaNoEncontrada,
)
from modules.compliance.api.app import create_app
from modules.compliance.exposure import ExposureCalculator
from modules.compliance.tests.conftest import HOY, make_facade, responder_correcto


def _inf(mn, mx):
    return Infraccion(1, "2.1", "x", "grave", None, mn, mx, "cita", 1, "N", "2", "m")


def test_exposicion_no_calcula_montos_sin_multa_en_la_cita():
    x = ExposureCalculator(5500.0).calcular(_inf(None, None))
    assert not x.monto_determinado and x.min_soles is None and x.max_soles is None
    assert MONTO_NO_DETERMINADO in x.nota and x.rotulo == ROTULO_EXPOSICION


def test_exposicion_con_multa_y_uit():
    x = ExposureCalculator(5000.0).calcular(_inf(20.0, 50.0))
    assert (x.min_soles, x.max_soles) == (100000.0, 250000.0) and x.monto_determinado
    solo_uit = ExposureCalculator(None).calcular(_inf(20.0, 50.0))
    assert solo_uit.max_soles is None and "UIT_VALOR" in solo_uit.nota


@pytest.fixture
def poblada(rag, tmp_path):
    """Facade con obligaciones e infracciones extraidas (todo como propuesta)."""
    auditor = AuditFacade.from_settings(AuditSettings(log_dir=tmp_path / "alog", audit_dir=tmp_path / "audit"), rag=rag, today=lambda: HOY)
    f, _ = make_facade(rag, tmp_path, responder_correcto, uit=5000.0, auditor=auditor)
    f.extract_obligations(["BAN-004", "BAN-005", "BAN-007"])
    f.extract_infractions(["BAN-004"])
    return f


def test_propuestas_no_entran_al_reporte(poblada):
    rep, _ = poblada.report(HOY)
    assert rep.items == [] and rep.propuestas_pendientes["obligaciones"] >= 3
    assert rep.rotulo == ROTULO_EXPOSICION


def test_solo_filas_validadas_entran_al_reporte(poblada):
    p = poblada.proposals()
    ros = next(o for o in p["obligaciones"] if o.plazo_valor == 24)
    poblada.review(ros.proposal_id, True, "oficial.cumplimiento")
    enlace = p["enlaces"][0]
    poblada.review(enlace.proposal_id, True, "oficial.cumplimiento")

    # Enlace validado pero infraccion SIN validar: no hay exposicion.
    rep, _ = poblada.report(HOY)
    (item,) = rep.items
    assert item.obligacion.codigo == ros.codigo and item.infracciones == []
    assert item.estado == EstadoPlazo.ATRASADO  # CSV: ROS enviado 5 dias despues
    assert {c.sujeto_id for c in item.casos} == {"ROS-2026-0101", "ROS-2026-0115", "ROS-2026-0142"}

    poblada.review(f"inf-{enlace.infraccion_id}", True, "oficial.cumplimiento")
    inf = poblada._repo.get_infraccion(enlace.infraccion_id)
    rep, _ = poblada.report(HOY)
    (item,) = rep.items
    (ir,) = item.infracciones
    assert ir.sintetica and ir.exposicion.monto_determinado
    assert item.rango_uit == (inf.multa_min_uit, inf.multa_max_uit)  # tal cual la cita, sin inventar
    assert item.rango_soles == (inf.multa_min_uit * 5000.0, inf.multa_max_uit * 5000.0)
    assert {c.tipo for c in item.citas} == {"obligacion", "infraccion"}
    assert any("SINTETICO" in a for a in rep.advertencias)


def test_rechazada_no_entra_y_revision_queda_registrada(poblada):
    o = poblada.proposals()["obligaciones"][0]
    poblada.review(o.proposal_id, False, "ana", "no aplica a bancos")
    assert poblada.report(HOY)[0].items == []
    assert poblada._repo.revision_log()[-1][2:4] == ("rechazada", "ana")
    with pytest.raises(ComplianceError):
        poblada.review(o.proposal_id, True, "  ")
    with pytest.raises(PropuestaNoEncontrada):
        poblada.review("obl-9999", True, "ana")


def test_to_candidate_response_y_auditoria(poblada):
    reg = next(o for o in poblada.proposals()["obligaciones"] if o.categoria == "BAN-005")
    poblada.review(reg.proposal_id, True, "ana")
    rep, audit = poblada.report(HOY, ["BAN-005"], auditar=True)
    cand = rep.to_candidate_response()
    normativas = [c for c in cand.claims if c.type == "normativa"]
    assert normativas and all(c.evidence_ids == [reg.version_id] for c in normativas)
    # Cita literal y vigente -> sin criticos; datos del caso pendientes -> WARN (deseado).
    assert audit.decision == Decision.WARN, audit.checks["decision_reason"]
    assert not [f for f in audit.findings if f.critical]


def test_api_extract_background_proposals_review_report(rag, tmp_path):
    f, _ = make_facade(rag, tmp_path, responder_correcto)
    with TestClient(create_app(f)) as c:
        job = c.post("/compliance/extract", json={"tipo": "obligaciones", "categorias": ["BAN-004"]}).json()
        estado = c.get(f"/compliance/extract/{job['job_id']}").json()
        assert estado["estado"] == "terminado" and estado["resultado"][0]["propuestas_nuevas"] >= 1
        assert c.post("/compliance/extract", json={"categorias": ["BAN-999"]}).status_code == 400
        props = c.get("/compliance/proposals").json()["obligaciones"]
        pid = props[0]["proposal_id"]
        r = c.post(f"/compliance/proposals/{pid}/review", json={"aprobar": True, "revisor": "ana"})
        assert r.status_code == 200
        assert c.post("/compliance/proposals/obl-9999/review", json={"aprobar": True, "revisor": "a"}).status_code == 404
        rep = c.post("/compliance/report", json={"fecha_corte": "2026-10-17"}).json()["reporte"]
        assert len(rep["items"]) == 1 and rep["rotulo"] == ROTULO_EXPOSICION


# --- evaluar_caso (lo consume modules/cases) ---
def test_evaluar_caso_solo_calcula_validadas(poblada):
    from datetime import date as _d

    from modules.compliance import EvidenciaInterna

    ros = next(o for o in poblada.proposals()["obligaciones"] if o.plazo_valor == 24)
    ev = [EvidenciaInterna("BAN-004", "CASO-1", _d(2026, 9, 10), _d(2026, 9, 15))]
    antes = poblada.evaluar_caso("BAN-004", ev, HOY)
    assert antes.items == [] and ros.codigo in {o.codigo for o in antes.sin_validar}

    poblada.review(ros.proposal_id, True, "ana")
    caso = poblada.evaluar_caso("BAN-004", ev, HOY, codigos=[ros.codigo, "BAN-004-99"])
    (item,) = caso.items
    (c,) = item.casos
    assert c.estado == EstadoPlazo.ATRASADO and c.dias_atraso == 4 and c.sujeto_id == "CASO-1"
    assert caso.no_encontradas == ["BAN-004-99"] and caso.sin_validar == []
    with pytest.raises(ComplianceError):
        poblada.evaluar_caso("BAN-999", ev, HOY)
    assert poblada.conteos()["obligaciones"]["validada"] == 1
