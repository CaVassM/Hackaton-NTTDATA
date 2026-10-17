"""App de compliance:  uvicorn modules.compliance.api.app:app --port 8200

La fachada (con rag y el auditor compartiendo la misma instancia de rag) se
construye una vez en el lifespan.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from modules.compliance.api.router import ExtractionJobs, create_compliance_router
from modules.compliance.facade import ComplianceFacade
from shared.logging import configure_logging


def create_app(facade: ComplianceFacade | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.compliance_facade is None:
            configure_logging()
            from modules.audit import AuditFacade
            from modules.rag import RagFacade

            rag = RagFacade.from_settings()
            app.state.compliance_facade = ComplianceFacade.from_settings(rag=rag, auditor=AuditFacade.from_settings(rag=rag))
        yield

    app = FastAPI(title="Compliance LA/FT", version="0.1.0", lifespan=lifespan)
    app.state.compliance_facade = facade
    app.include_router(create_compliance_router(_get_facade, ExtractionJobs()))
    return app


def _get_facade(request: Request) -> ComplianceFacade:
    return request.app.state.compliance_facade


app = create_app()
