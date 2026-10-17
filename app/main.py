"""Backend unificado: una sola app FastAPI que monta los routers de cada modulo.

    uvicorn app.main:app --port 8000          (o: python scripts/start_backend.py)

Todo se construye UNA vez en el lifespan y se comparte la misma instancia de
rag entre audit, compliance y cases. Sin logica de negocio aqui: solo
composicion, /health y manejo uniforme de errores.
"""
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.schemas import HealthOut
from modules.audit import AuditFacade, AuditSettings, create_audit_router
from modules.cases import CasesFacade, CasesSettings, create_cases_router
from modules.compliance import ComplianceFacade, ExtractionJobs, create_compliance_router
from modules.rag import RagFacade, create_rag_router
from shared.config import BaseAppSettings
from shared.llm import check_ollama
from shared.logging import configure_logging, get_logger

log = get_logger(__name__)
VERSION = "1.0.0"


class AppSettings(BaseAppSettings):
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    # Agente auditor A2A (proceso aparte, ver scripts/start_backend.py).
    nanda_enabled: bool = False
    a2a_public_url: str = "http://localhost:8100"
    frontend_allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@dataclass
class Container:
    rag: RagFacade
    audit: AuditFacade
    compliance: ComplianceFacade
    cases: CasesFacade
    settings: AppSettings


def build_container(settings: AppSettings | None = None) -> Container:
    settings = settings or AppSettings()
    rag = RagFacade.from_settings()
    audit = AuditFacade.from_settings(AuditSettings(), rag=rag)
    compliance = ComplianceFacade.from_settings(rag=rag, auditor=audit)
    cases = CasesFacade.from_settings(CasesSettings(), rag=rag, compliance=compliance, audit=audit)
    return Container(rag, audit, compliance, cases, settings)


def _dep(attr: str):
    def get(request: Request):
        return getattr(request.app.state.container, attr)

    return get


def health(c: Container) -> dict[str, Any]:
    s = c.settings
    rep = check_ollama(s.ollama_host, [s.llm_model, s.embed_model])
    rag_h = c.rag.health()["indices"]
    try:
        cadena = c.audit.verify_chain()
        audit_h = {**c.audit.counts(), "cadena_ok": cadena.ok, "cadena_motivo": cadena.motivo}
    except Exception as exc:  # noqa: BLE001 - /health nunca debe caer
        audit_h = {"error": str(exc)}
    nanda = {"enabled": s.nanda_enabled, "agent_card": None, "reachable": None}
    if s.nanda_enabled:
        url = s.a2a_public_url.rstrip("/") + "/.well-known/agent-card.json"
        nanda["agent_card"] = url
        try:
            nanda["reachable"] = httpx.get(url, timeout=2).status_code == 200
        except httpx.HTTPError:
            nanda["reachable"] = False
    bases_ok = rag_h["versiones_sql"] > 0 and audit_h.get("cadena_ok", False)
    return {
        "status": "ok" if rep.ok and bases_ok else "degradado",
        "version": VERSION,
        "ollama": {"host": rep.host, "reachable": rep.reachable, "models": rep.models, "error": rep.error},
        "modelos": {"llm": s.llm_model, "embeddings": s.embed_model},
        "bases": {
            "rag": rag_h,
            "compliance": c.compliance.conteos(),
            "audit": audit_h,
            "cases": c.cases.conteos(),
        },
        "audit_mode": c.cases.audit_mode,
        "policy_version": c.audit.policy_version,
        "nanda": nanda,
    }


def create_app(container: Container | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.container is None:
            configure_logging()
            log.info("Construyendo modulos (rag, audit, compliance, cases)...")
            app.state.container = build_container()
            log.info("Backend listo")
        yield

    app = FastAPI(
        title="Hackaton NTTDATA - Backend de cumplimiento LA/FT",
        version=VERSION,
        description="RAG temporal SBS, auditor de respuestas, obligaciones/plazos/exposicion y evaluacion de casos. "
                    "Todo local (Ollama). Datos de demo: ver /cases/schema y docs/CASOS.md.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=(container.settings.frontend_allowed_origins if container else AppSettings().frontend_allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.state.container = container

    @app.exception_handler(Exception)
    async def _sin_500_vacio(request: Request, exc: Exception):  # noqa: ARG001
        log.exception("Error no controlado en %s", request.url.path)
        return JSONResponse(status_code=500, content={"error": type(exc).__name__, "detail": str(exc)[:500]})

    @app.get("/health", response_model=HealthOut, tags=["salud"])
    def get_health(request: Request):
        """Ollama, modelos, cada base y conteos (versiones, propuestas validadas, auditorias, casos)."""
        return health(request.app.state.container)

    app.include_router(create_rag_router(_dep("rag")))
    app.include_router(create_audit_router(_dep("audit")))
    app.include_router(create_compliance_router(_dep("compliance"), ExtractionJobs()))
    app.include_router(create_cases_router(_dep("cases")))
    return app


app = create_app()
