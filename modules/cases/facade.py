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
from modules.cases.repositories import SqliteCasesRepository
from modules.cases.services.case_service import CaseService
from modules.cases.services.eventos import CatalogoEventos
from modules.cases.services.question_service import QuestionService
from shared.logging import get_logger

if TYPE_CHECKING:
    from modules.cases.ports import AuditGateway

log = get_logger(__name__)
CSV_COLUMNAS = list(CaseInput.model_fields)


class CasesFacade:
    def __init__(self, *, settings: CasesSettings, cases: CaseService, questions: QuestionService,
                 catalogo: CatalogoEventos, repo: SqliteCasesRepository, audit: "AuditGateway"):
        self.settings = settings
        self._cases, self._questions, self.catalogo, self._repo, self._audit = cases, questions, catalogo, repo, audit

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

    def conteos(self) -> dict[str, int]:
        return self._repo.count()

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
            "notas": [
                "fecha_referencia es opcional: si se omite, el backend usa la fecha de hoy.",
                "fecha_cumplimiento vacia = pendiente.",
            ],
        }
