"""Controladores delgados de compliance. La extraccion (LLM, minutos) corre en
background y se consulta por job_id; el resto es sincrono (threadpool)."""
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.encoders import jsonable_encoder

from modules.compliance.api.schemas import ExtractRequest, ReportRequest, ReviewRequest
from modules.compliance.domain import ComplianceError, EstadoPropuesta, PropuestaNoEncontrada, TipoPropuesta
from modules.compliance.facade import ComplianceFacade
from shared.logging import get_logger

log = get_logger(__name__)


class ExtractionJobs:
    """Registro en memoria de extracciones en background (una a la vez: una sola GPU)."""

    def __init__(self):
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(self, tipo: str, categorias) -> dict[str, Any]:
        with self._lock:
            if any(j["estado"] == "corriendo" for j in self._jobs.values()):
                raise HTTPException(409, "Ya hay una extraccion en curso")
            job = {"job_id": uuid.uuid4().hex[:12], "tipo": tipo, "categorias": categorias, "estado": "corriendo",
                   "progreso": None, "inicio": datetime.now(timezone.utc).isoformat(), "resultado": None, "error": None}
            self._jobs[job["job_id"]] = job
            return job

    def get(self, job_id: str) -> dict[str, Any]:
        if job_id not in self._jobs:
            raise HTTPException(404, f"job {job_id} no existe")
        return self._jobs[job_id]


def _run(facade: ComplianceFacade, job: dict, req: ExtractRequest) -> None:
    def progress(i, total, label):
        job["progreso"] = {"hechos": i, "total": total, "actual": label}

    try:
        res = []
        if req.tipo in ("obligaciones", "todo"):
            res.append(asdict(facade.extract_obligations(req.categorias, req.fecha, progress)))
        if req.tipo in ("infracciones", "todo"):
            res.append(asdict(facade.extract_infractions(req.categorias, req.fecha, progress)))
        job.update(estado="terminado", resultado=res)
    except Exception as exc:  # noqa: BLE001 - el job reporta el fallo, no tumba la API
        log.exception("Extraccion %s fallo", job["job_id"])
        job.update(estado="error", error=f"{type(exc).__name__}: {exc}")


def create_compliance_router(get_facade: Callable[..., ComplianceFacade], jobs: ExtractionJobs) -> APIRouter:
    router = APIRouter(prefix="/compliance", tags=["compliance"])

    @router.post("/extract", status_code=202)
    def extract(body: ExtractRequest, background: BackgroundTasks, facade: ComplianceFacade = Depends(get_facade)):
        try:
            facade.categorias_validas(body.categorias)
        except ComplianceError as exc:
            raise HTTPException(400, str(exc)) from exc
        job = jobs.start(body.tipo, body.categorias)
        background.add_task(_run, facade, job, body)
        return job

    @router.get("/extract/{job_id}")
    def extract_status(job_id: str):
        return jobs.get(job_id)

    @router.get("/proposals")
    def proposals(tipo: TipoPropuesta | None = None, estado: EstadoPropuesta | None = EstadoPropuesta.PROPUESTA,
                  facade: ComplianceFacade = Depends(get_facade)):
        res = facade.proposals(tipo, estado)
        return jsonable_encoder({k: [{"proposal_id": x.proposal_id, **asdict(x)} for x in v] for k, v in res.items()})

    @router.post("/proposals/{proposal_id}/review")
    def review(proposal_id: str, body: ReviewRequest, facade: ComplianceFacade = Depends(get_facade)):
        try:
            facade.review(proposal_id, body.aprobar, body.revisor, body.comentario)
        except PropuestaNoEncontrada as exc:
            raise HTTPException(404, str(exc)) from exc
        except ComplianceError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"proposal_id": proposal_id, "estado": "validada" if body.aprobar else "rechazada", "revisor": body.revisor}

    @router.post("/report")
    def report(body: ReportRequest, facade: ComplianceFacade = Depends(get_facade)):
        try:
            rep, audit = facade.report(body.fecha_corte, body.categorias, auditar=body.auditar)
        except ComplianceError as exc:
            raise HTTPException(400, str(exc)) from exc
        return jsonable_encoder({"reporte": asdict(rep),
                                 "auditoria": audit.model_dump(mode="json") if audit is not None else None})

    return router
