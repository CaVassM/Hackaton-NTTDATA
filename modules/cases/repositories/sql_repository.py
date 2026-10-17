"""SQLite de cases (cases.sqlite). SQL fijo y parametrizado."""
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from modules.cases.domain import CaseResult, QuestionResult
from modules.cases.domain.expediente import ExpedienteResult

_SCHEMA = Path(__file__).with_name("schema.sql")


class SqliteCasesRepository:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._lock = threading.Lock()

    @property
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30)
            conn.execute("PRAGMA journal_mode = WAL")
            self._local.conn = conn
        return conn

    def init_schema(self) -> None:
        self._conn.executescript(_SCHEMA.read_text(encoding="utf-8"))
        self._conn.commit()

    def save_case(self, r: CaseResult) -> None:
        decision = r.audit_result.decision.value if r.audit_result else None
        with self._lock:
            self._conn.execute(
                "INSERT INTO case_run (case_id, tipo_evento, decision, input_json, result_json, created_at) VALUES (?,?,?,?,?,?)",
                (r.case.case_id, r.case.tipo_evento, decision, r.case.model_dump_json(), r.model_dump_json(),
                 datetime.now(timezone.utc).isoformat()),
            )
            self._conn.commit()

    def get_case(self, case_id: str) -> CaseResult | None:
        row = self._conn.execute(
            "SELECT result_json FROM case_run WHERE case_id = ? ORDER BY id DESC LIMIT 1", (case_id,)).fetchone()
        return CaseResult.model_validate_json(row[0]) if row else None

    def list_cases(self, limit: int = 100) -> list[dict]:
        """Ultima evaluacion por case_id (resumen liviano)."""
        rows = self._conn.execute(
            """SELECT c.case_id, c.tipo_evento, c.decision, c.created_at FROM case_run c
               JOIN (SELECT case_id, MAX(id) AS id FROM case_run GROUP BY case_id) u ON u.id = c.id
               ORDER BY c.id DESC LIMIT ?""", (limit,)).fetchall()
        return [{"case_id": r[0], "tipo_evento": r[1], "decision": r[2], "evaluado_en": r[3]} for r in rows]

    def count(self) -> dict[str, int]:
        rows = self._conn.execute(
            """SELECT COALESCE(c.decision, 'SIN_AUDITORIA'), COUNT(*) FROM case_run c
               JOIN (SELECT case_id, MAX(id) AS id FROM case_run GROUP BY case_id) u ON u.id = c.id
               GROUP BY 1""").fetchall()
        return dict(rows)

    def save_question(self, r: QuestionResult) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO question_run (pregunta, decision, result_json, created_at) VALUES (?,?,?,?)",
                (r.pregunta, r.audit_result.decision.value if r.audit_result else None, r.model_dump_json(),
                 datetime.now(timezone.utc).isoformat()),
            )
            self._conn.commit()

    def save_expediente(self, r: ExpedienteResult) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO expediente_run (id_caso, resultado, decision, result_json, created_at) VALUES (?,?,?,?,?)",
                (r.fila["id_caso"], r.fila["resultado_esperado"], r.fila["decision_auditoria"], r.model_dump_json(),
                 datetime.now(timezone.utc).isoformat()),
            )
            self._conn.commit()

    def get_expediente(self, id_caso: str) -> ExpedienteResult | None:
        row = self._conn.execute(
            "SELECT result_json FROM expediente_run WHERE id_caso = ? ORDER BY id DESC LIMIT 1", (id_caso,)).fetchone()
        return ExpedienteResult.model_validate_json(row[0]) if row else None

    def list_expedientes(self, limit: int = 1000) -> list[dict]:
        """Ultima evaluacion por id_caso, en orden de importacion reciente."""
        rows = self._conn.execute(
            """SELECT e.id_caso, e.resultado, e.decision, e.created_at FROM expediente_run e
               JOIN (SELECT id_caso, MAX(id) AS id FROM expediente_run GROUP BY id_caso) u ON u.id = e.id
               ORDER BY e.id DESC LIMIT ?""", (limit,)).fetchall()
        return [{"id_caso": r[0], "resultado_esperado": r[1], "decision_auditoria": r[2], "evaluado_en": r[3]}
                for r in rows]

    def count_expedientes(self) -> dict[str, int]:
        rows = self._conn.execute(
            """SELECT e.resultado, COUNT(*) FROM expediente_run e
               JOIN (SELECT id_caso, MAX(id) AS id FROM expediente_run GROUP BY id_caso) u ON u.id = e.id
               GROUP BY 1""").fetchall()
        return dict(rows)
