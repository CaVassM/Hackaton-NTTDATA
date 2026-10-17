"""CasesFacade: la UNICA puerta del modulo cases.

    from modules.cases import CasesFacade
    cases = CasesFacade.from_settings()
    cases.evaluate({...CaseInput...})
"""
import csv
import io
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from modules.cases.config import CasesSettings
from modules.cases.domain import BatchItem, CaseInput, CaseNotFound, CaseResult, QuestionInput, QuestionResult
from modules.cases.domain.expediente import COLUMNAS_EXTRA, COLUMNAS_SALIDA, ExpedienteInput, ExpedienteResult
from modules.cases.repositories import SqliteCasesRepository
from modules.cases.services.case_service import CaseService
from modules.cases.services.eventos import CatalogoEventos
from modules.cases.services.expediente_service import ExpedienteService
from modules.cases.services.question_service import QuestionService
from shared.logging import get_logger

if TYPE_CHECKING:
    from modules.cases.ports import AuditGateway

log = get_logger(__name__)
CSV_COLUMNAS = list(CaseInput.model_fields)


class CasesFacade:
    def __init__(self, *, settings: CasesSettings, cases: CaseService, questions: QuestionService,
                 catalogo: CatalogoEventos, repo: SqliteCasesRepository, audit: "AuditGateway",
                 expedientes: ExpedienteService | None = None):
        self.settings = settings
        self._cases, self._questions, self.catalogo, self._repo, self._audit = cases, questions, catalogo, repo, audit
        self._expedientes = expedientes

    @classmethod
    def from_settings(cls, settings: CasesSettings | None = None, **kw: Any) -> "CasesFacade":
        from modules.cases.bootstrap import build_cases_facade

        return build_cases_facade(settings, **kw)

    @property
    def audit_mode(self) -> str:
        return self._audit.mode

    # ---------------------------------------------------------------- casos
    def evaluate(self, case: CaseInput | dict[str, Any]) -> CaseResult:
        """Lanza pydantic.ValidationError o CaseValidationError si la entrada no sirve."""
        inp = case if isinstance(case, CaseInput) else CaseInput.model_validate(case)
        self.catalogo.resolver(inp.tipo_evento)  # valida antes de trabajar
        result = self._cases.evaluate(inp)
        self._repo.save_case(result)
        return result

    def batch(self, casos: list[dict[str, Any]]) -> list[BatchItem]:
        """Un resultado por caso; un caso invalido no detiene el lote."""
        out = []
        for raw in casos:
            cid = raw.get("case_id") if isinstance(raw, dict) else None
            try:
                out.append(BatchItem(case_id=cid, ok=True, result=self.evaluate(raw)))
            except ValidationError as exc:
                msgs = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
                out.append(BatchItem(case_id=cid, ok=False, error=f"entrada invalida: {msgs}"))
            except Exception as exc:  # noqa: BLE001 - se reporta por caso
                out.append(BatchItem(case_id=cid, ok=False, error=f"{type(exc).__name__}: {exc}"))
        return out

    @staticmethod
    def parse_csv(text: str) -> list[dict[str, Any]]:
        """CSV con los campos de CaseInput (cabecera obligatoria). Vacio -> null."""
        reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
        faltan = [c for c in ("case_id", "user_id", "rol", "tipo_evento", "fecha_evento") if c not in (reader.fieldnames or [])]
        if faltan:
            raise ValueError(f"CSV sin columnas obligatorias {faltan}; columnas validas: {CSV_COLUMNAS}")
        filas = []
        for row in reader:
            fila = {k: (v.strip() if isinstance(v, str) and v.strip() else None) for k, v in row.items() if k}
            filas.append({k: v for k, v in fila.items() if v is not None})
        return filas

    def get(self, case_id: str) -> CaseResult:
        r = self._repo.get_case(case_id)
        if r is None:
            raise CaseNotFound(case_id)
        return r

    def listar(self, limit: int = 100) -> list[dict]:
        return self._repo.list_cases(limit)

    def conteos(self) -> dict[str, Any]:
        return {"casos": self._repo.count(), "expedientes": self._repo.count_expedientes()}

    # ----------------------------------------------------------- expedientes
    def analizar_expediente(self, exp: ExpedienteInput | dict[str, Any]) -> ExpedienteResult:
        """Formato del equipo: id_caso + descripcion_caso (+ fechas internas opcionales)."""
        if self._expedientes is None:
            raise CaseNotFound("analisis de expedientes no configurado")
        inp = exp if isinstance(exp, ExpedienteInput) else ExpedienteInput.model_validate(exp)
        r = self._expedientes.analizar(inp)
        self._repo.save_expediente(r)
        return r

    def expedientes_batch(self, filas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Un resultado por fila; una fila invalida no detiene el lote."""
        out = []
        for raw in filas:
            cid = raw.get("id_caso") if isinstance(raw, dict) else None
            try:
                out.append({"id_caso": cid, "ok": True, "result": self.analizar_expediente(raw)})
            except ValidationError as exc:
                msgs = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
                out.append({"id_caso": cid, "ok": False, "error": f"entrada invalida: {msgs}"})
            except Exception as exc:  # noqa: BLE001
                out.append({"id_caso": cid, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return out

    @staticmethod
    def parse_expedientes_csv(text: str) -> list[dict[str, Any]]:
        reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
        faltan = [c for c in ("id_caso", "descripcion_caso") if c not in (reader.fieldnames or [])]
        if faltan:
            raise ValueError(f"CSV sin columnas {faltan}; formato: id_caso,descripcion_caso "
                             "[,fecha_registro,fecha_limite_interna,fecha_atencion]")
        return [{k: v.strip() for k, v in row.items() if k and isinstance(v, str) and v.strip()} for row in reader]

    @staticmethod
    def expedientes_a_csv(items: list[dict[str, Any]]) -> str:
        """CSV con las columnas EXACTAS de resultados_esperados (+ columnas del agente al final)."""
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=COLUMNAS_SALIDA + COLUMNAS_EXTRA + ["error"], extrasaction="ignore")
        w.writeheader()
        for it in items:
            w.writerow(it["result"].as_row() if it["ok"] else {"id_caso": it["id_caso"], "error": it["error"]})
        return buf.getvalue()

    def get_expediente(self, id_caso: str) -> ExpedienteResult:
        r = self._repo.get_expediente(id_caso)
        if r is None:
            raise CaseNotFound(id_caso)
        return r

    # ------------------------------------------------------------- preguntas
    def question(self, q: QuestionInput | dict[str, Any]) -> QuestionResult:
        inp = q if isinstance(q, QuestionInput) else QuestionInput.model_validate(q)
        result = self._questions.ask(inp)
        self._repo.save_question(result)
        return result

    # ---------------------------------------------------------------- schema
    def schema(self) -> dict[str, Any]:
        return {
            "case_input": CaseInput.model_json_schema(),
            "tipos_evento": {t: {"categoria": e.categoria, "descripcion": e.descripcion,
                                 "fecha_evento_significa": e.fecha_evento, "obligaciones": list(e.obligaciones)}
                             for t, e in self.catalogo.eventos.items()},
            "roles": ["analista", "oficial_cumplimiento"],
            "monedas": ["PEN", "USD"],
            "csv_columnas": CSV_COLUMNAS,
            "expediente_input": ExpedienteInput.model_json_schema(),
            "expediente_columnas_salida": COLUMNAS_SALIDA,
            "expediente_columnas_extra": COLUMNAS_EXTRA,
            "notas": [
                "fecha_referencia es opcional: si se omite, el backend usa la fecha de hoy.",
                "fecha_cumplimiento vacia = pendiente.",
            ],
        }
