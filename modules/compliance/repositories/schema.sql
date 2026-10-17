-- SQLite propio del modulo compliance. Las citas apuntan a version_id de rag
-- (no hay FK cruzada entre bases: la integridad la verifica el extractor).

CREATE TABLE IF NOT EXISTS obligacion (
    id                  INTEGER PRIMARY KEY,
    codigo              TEXT NOT NULL UNIQUE,          -- BAN-004-01
    categoria           TEXT NOT NULL,                 -- BAN-004
    sujeto              TEXT NOT NULL,
    accion_requerida    TEXT NOT NULL,
    evento_disparador   TEXT,
    plazo_texto         TEXT,
    plazo_valor         INTEGER,
    plazo_unidad        TEXT CHECK (plazo_unidad IN ('horas', 'dias', 'meses', 'anios')),
    tipo_plazo          TEXT CHECK (tipo_plazo IN ('calendario', 'habil', 'periodico')),
    evidencia_requerida TEXT,
    cita_textual        TEXT NOT NULL,
    cita_hash           TEXT NOT NULL,
    version_id          INTEGER NOT NULL,
    norma_codigo        TEXT NOT NULL,
    articulo_numero     TEXT NOT NULL,
    score_recuperacion  REAL NOT NULL,
    modelo              TEXT NOT NULL,
    estado              TEXT NOT NULL DEFAULT 'propuesta' CHECK (estado IN ('propuesta', 'validada', 'rechazada')),
    revisado_por        TEXT,
    revisado_en         TEXT,
    comentario          TEXT,
    creado_en           TEXT NOT NULL,
    UNIQUE (categoria, version_id, cita_hash)          -- reanudable: reprocesar no duplica
);

CREATE TABLE IF NOT EXISTS infraccion (
    id               INTEGER PRIMARY KEY,
    codigo_numeral   TEXT,
    descripcion      TEXT NOT NULL,
    gravedad         TEXT CHECK (gravedad IN ('leve', 'grave', 'muy_grave')),
    sancion_texto    TEXT,
    multa_min_uit    REAL,
    multa_max_uit    REAL,
    cita_textual     TEXT NOT NULL,
    cita_hash        TEXT NOT NULL,
    version_id       INTEGER NOT NULL,
    norma_codigo     TEXT NOT NULL,
    articulo_numero  TEXT NOT NULL,
    modelo           TEXT NOT NULL,
    estado           TEXT NOT NULL DEFAULT 'propuesta' CHECK (estado IN ('propuesta', 'validada', 'rechazada')),
    revisado_por     TEXT,
    revisado_en      TEXT,
    comentario       TEXT,
    creado_en        TEXT NOT NULL,
    UNIQUE (version_id, cita_hash)
);

-- Enlace categoria -> infraccion (propuesta). score = score de recuperacion.
CREATE TABLE IF NOT EXISTS categoria_infraccion (
    id            INTEGER PRIMARY KEY,
    categoria     TEXT NOT NULL,
    infraccion_id INTEGER NOT NULL REFERENCES infraccion(id),
    score         REAL NOT NULL,
    relacionada   INTEGER NOT NULL,
    motivo        TEXT NOT NULL,
    estado        TEXT NOT NULL DEFAULT 'propuesta' CHECK (estado IN ('propuesta', 'validada', 'rechazada')),
    revisado_por  TEXT,
    revisado_en   TEXT,
    comentario    TEXT,
    creado_en     TEXT NOT NULL,
    UNIQUE (categoria, infraccion_id)
);

-- Bitacora append-only de decisiones humanas (quien, cuando, que).
CREATE TABLE IF NOT EXISTS revision_log (
    id          INTEGER PRIMARY KEY,
    tipo        TEXT NOT NULL,
    propuesta_id INTEGER NOT NULL,
    decision    TEXT NOT NULL,
    revisor     TEXT NOT NULL,
    comentario  TEXT,
    ts          TEXT NOT NULL
);

-- Cache de respuestas del LLM: (version_id, modelo, hash del prompt).
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key   TEXT PRIMARY KEY,
    version_id  INTEGER NOT NULL,
    modelo      TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    respuesta   TEXT NOT NULL,
    creado_en   TEXT NOT NULL
);
