-- Persistencia del auditor. TODO es append-only: el repositorio no expone
-- UPDATE/DELETE y los triggers lo impiden a nivel de base. Aun asi, la cadena
-- de hashes de audit_event permite DETECTAR una manipulacion directa del archivo.

CREATE TABLE IF NOT EXISTS audit_interaction (
    audit_id       TEXT PRIMARY KEY,
    interaction_id TEXT NOT NULL,
    user_id        TEXT NOT NULL,
    role           TEXT NOT NULL,
    query          TEXT NOT NULL,
    use_case       TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    requested_by   TEXT,
    request_json   TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS response_claim (
    id                INTEGER PRIMARY KEY,
    audit_id          TEXT NOT NULL REFERENCES audit_interaction(audit_id),
    claim_id          TEXT NOT NULL,
    text              TEXT NOT NULL,
    type              TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claim_validation (
    id           INTEGER PRIMARY KEY,
    audit_id     TEXT NOT NULL REFERENCES audit_interaction(audit_id),
    claim_id     TEXT,
    validator    TEXT NOT NULL,
    status       TEXT NOT NULL,
    critical     INTEGER NOT NULL,
    reason       TEXT NOT NULL,
    details_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_decision (
    audit_id       TEXT PRIMARY KEY REFERENCES audit_interaction(audit_id),
    decision       TEXT NOT NULL,
    score          REAL NOT NULL,
    risk_level     TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    result_json    TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS human_review (
    id         INTEGER PRIMARY KEY,
    audit_id   TEXT NOT NULL REFERENCES audit_interaction(audit_id),
    reviewer   TEXT NOT NULL,
    decision   TEXT NOT NULL CHECK (decision IN ('aprobada', 'rechazada')),
    comment    TEXT,
    created_at TEXT NOT NULL
);

-- hash = SHA-256(prev_hash + registro canonico {ts, actor, action, payload}).
CREATE TABLE IF NOT EXISTS audit_event (
    id           INTEGER PRIMARY KEY,
    ts           TEXT NOT NULL,
    actor        TEXT NOT NULL,
    action       TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    prev_hash    TEXT NOT NULL,
    hash         TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS ix_claim_audit ON response_claim (audit_id);
CREATE INDEX IF NOT EXISTS ix_validation_audit ON claim_validation (audit_id);
CREATE INDEX IF NOT EXISTS ix_review_audit ON human_review (audit_id);

CREATE TRIGGER IF NOT EXISTS ao_event_u BEFORE UPDATE ON audit_event BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS ao_event_d BEFORE DELETE ON audit_event BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS ao_decision_u BEFORE UPDATE ON policy_decision BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS ao_decision_d BEFORE DELETE ON policy_decision BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS ao_review_u BEFORE UPDATE ON human_review BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS ao_review_d BEFORE DELETE ON human_review BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS ao_interaction_u BEFORE UPDATE ON audit_interaction BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS ao_interaction_d BEFORE DELETE ON audit_interaction BEGIN SELECT RAISE(ABORT, 'append-only'); END;
