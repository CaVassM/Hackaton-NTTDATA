"""Persistencia append-only, revision humana y cadena de hashes."""
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.audit import AuditNotFound, Decision, create_audit_router
from modules.audit.tests.conftest import V_ART2_VIGENTE, audit_request, claim, ok_request


def _db(settings) -> sqlite3.Connection:
    return sqlite3.connect(settings.audit_db_path)


def _bypass_triggers(conn: sqlite3.Connection) -> None:
    """Simula a un atacante con acceso al archivo: quita los triggers append-only."""
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
        conn.execute(f"DROP TRIGGER {name}")


def test_evaluate_persiste_y_get_devuelve_lo_mismo(audit):
    res = audit.evaluate(ok_request(), requested_by="copilot")
    rec = audit.get(res.audit_id)
    assert rec.result == res and rec.reviews == [] and rec.revision_final is None
    with pytest.raises(AuditNotFound):
        audit.get("no-existe")


def test_review_humana_append_only_y_en_cadena(audit):
    res = audit.evaluate(audit_request([claim("c1", "El plazo es de 15 días.", evidence=[V_ART2_VIGENTE])],
                                       query="¿Debo presentar un ROS?"))
    assert res.decision == Decision.ESCALATE
    audit.review(res.audit_id, "oficial.1", True, "revisado, procede")
    audit.review(res.audit_id, "oficial.2", False, "segunda opinion: no procede")
    rec = audit.get(res.audit_id)
    assert [r.decision for r in rec.reviews] == ["aprobada", "rechazada"] and rec.revision_final == "rechazada"
    with pytest.raises(ValueError):
        audit.review(res.audit_id, "  ", True)
    with pytest.raises(AuditNotFound):
        audit.review("no-existe", "x", True)
    rep = audit.verify_chain()
    assert rep.ok and rep.eventos == 3 and rep.auditorias == 1


def test_triggers_impiden_update_y_delete(audit, settings):
    audit.evaluate(ok_request())
    with _db(settings) as c, pytest.raises(sqlite3.DatabaseError, match="append-only"):
        c.execute("UPDATE policy_decision SET decision='ALLOW'")
    with _db(settings) as c, pytest.raises(sqlite3.DatabaseError, match="append-only"):
        c.execute("DELETE FROM audit_event")


def test_manipular_un_evento_se_detecta(audit, settings):
    for _ in range(3):
        audit.evaluate(ok_request())
    assert audit.verify_chain().ok
    with _db(settings) as c:
        _bypass_triggers(c)
        c.execute("UPDATE audit_event SET payload_json = replace(payload_json, 'ALLOW', 'BLOCK') WHERE id = 2")
    rep = audit.verify_chain()
    assert not rep.ok and rep.primer_error_id == 2 and "modificado" in rep.motivo


def test_borrar_un_evento_se_detecta(audit, settings):
    for _ in range(3):
        audit.evaluate(ok_request())
    with _db(settings) as c:
        _bypass_triggers(c)
        c.execute("DELETE FROM audit_event WHERE id = 2")
    rep = audit.verify_chain()
    assert not rep.ok and rep.primer_error_id == 3 and "prev_hash" in rep.motivo


def test_alterar_el_resultado_guardado_se_detecta(audit, settings):
    res = audit.evaluate(audit_request([claim("c1", "El plazo es de 10 días.", evidence=[V_ART2_VIGENTE])]))
    assert res.decision == Decision.BLOCK
    with _db(settings) as c:
        _bypass_triggers(c)
        c.execute("UPDATE policy_decision SET result_json = replace(result_json, '\"BLOCK\"', '\"ALLOW\"')")
    rep = audit.verify_chain()
    assert not rep.ok and "modificado" in rep.motivo and res.audit_id in rep.motivo


def test_fila_insertada_sin_evento_se_detecta(audit, settings):
    res = audit.evaluate(ok_request())
    with _db(settings) as c:
        c.execute("INSERT INTO human_review (audit_id, reviewer, decision, comment, created_at) VALUES (?,?,?,?,?)",
                  (res.audit_id, "intruso", "aprobada", None, "2026-01-01"))
    rep = audit.verify_chain()
    assert not rep.ok and "sin evento" in rep.motivo


def test_router_de_audit(audit):
    app = FastAPI()
    app.include_router(create_audit_router(lambda: audit))
    with TestClient(app) as c:
        r = c.post("/audit/evaluate", json=ok_request())
        assert r.status_code == 200 and r.json()["decision"] == "ALLOW"
        aid = r.json()["audit_id"]
        assert c.get(f"/audit/{aid}").json()["result"]["audit_id"] == aid
        rv = c.post(f"/audit/{aid}/review", json={"reviewer": "ana", "aprobar": True, "comentario": "ok"})
        assert rv.status_code == 200 and rv.json()["decision"] == "aprobada"
        assert c.get("/audit/verify-chain").json()["ok"] is True
        assert [e["action"] for e in c.get("/audit/events?limit=5").json()] == ["audit.review", "audit.evaluate"]
        assert c.get("/audit/no-existe").status_code == 404
        assert c.post("/audit/evaluate", json={"query": "x"}).status_code == 422


def test_trace_en_proceso_sin_transporte_y_con_revision(audit):
    res = audit.evaluate(ok_request(), requested_by="cases")
    audit.review(res.audit_id, "oficial.1", True, "ok")
    trace = audit.trace(res.audit_id)
    assert trace.canal == "en_proceso" and trace.transporte is None and trace.solicitado_por == "cases"
    assert [e.action for e in trace.eventos] == ["audit.evaluate", "audit.review"]
    assert all(e.hash_verificado for e in trace.eventos) and trace.record.revision_final == "aprobada"
    assert trace.request["interaction_id"] == res.interaction_id
    assert audit.counts()["por_solicitante"] == {"cases": 1} and audit.counts()["via_a2a"] == 0
    with pytest.raises(AuditNotFound):
        audit.trace("no-existe")
