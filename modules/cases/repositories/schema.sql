-- Casos evaluados (cada evaluacion es una fila; GET devuelve la ultima por case_id).
CREATE TABLE IF NOT EXISTS case_run (
    id          INTEGER PRIMARY KEY,
    case_id     TEXT NOT NULL,
    tipo_evento TEXT NOT NULL,
    decision    TEXT,
    input_json  TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_case_run_case ON case_run (case_id, id);

CREATE TABLE IF NOT EXISTS question_run (
    id          INTEGER PRIMARY KEY,
    pregunta    TEXT NOT NULL,
    decision    TEXT,
    result_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
