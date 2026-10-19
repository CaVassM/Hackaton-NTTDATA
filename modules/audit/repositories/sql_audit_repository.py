"""Repositorio append-only del auditor con cadena de hashes.

Solo hay INSERT y SELECT (sin UPDATE/DELETE). Cada escritura deja un evento en
audit_event con hash = SHA-256(prev_hash + registro canonico). verify_chain()
recalcula toda la cadena y cruza los digests con las tablas de datos, asi que
detecta cambios hechos por fuera del repositorio (p. ej. editando el .sqlite).
El append usa BEGIN IMMEDIATE: la app unificada y el agente A2A pueden escribir
en la misma base desde procesos distintos sin bifurcar la cadena.
"""
import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from modules.audit.domain import (
    AuditEvent,
    AuditNotFound,
    AuditRecord,
    AuditRequest,
    AuditResult,
    AuditTrace,
    ChainReport,
    HumanReview,
    TraceEvent,
)

_SCHEMA = Path(__file__).with_name("schema.sql")
GENESIS = "0" * 64


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def event_hash(prev_hash: str, ts: str, actor: str, action: str, payload_json: str) -> str:
    registro = canonical({"ts": ts, "actor": actor, "action": action, "payload": json.loads(payload_json)})
    return sha256(prev_hash + registro)


class SqlAuditRepository:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._lock = threading.Lock()

    @property
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            # isolation_level=None: las transacciones las abrimos nosotros (BEGIN IMMEDIATE).
            conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA foreign_keys = ON")
            self._local.conn = conn
        return conn

    def init_schema(self) -> None:
        self._conn.executescript(_SCHEMA.read_text(encoding="utf-8"))

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            c = self._conn
            c.execute("BEGIN IMMEDIATE")  # lock de escritura a nivel de BASE (multi-proceso)
            try:
                yield c
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise

    def _append_event(self, c: sqlite3.Connection, actor: str, action: str, payload: dict[str, Any]) -> str:
        row = c.execute("SELECT hash FROM audit_event ORDER BY id DESC LIMIT 1").fetchone()
        prev = row[0] if row else GENESIS
        ts, pj = _now(), canonical(payload)
        h = event_hash(prev, ts, actor, action, pj)
        c.execute("INSERT INTO audit_event (ts, actor, action, payload_json, prev_hash, hash) VALUES (?,?,?,?,?,?)",
                  (ts, actor, action, pj, prev, h))
        return h

    # -------------------------------------------------------------- escritura
    def save_evaluation(self, req: AuditRequest, result: AuditResult, requested_by: str | None,
                        transport: dict[str, Any] | None = None) -> None:
        result_json = result.model_dump_json()
        ts = _now()
        with self._tx() as c:
            c.execute(
                """INSERT INTO audit_interaction (audit_id, interaction_id, user_id, role, query, use_case,
                   effective_date, requested_by, request_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (result.audit_id, req.interaction_id, req.user_id, req.role, req.query, req.use_case,
                 str(result.effective_date), requested_by, req.model_dump_json(), ts),
            )
            c.executemany(
                "INSERT INTO response_claim (audit_id, claim_id, text, type, evidence_ids_json) VALUES (?,?,?,?,?)",
                [(result.audit_id, cl.claim_id, cl.text, cl.type.value, json.dumps(cl.evidence_ids))
                 for cl in req.candidate.claims],
            )
            c.executemany(
                """INSERT INTO claim_validation (audit_id, claim_id, validator, status, critical, reason, details_json)
                   VALUES (?,?,?,?,?,?,?)""",
                [(result.audit_id, f.claim_id, f.validator, f.status.value, int(f.critical), f.reason,
                  canonical(f.details)) for f in result.findings],
            )
            c.execute(
                """INSERT INTO policy_decision (audit_id, decision, score, risk_level, policy_version, result_json,
                   created_at) VALUES (?,?,?,?,?,?,?)""",
                (result.audit_id, result.decision.value, result.score, result.risk_level, result.policy_version,
                 result_json, ts),
            )
            self._append_event(c, requested_by or "desconocido", "audit.evaluate", {
                "audit_id": result.audit_id, "interaction_id": req.interaction_id, "decision": result.decision.value,
                "score": result.score, "policy_version": result.policy_version, "result_sha256": sha256(result_json),
                # Metadatos del mensaje A2A: quedan sellados en el hash (no se pueden reescribir sin romper la cadena).
                **({"transporte": transport} if transport else {}),
            })

    def add_review(self, audit_id: str, reviewer: str, decision: str, comment: str | None) -> HumanReview:
        ts = _now()
        with self._tx() as c:
            if not c.execute("SELECT 1 FROM audit_interaction WHERE audit_id=?", (audit_id,)).fetchone():
                raise AuditNotFound(audit_id)
            rid = c.execute("INSERT INTO human_review (audit_id, reviewer, decision, comment, created_at) VALUES (?,?,?,?,?)",
                            (audit_id, reviewer, decision, comment, ts)).lastrowid
            self._append_event(c, reviewer, "audit.review", {
                "audit_id": audit_id, "review_id": rid, "decision": decision,
                "comment_sha256": sha256(comment or ""),
            })
        return HumanReview(review_id=rid, audit_id=audit_id, reviewer=reviewer, decision=decision,
                           comment=comment, created_at=ts)

    # ---------------------------------------------------------------- lectura
    def get(self, audit_id: str) -> AuditRecord:
        row = self._conn.execute("SELECT result_json FROM policy_decision WHERE audit_id=?", (audit_id,)).fetchone()
        if row is None:
            raise AuditNotFound(audit_id)
        reviews = [HumanReview(review_id=r[0], audit_id=audit_id, reviewer=r[1], decision=r[2], comment=r[3], created_at=r[4])
                   for r in self._conn.execute(
                       "SELECT id, reviewer, decision, comment, created_at FROM human_review WHERE audit_id=? ORDER BY id",
                       (audit_id,)).fetchall()]
        return AuditRecord(result=AuditResult.model_validate_json(row[0]), reviews=reviews,
                           revision_final=reviews[-1].decision if reviews else None)

    def trace(self, audit_id: str) -> AuditTrace:
        c = self._conn
        row = c.execute("SELECT interaction_id, requested_by, request_json, created_at FROM audit_interaction "
                        "WHERE audit_id=?", (audit_id,)).fetchone()
        if row is None:
            raise AuditNotFound(audit_id)
        record = self.get(audit_id)
        result_digest = sha256(c.execute("SELECT result_json FROM policy_decision WHERE audit_id=?",
                                         (audit_id,)).fetchone()[0])
        eventos, transporte = [], None
        for eid, ts, actor, action, pj, prev_hash, h in c.execute(
                "SELECT id, ts, actor, action, payload_json, prev_hash, hash FROM audit_event "
                "WHERE json_extract(payload_json, '$.audit_id') = ? ORDER BY id", (audit_id,)):
            payload = json.loads(pj)
            if action == "audit.evaluate":
                transporte = payload.get("transporte")
            eventos.append(TraceEvent(
                id=eid, ts=ts, actor=actor, action=action, payload=payload, prev_hash=prev_hash, hash=h,
                hash_verificado=event_hash(prev_hash, ts, actor, action, pj) == h,
                resultado_verificado=payload.get("result_sha256") == result_digest if action == "audit.evaluate" else None,
            ))
        canal = "a2a" if transporte else "api" if row[1] == "api" else "en_proceso"
        return AuditTrace(audit_id=audit_id, interaction_id=row[0], canal=canal, solicitado_por=row[1],
                          transporte=transporte, solicitado_en=row[3], request=json.loads(row[2]),
                          record=record, eventos=eventos)

    def events(self, limit: int = 100) -> list[AuditEvent]:
        rows = self._conn.execute(
            "SELECT id, ts, actor, action, payload_json, prev_hash, hash FROM audit_event ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
        return [AuditEvent(id=r[0], ts=r[1], actor=r[2], action=r[3], payload=json.loads(r[4]), prev_hash=r[5], hash=r[6])
                for r in rows]

    def counts(self) -> dict[str, Any]:
        c = self._conn
        return {
            "auditorias": c.execute("SELECT COUNT(*) FROM policy_decision").fetchone()[0],
            "por_decision": dict(c.execute("SELECT decision, COUNT(*) FROM policy_decision GROUP BY decision").fetchall()),
            "revisiones": c.execute("SELECT COUNT(*) FROM human_review").fetchone()[0],
            "eventos": c.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0],
            "por_solicitante": dict(c.execute(
                "SELECT COALESCE(requested_by, 'desconocido'), COUNT(*) FROM audit_interaction GROUP BY 1").fetchall()),
            "via_a2a": c.execute("SELECT COUNT(*) FROM audit_event WHERE action='audit.evaluate' "
                                 "AND json_extract(payload_json, '$.transporte.protocolo') = 'A2A'").fetchone()[0],
        }

    # ----------------------------------------------------------- verificacion
    def verify_chain(self) -> ChainReport:
        c = self._conn
        rows = c.execute("SELECT id, ts, actor, action, payload_json, prev_hash, hash FROM audit_event ORDER BY id").fetchall()
        auditorias = c.execute("SELECT COUNT(*) FROM policy_decision").fetchone()[0]

        def falla(eid, motivo):
            return ChainReport(ok=False, eventos=len(rows), auditorias=auditorias, primer_error_id=eid, motivo=motivo)

        prev = GENESIS
        evaluados: dict[str, str] = {}
        revisados: set[int] = set()
        for eid, ts, actor, action, pj, prev_hash, h in rows:
            if prev_hash != prev:
                return falla(eid, "prev_hash no coincide: evento borrado, insertado o reordenado antes de este")
            try:
                esperado = event_hash(prev, ts, actor, action, pj)
            except ValueError:
                return falla(eid, "payload ilegible")
            if esperado != h:
                return falla(eid, "hash no coincide: el evento fue modificado")
            payload = json.loads(pj)
            if action == "audit.evaluate":
                evaluados[payload["audit_id"]] = payload["result_sha256"]
            elif action == "audit.review":
                revisados.add(payload["review_id"])
            prev = h

        # Cruce con las tablas de datos: un resultado editado o una fila sin evento.
        for audit_id, result_json in c.execute("SELECT audit_id, result_json FROM policy_decision"):
            if audit_id not in evaluados:
                return falla(None, f"auditoria {audit_id} sin evento en la cadena")
            if sha256(result_json) != evaluados[audit_id]:
                return falla(None, f"resultado de la auditoria {audit_id} modificado (digest distinto)")
        for (rid,) in c.execute("SELECT id FROM human_review"):
            if rid not in revisados:
                return falla(None, f"revision {rid} sin evento en la cadena")
        return ChainReport(ok=True, eventos=len(rows), auditorias=auditorias, ultimo_hash=prev if rows else None)
