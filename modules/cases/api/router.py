"""Controladores delgados de cases.

/cases/schema se declara ANTES que /cases/{case_id}. Errores de contenido
(tipo_evento desconocido) salen como 422 con el mismo formato que los de
Pydantic, mas `valores_validos`.
"""
import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from fastapi.concurrency import run_in_threadpool

from modules.cases.domain import BatchItem, CaseInput, CaseNotFound, CaseResult, CaseValidationError, QuestionInput, QuestionResult
from modules.cases.domain.expediente import ExpedienteInput, ExpedienteResult
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

    # ------------------------------------------------- expedientes (formato del equipo)
    @router.post("/expedientes", response_model=ExpedienteResult)
    def expediente(body: ExpedienteInput, facade: CasesFacade = Depends(get_facade)):
        """Un expediente: id_caso + descripcion_caso. `fila` trae las columnas del CSV de resultados esperados."""
        return facade.analizar_expediente(body)

    @router.post("/expedientes/batch", openapi_extra={"requestBody": {"required": True, "content": {
        "multipart/form-data": {"schema": {"type": "object", "required": ["file"], "properties": {"file": {
            "type": "string", "format": "binary",
            "description": "CSV id_caso,descripcion_caso[,fecha_registro,fecha_limite_interna,fecha_atencion]"}}}},
        "application/json": {"schema": {"type": "array", "items": {"$ref": "#/components/schemas/ExpedienteInput"}}}}}})
    async def expedientes_batch(request: Request, formato: str = Query("json", pattern="^(json|csv)$"),
                                facade: CasesFacade = Depends(get_facade)):
        """Lote de expedientes. formato=csv devuelve un CSV con las columnas EXACTAS de resultados esperados."""
        ctype = request.headers.get("content-type", "")
        try:
            if ctype.startswith("multipart/form-data"):
                f = (await request.form()).get("file")
                if f is None or not hasattr(f, "read"):
                    raise HTTPException(422, [{"loc": ["body", "file"], "msg": "Falta el CSV en el campo 'file'", "type": "missing"}])
                filas = facade.parse_expedientes_csv((await f.read()).decode("utf-8-sig"))
            else:
                data = json.loads(await request.body() or b"null")
                filas = data if isinstance(data, list) else [data] if isinstance(data, dict) else None
                if filas is None:
                    raise ValueError("Se espera una lista JSON de expedientes o un CSV multipart")
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(422, [{"loc": ["body"], "msg": str(exc), "type": "value_error"}]) from exc
        if len(filas) > 1000:
            raise HTTPException(422, [{"loc": ["body"], "msg": "Maximo 1000 expedientes por lote", "type": "value_error"}])
        items = await run_in_threadpool(facade.expedientes_batch, filas)
        if formato == "csv":
            return PlainTextResponse(facade.expedientes_a_csv(items), media_type="text/csv; charset=utf-8",
                                     headers={"Content-Disposition": "attachment; filename=resultados_agente.csv"})
        return [{"id_caso": i["id_caso"], "ok": i["ok"], "error": i.get("error"),
                 "result": i["result"].model_dump(mode="json") if i["ok"] else None} for i in items]

    @router.get("/expedientes/{id_caso}", response_model=ExpedienteResult)
    def get_expediente(id_caso: str, facade: CasesFacade = Depends(get_facade)):
        try:
            return facade.get_expediente(id_caso)
        except CaseNotFound as exc:
            raise HTTPException(404, f"Expediente no encontrado: {id_caso}") from exc

    @router.get("/expedientes")
    def listar_expedientes(limit: int = Query(1000, ge=1, le=1000),
                           facade: CasesFacade = Depends(get_facade)) -> list[dict]:
        """Ultima evaluacion de cada expediente importado."""
        return facade.listar_expedientes(limit)

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
