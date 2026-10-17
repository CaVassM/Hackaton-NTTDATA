"""App FastAPI para levantar el modulo rag solo:

    uvicorn modules.rag.api.app:app --reload

La fachada se construye UNA vez al arrancar y se comparte via app.state. Una
app anfitriona (multi-modulo) haria lo mismo con `create_rag_router`.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from modules.rag.api.router import create_rag_router
from modules.rag.facade import RagFacade
from shared.logging import configure_logging


def _get_facade(request: Request) -> RagFacade:
    return request.app.state.rag_facade


def create_app(facade: RagFacade | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "rag_facade", None) is None:
            configure_logging()
            app.state.rag_facade = RagFacade.from_settings()
        yield

    app = FastAPI(title="RAG normativa SBS", version="0.1.0", lifespan=lifespan)
    app.state.rag_facade = facade  # inyectada en tests; si es None se crea al arrancar
    app.include_router(create_rag_router(_get_facade))
    return app


app = create_app()
