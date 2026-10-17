"""SQLite del modulo compliance. SQL fijo y parametrizado; los nombres de
tabla salen de un mapa cerrado (nunca de la entrada del usuario)."""
import hashlib
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from modules.compliance.domain import (
    Enlace,
    EstadoPropuesta,
    Infraccion,
    Obligacion,
    PropuestaNoEncontrada,
    Revision,
    TipoPropuesta,
)

_SCHEMA = Path(__file__).with_name("schema.sql")
_TABLA = {
    TipoPropuesta.OBLIGACION: "obligacion",
    TipoPropuesta.INFRACCION: "infraccion",
    TipoPropuesta.ENLACE: "categoria_infraccion",
}
_OBL_COLS = ("id, codigo, categoria, sujeto, accion_requerida, evento_disparador, plazo_texto, plazo_valor, "
             "plazo_unidad, tipo_plazo, evidencia_requerida, cita_textual, version_id, norma_codigo, "
             "articulo_numero, score_recuperacion, modelo, estado, revisado_por, revisado_en, comentario")
_INF_COLS = ("id, codigo_numeral, descripcion, gravedad, sancion_texto, multa_min_uit, multa_max_uit, cita_textual, "
             "version_id, norma_codigo, articulo_numero, modelo, estado, revisado_por, revisado_en, comentario")
_ENL_COLS = "id, categoria, infraccion_id, score, relacionada, motivo, estado, revisado_por, revisado_en, comentario"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cita_hash(cita: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", cita).strip().encode()).hexdigest()[:24]


def _rev(row) -> Revision:
    return Revision(EstadoPropuesta(row[0]), row[1], datetime.fromisoformat(row[2]) if row[2] else None, row[3])


def _obl(r) -> Obligacion:
    return Obligacion(*r[:17], revision=_rev(r[17:21]))


def _inf(r) -> Infraccion:
    return Infraccion(*r[:12], revision=_rev(r[12:16]))


def _enl(r) -> Enlace:
    return Enlace(r[0], r[1], r[2], r[3], bool(r[4]), r[5], revision=_rev(r[6:10]))


class SqliteComplianceRepository:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.Lock()  # la extraccion en background escribe en paralelo a la API

    @property
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")  # lecturas de la API mientras corre la extraccion
            self._local.conn = conn
        return conn

    def init_schema(self) -> None:
        self._conn.executescript(_SCHEMA.read_text(encoding="utf-8"))
        self._conn.commit()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            conn = self._conn
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    # ------------------------------------------------------------ obligaciones
    def insert_obligacion(self, o: Obligacion) -> Obligacion | None:
        """Inserta como propuesta con codigo correlativo por categoria.
        Devuelve None si ya existia (misma categoria, version y cita)."""
        h = cita_hash(o.cita_textual)
        with self._tx() as c:
            if c.execute("SELECT 1 FROM obligacion WHERE categoria=? AND version_id=? AND cita_hash=?",
                         (o.categoria, o.version_id, h)).fetchone():
                return None
            n = c.execute("SELECT COUNT(*) FROM obligacion WHERE categoria=?", (o.categoria,)).fetchone()[0]
            codigo = f"{o.categoria}-{n + 1:02d}"
            cur = c.execute(
                """INSERT INTO obligacion (codigo, categoria, sujeto, accion_requerida, evento_disparador,
                   plazo_texto, plazo_valor, plazo_unidad, tipo_plazo, evidencia_requerida, cita_textual, cita_hash,
                   version_id, norma_codigo, articulo_numero, score_recuperacion, modelo, creado_en)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (codigo, o.categoria, o.sujeto, o.accion_requerida, o.evento_disparador, o.plazo_texto,
                 o.plazo_valor, o.plazo_unidad, o.tipo_plazo, o.evidencia_requerida, o.cita_textual, h,
                 o.version_id, o.norma_codigo, o.articulo_numero, o.score_recuperacion, o.modelo, _now()),
            )
        return self.get_obligacion(cur.lastrowid)

    def get_obligacion(self, id_: int) -> Obligacion:
        r = self._conn.execute(f"SELECT {_OBL_COLS} FROM obligacion WHERE id=?", (id_,)).fetchone()
        if r is None:
            raise PropuestaNoEncontrada(f"obl-{id_}")
        return _obl(r)

    def list_obligaciones(self, estado: EstadoPropuesta | None = None, categoria: str | None = None) -> list[Obligacion]:
        rows = self._conn.execute(
            f"""SELECT {_OBL_COLS} FROM obligacion
                WHERE (:estado IS NULL OR estado = :estado) AND (:cat IS NULL OR categoria = :cat)
                ORDER BY codigo""",
            {"estado": estado.value if estado else None, "cat": categoria},
        ).fetchall()
        return [_obl(r) for r in rows]

    # ------------------------------------------------------------ infracciones
    def insert_infraccion(self, i: Infraccion) -> Infraccion:
        """Idempotente por (version, cita): devuelve la existente si ya estaba."""
        h = cita_hash(i.cita_textual)
        with self._tx() as c:
            row = c.execute("SELECT id FROM infraccion WHERE version_id=? AND cita_hash=?", (i.version_id, h)).fetchone()
            if row:
                id_ = row[0]
            else:
                id_ = c.execute(
                    """INSERT INTO infraccion (codigo_numeral, descripcion, gravedad, sancion_texto, multa_min_uit,
                       multa_max_uit, cita_textual, cita_hash, version_id, norma_codigo, articulo_numero, modelo,
                       creado_en) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (i.codigo_numeral, i.descripcion, i.gravedad, i.sancion_texto, i.multa_min_uit, i.multa_max_uit,
                     i.cita_textual, h, i.version_id, i.norma_codigo, i.articulo_numero, i.modelo, _now()),
                ).lastrowid
        return self.get_infraccion(id_)

    def get_infraccion(self, id_: int) -> Infraccion:
        r = self._conn.execute(f"SELECT {_INF_COLS} FROM infraccion WHERE id=?", (id_,)).fetchone()
        if r is None:
            raise PropuestaNoEncontrada(f"inf-{id_}")
        return _inf(r)

    def list_infracciones(self, estado: EstadoPropuesta | None = None) -> list[Infraccion]:
        rows = self._conn.execute(
            f"SELECT {_INF_COLS} FROM infraccion WHERE (:e IS NULL OR estado = :e) ORDER BY id",
            {"e": estado.value if estado else None},
        ).fetchall()
        return [_inf(r) for r in rows]

    # ----------------------------------------------------------------- enlaces
    def insert_enlace(self, categoria: str, infraccion_id: int, score: float, relacionada: bool, motivo: str) -> Enlace | None:
        with self._tx() as c:
            if c.execute("SELECT 1 FROM categoria_infraccion WHERE categoria=? AND infraccion_id=?",
                         (categoria, infraccion_id)).fetchone():
                return None
            id_ = c.execute(
                """INSERT INTO categoria_infraccion (categoria, infraccion_id, score, relacionada, motivo, creado_en)
                   VALUES (?,?,?,?,?,?)""",
                (categoria, infraccion_id, score, int(relacionada), motivo, _now()),
            ).lastrowid
        return self.get_enlace(id_)

    def get_enlace(self, id_: int) -> Enlace:
        r = self._conn.execute(f"SELECT {_ENL_COLS} FROM categoria_infraccion WHERE id=?", (id_,)).fetchone()
        if r is None:
            raise PropuestaNoEncontrada(f"enl-{id_}")
        return _enl(r)

    def list_enlaces(self, estado: EstadoPropuesta | None = None, categoria: str | None = None) -> list[Enlace]:
        rows = self._conn.execute(
            f"""SELECT {_ENL_COLS} FROM categoria_infraccion
                WHERE (:e IS NULL OR estado = :e) AND (:cat IS NULL OR categoria = :cat) ORDER BY categoria, score DESC""",
            {"e": estado.value if estado else None, "cat": categoria},
        ).fetchall()
        return [_enl(r) for r in rows]

    # -------------------------------------------------------------- revision
    def review(self, tipo: TipoPropuesta, id_: int, estado: EstadoPropuesta, revisor: str,
               comentario: str | None = None) -> None:
        tabla = _TABLA[tipo]  # mapa cerrado: nunca se interpola entrada del usuario
        ts = _now()
        with self._tx() as c:
            cur = c.execute(
                f"UPDATE {tabla} SET estado=?, revisado_por=?, revisado_en=?, comentario=? WHERE id=?",
                (estado.value, revisor, ts, comentario, id_),
            )
            if cur.rowcount == 0:
                raise PropuestaNoEncontrada(f"{tipo}-{id_}")
            c.execute(
                "INSERT INTO revision_log (tipo, propuesta_id, decision, revisor, comentario, ts) VALUES (?,?,?,?,?,?)",
                (tipo.value, id_, estado.value, revisor, comentario, ts),
            )

    def revision_log(self) -> list[tuple]:
        return self._conn.execute(
            "SELECT tipo, propuesta_id, decision, revisor, comentario, ts FROM revision_log ORDER BY id").fetchall()

    # ------------------------------------------------------------- cache LLM
    def cache_get(self, key: str) -> str | None:
        r = self._conn.execute("SELECT respuesta FROM llm_cache WHERE cache_key=?", (key,)).fetchone()
        return r[0] if r else None

    def cache_put(self, key: str, version_id: int, modelo: str, prompt_hash: str, respuesta: str) -> None:
        with self._tx() as c:
            c.execute(
                """INSERT OR REPLACE INTO llm_cache (cache_key, version_id, modelo, prompt_hash, respuesta, creado_en)
                   VALUES (?,?,?,?,?,?)""",
                (key, version_id, modelo, prompt_hash, respuesta, _now()),
            )
