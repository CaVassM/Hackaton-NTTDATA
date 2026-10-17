"""Controladores delgados de cases.

/cases/schema se declara ANTES que /cases/{case_id}. Errores de contenido
(tipo_evento desconocido) salen como 422 con el mismo formato que los de
Pydantic, mas `valores_validos`.
"""
import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool

from modules.cases.domain import BatchItem, CaseInput, CaseNotFound, CaseResult, CaseValidationError, QuestionInput, QuestionResult
from modules.cases.facade import CSV_COLUMNAS, CasesFacade

MAX_BATCH = 200

_EJEMPLO_BATCH = [CaseInput.model_config["json_schema_extra"]["examples"][0]]
_BATCH_OPENAPI = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {"schema": {"type": "array", "items": {"$ref": "#/components/schemas/CaseInput"}},
                                 "example": _EJEMPLO_BATCH},
            "multipart/form-data": {"schema": {"type": "object", "required": ["file"],
                                               "properties": {"file": {"type": "string", "format": "binary",
                                                                       "description": f"CSV con columnas {CSV_COLUMNAS}"}}}},
        },
    }
}


def _422(exc: CaseValidationError) -> HTTPException:
    return HTTPException(422, [{"loc": ["body", exc.field], "msg": str(exc), "type": "value_error",
                                "valores_validos": exc.valores_validos}])


def create_cases_router(get_facade: Callable[..., CasesFacade]) -> APIRouter:
    router = APIRouter(prefix="/cases", tags=["cases"])

    @router.get("/schema")
    def schema(facade: CasesFacade = Depends(get_facade)) -> dict[str, Any]:
        """JSON Schema de CaseInput + tipos de evento validos (para los equipos que envian casos)."""
        return facade.schema()

    @router.post("/evaluate", response_model=CaseResult)
    def evaluate(body: CaseInput, facade: CasesFacade = Depends(get_facade)):
        try:
            return facade.evaluate(body)
        except CaseValidationError as exc:
            raise _422(exc) from exc

    @router.post("/batch", response_model=list[BatchItem], openapi_extra=_BATCH_OPENAPI)
    async def batch(request: Request, facade: CasesFacade = Depends(get_facade)):
        """Lista JSON de CaseInput, o CSV subido como multipart (campo `file`). Un resultado por caso."""
        ctype = request.headers.get("content-type", "")
        try:
            if ctype.startswith("multipart/form-data"):
                form = await request.form()
                f = form.get("file")
                if f is None or not hasattr(f, "read"):
                    raise HTTPException(422, [{"loc": ["body", "file"], "msg": "Falta el archivo CSV en el campo 'file'",
                                               "type": "missing"}])
                casos = facade.parse_csv((await f.read()).decode("utf-8-sig"))
            else:
                data = json.loads(await request.body() or b"null")
                casos = data if isinstance(data, list) else [data] if isinstance(data, dict) else None
                if casos is None:
                    raise ValueError("Se espera una lista JSON de casos (o un objeto) o un CSV multipart")
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(422, [{"loc": ["body"], "msg": str(exc), "type": "value_error"}]) from exc
        if len(casos) > MAX_BATCH:
            raise HTTPException(422, [{"loc": ["body"], "msg": f"Maximo {MAX_BATCH} casos por lote", "type": "value_error"}])
        return await run_in_threadpool(facade.batch, casos)

    @router.post("/question", response_model=QuestionResult)
    def question(body: QuestionInput, facade: CasesFacade = Depends(get_facade)):
        return facade.question(body)

    @router.get("")
    def listar(limit: int = Query(100, ge=1, le=1000), facade: CasesFacade = Depends(get_facade)) -> list[dict]:
        """Ultima evaluacion de cada caso (case_id, tipo_evento, decision, fecha)."""
        return facade.listar(limit)

    @router.get("/{case_id}", response_model=CaseResult)
    def get(case_id: str, facade: CasesFacade = Depends(get_facade)):
        try:
            return facade.get(case_id)
        except CaseNotFound as exc:
            raise HTTPException(404, f"Caso no encontrado: {case_id}") from exc

    return router
