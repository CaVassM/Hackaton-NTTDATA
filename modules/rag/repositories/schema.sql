-- SQLite es la FUENTE DE VERDAD. Chroma y BM25 son indices derivados que se
-- pueden reconstruir desde aqui. Fechas en ISO-8601 (TEXT): comparan bien
-- lexicograficamente.

CREATE TABLE IF NOT EXISTS norma (
    id            INTEGER PRIMARY KEY,
    codigo        TEXT NOT NULL UNIQUE,
    titulo        TEXT NOT NULL,
    fecha_emision TEXT NOT NULL,
    tipo          TEXT NOT NULL,
    estado        TEXT NOT NULL CHECK (estado IN ('vigente', 'proyecto', 'derogada')),
    fuente        TEXT
);

CREATE TABLE IF NOT EXISTS articulo (
    id       INTEGER PRIMARY KEY,
    norma_id INTEGER NOT NULL REFERENCES norma(id),
    numero   TEXT NOT NULL,
    UNIQUE (norma_id, numero)
);

CREATE TABLE IF NOT EXISTS version (
    id            INTEGER PRIMARY KEY,
    articulo_id   INTEGER NOT NULL REFERENCES articulo(id),
    texto         TEXT NOT NULL,
    vigente_desde TEXT NOT NULL,
    vigente_hasta TEXT,                       -- NULL = sigue vigente; exclusivo
    creada_por    INTEGER NOT NULL REFERENCES norma(id),
    reemplaza_a   INTEGER REFERENCES version(id),
    CHECK (vigente_hasta IS NULL OR vigente_hasta > vigente_desde)
);

CREATE INDEX IF NOT EXISTS ix_version_articulo ON version (articulo_id, vigente_desde);
CREATE INDEX IF NOT EXISTS ix_version_reemplaza ON version (reemplaza_a);
-- A lo sumo UNA version abierta por articulo: la ingesta debe cerrar antes de abrir.
CREATE UNIQUE INDEX IF NOT EXISTS ux_version_abierta ON version (articulo_id) WHERE vigente_hasta IS NULL;
