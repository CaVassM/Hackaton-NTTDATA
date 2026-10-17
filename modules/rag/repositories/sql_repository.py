"""Acceso a SQLite. TODO el SQL es fijo y parametrizado: nadie (ni el LLM) arma
consultas dinamicas. Las listas de ids se expanden a placeholders `?`, nunca
se interpolan valores.
"""
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from modules.rag.domain import Articulo, EstadoNorma, Norma, Version, VersionDetalle
from modules.rag.repositories.interfaces import InfoCita

_SCHEMA = Path(__file__).with_name("schema.sql")

# Proyeccion comun de VersionDetalle. `n` = norma del articulo, `c` = creadora.
_DETALLE_SELECT = """
SELECT v.id, v.texto, n.codigo, n.titulo, a.numero, v.vigente_desde, v.vigente_hasta,
       c.codigo, c.estado, v.reemplaza_a
FROM version v
JOIN articulo a ON a.id = v.articulo_id
JOIN norma n    ON n.id = a.norma_id
JOIN norma c    ON c.id = v.creada_por
"""

# Regla de vigencia, en un solo sitio. "hasta" es exclusivo.
_VIGENTE_EN = "(v.vigente_desde <= :fecha AND (v.vigente_hasta IS NULL OR :fecha < v.vigente_hasta))"
_NO_PROYECTO = "c.estado <> 'proyecto'"


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _placeholders(n: int) -> str:
    return ",".join("?" * n)


def _detalle(row: sqlite3.Row | tuple) -> VersionDetalle:
    return VersionDetalle(
        version_id=row[0],
        texto=row[1],
        norma_codigo=row[2],
        norma_titulo=row[3],
        articulo_numero=row[4],
        vigente_desde=_d(row[5]),
        vigente_hasta=_d(row[6]),
        creada_por_codigo=row[7],
        estado_norma_creadora=EstadoNorma(row[8]),
        reemplaza_a=row[9],
    )


class SqliteRepository:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Una conexion por hilo: FastAPI atiende endpoints sync en un threadpool.
        self._local = threading.local()

    # ---------------------------------------------------------------- infra
    @property
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path)
            conn.execute("PRAGMA foreign_keys = ON")
            self._local.conn = conn
        return conn

    def init_schema(self) -> None:
        self._conn.executescript(_SCHEMA.read_text(encoding="utf-8"))
        self._conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._conn
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # ------------------------------------------------------------- escritura
    def insert_norma(self, norma: Norma, fuente: str | None = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO norma (codigo, titulo, fecha_emision, tipo, estado, fuente) VALUES (?, ?, ?, ?, ?, ?)",
            (norma.codigo, norma.titulo, norma.fecha_emision.isoformat(), norma.tipo, norma.estado.value, fuente),
        )
        return cur.lastrowid

    def get_or_create_articulo(self, norma_id: int, numero: str) -> Articulo:
        self._conn.execute(
            "INSERT OR IGNORE INTO articulo (norma_id, numero) VALUES (?, ?)", (norma_id, numero)
        )
        row = self._conn.execute(
            "SELECT id, norma_id, numero FROM articulo WHERE norma_id = ? AND numero = ?", (norma_id, numero)
        ).fetchone()
        return Articulo(*row)

    def insert_version(self, version: Version) -> int:
        cur = self._conn.execute(
            """INSERT INTO version (articulo_id, texto, vigente_desde, vigente_hasta, creada_por, reemplaza_a)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                version.articulo_id,
                version.texto,
                version.vigente_desde.isoformat(),
                version.vigente_hasta.isoformat() if version.vigente_hasta else None,
                version.creada_por,
                version.reemplaza_a,
            ),
        )
        return cur.lastrowid

    def close_version(self, version_id: int, hasta: date) -> None:
        self._conn.execute(
            "UPDATE version SET vigente_hasta = ? WHERE id = ? AND vigente_hasta IS NULL",
            (hasta.isoformat(), version_id),
        )

    # ---------------------------------------------------------------- lectura
    def get_norma(self, codigo: str) -> Norma | None:
        row = self._conn.execute(
            "SELECT id, codigo, titulo, fecha_emision, tipo, estado FROM norma WHERE codigo = ?", (codigo,)
        ).fetchone()
        if row is None:
            return None
        return Norma(row[0], row[1], row[2], _d(row[3]), row[4], EstadoNorma(row[5]))

    def get_articulo(self, norma_codigo: str, numero: str) -> Articulo | None:
        row = self._conn.execute(
            """SELECT a.id, a.norma_id, a.numero FROM articulo a JOIN norma n ON n.id = a.norma_id
               WHERE n.codigo = ? AND a.numero = ?""",
            (norma_codigo, numero),
        ).fetchone()
        return Articulo(*row) if row else None

    def get_open_version(self, articulo_id: int) -> Version | None:
        row = self._conn.execute(
            """SELECT id, articulo_id, texto, vigente_desde, vigente_hasta, creada_por, reemplaza_a
               FROM version WHERE articulo_id = ? AND vigente_hasta IS NULL""",
            (articulo_id,),
        ).fetchone()
        if row is None:
            return None
        return Version(row[0], row[1], row[2], _d(row[3]), _d(row[4]), row[5], row[6])

    def get_detalle(self, version_id: int) -> VersionDetalle | None:
        row = self._conn.execute(_DETALLE_SELECT + " WHERE v.id = ?", (version_id,)).fetchone()
        return _detalle(row) if row else None

    def get_detalles(self, version_ids: Sequence[int]) -> list[VersionDetalle]:
        if not version_ids:
            return []
        rows = self._conn.execute(
            _DETALLE_SELECT + f" WHERE v.id IN ({_placeholders(len(version_ids))})", list(version_ids)
        ).fetchall()
        by_id = {r[0]: _detalle(r) for r in rows}
        return [by_id[i] for i in version_ids if i in by_id]

    def all_detalles(self) -> list[VersionDetalle]:
        return [_detalle(r) for r in self._conn.execute(_DETALLE_SELECT + " ORDER BY v.id").fetchall()]

    def version_en_fecha(self, norma_codigo: str, numero: str, fecha: date) -> VersionDetalle | None:
        row = self._conn.execute(
            _DETALLE_SELECT
            + f" WHERE n.codigo = :codigo AND a.numero = :numero AND {_VIGENTE_EN} AND {_NO_PROYECTO}"
            + " ORDER BY v.vigente_desde DESC LIMIT 1",
            {"codigo": norma_codigo, "numero": numero, "fecha": fecha.isoformat()},
        ).fetchone()
        return _detalle(row) if row else None

    def historial(self, norma_codigo: str, numero: str) -> list[VersionDetalle]:
        rows = self._conn.execute(
            _DETALLE_SELECT + " WHERE n.codigo = ? AND a.numero = ? ORDER BY v.vigente_desde, v.id",
            (norma_codigo, numero),
        ).fetchall()
        return [_detalle(r) for r in rows]

    def versiones_creadas_por(self, norma_codigo: str) -> list[VersionDetalle]:
        rows = self._conn.execute(
            _DETALLE_SELECT + " WHERE c.codigo = ? ORDER BY n.codigo, a.numero, v.vigente_desde",
            (norma_codigo,),
        ).fetchall()
        return [_detalle(r) for r in rows]

    def versiones_posteriores(self, version_id: int) -> list[VersionDetalle]:
        # Sigue la cadena reemplaza_a hacia adelante: v -> la que la reemplaza -> ...
        rows = self._conn.execute(
            """WITH RECURSIVE post(id, depth) AS (
                   SELECT id, 1 FROM version WHERE reemplaza_a = ?
                   UNION ALL
                   SELECT v.id, p.depth + 1 FROM version v JOIN post p ON v.reemplaza_a = p.id
               )
               SELECT id FROM post ORDER BY depth""",
            (version_id,),
        ).fetchall()
        return self.get_detalles([r[0] for r in rows])

    def filtrar_vigentes(
        self, version_ids: Sequence[int], fecha: date, incluir_proyectos: bool = False
    ) -> set[int]:
        if not version_ids:
            return set()
        params: dict[str, object] = {"fecha": fecha.isoformat()}
        params.update({f"id{i}": vid for i, vid in enumerate(version_ids)})
        in_list = ",".join(f":id{i}" for i in range(len(version_ids)))
        # Los proyectos no tienen vigencia real: si se piden, entran sin filtro de fecha.
        cond = f"({_VIGENTE_EN} AND {_NO_PROYECTO})"
        if incluir_proyectos:
            cond = f"({cond} OR c.estado = 'proyecto')"
        rows = self._conn.execute(
            f"""SELECT v.id FROM version v JOIN norma c ON c.id = v.creada_por
                WHERE v.id IN ({in_list}) AND {cond}""",
            params,
        ).fetchall()
        return {r[0] for r in rows}

    def info_citas(self, version_ids: Sequence[int], hoy: date) -> dict[int, InfoCita]:
        if not version_ids:
            return {}
        detalles = self.get_detalles(version_ids)
        ph = _placeholders(len(version_ids))
        posteriores = {
            r[0]
            for r in self._conn.execute(
                f"SELECT DISTINCT reemplaza_a FROM version WHERE reemplaza_a IN ({ph})", list(version_ids)
            ).fetchall()
        }
        # Version vigente HOY del mismo articulo de cada candidata.
        actuales = dict(
            self._conn.execute(
                f"""SELECT v0.id, (
                        SELECT v.id FROM version v JOIN norma c ON c.id = v.creada_por
                        WHERE v.articulo_id = v0.articulo_id AND {_VIGENTE_EN} AND {_NO_PROYECTO}
                        ORDER BY v.vigente_desde DESC LIMIT 1)
                    FROM version v0 WHERE v0.id IN ({",".join(f":id{i}" for i in range(len(version_ids)))})""",
                {"fecha": hoy.isoformat(), **{f"id{i}": vid for i, vid in enumerate(version_ids)}},
            ).fetchall()
        )
        return {
            d.version_id: InfoCita(d, d.version_id in posteriores, actuales.get(d.version_id))
            for d in detalles
        }
