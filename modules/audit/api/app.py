"""App del auditor como agente A2A:

    uvicorn modules.audit.api.app:app --port 8100

Expone la Agent Card en la ruta well-known y el endpoint JSON-RPC /a2a.
La fachada se construye UNA vez en el lifespan (carga rag + politica).
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from modules.audit.api.a2a_router import create_a2a_router
from modules.audit.api.agent_card import build_agent_card, card_to_json
from modules.audit.api.auth import TokenAuthenticator
from modules.audit.config import AuditSettings
from modules.audit.facade import AuditFacade
from shared.logging import configure_logging, get_logger

log = get_logger(__name__)


def create_app(facade: AuditFacade | None = None, settings: AuditSettings | None = None) -> FastAPI:
    settings = settings or AuditSettings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging(settings.log_level)
        if app.state.audit_facade is None:
            app.state.audit_facade = AuditFacade.from_settings(settings)
        app.state.authenticator = TokenAuthenticator(settings.a2a_agent_tokens, settings.a2a_allowed_agents)
        if not app.state.authenticator.enabled:
            log.warning("A2A_AGENT_TOKENS vacio: todas las peticiones seran rechazadas (401)")
        app.state.agent_card = card_to_json(
            build_agent_card(settings.a2a_public_url, app.state.audit_facade.policy_version)
        )
        yield

    app = FastAPI(title="Auditor normativo AML (A2A)", version="0.1.0", lifespan=lifespan)
    app.state.audit_facade = facade  # inyectable en tests

    app.include_router(create_a2a_router(_get_facade, _get_authenticator, _get_card))
    return app


# Anotadas con Request: FastAPI las resuelve como dependencias (una lambda no sirve).
def _get_facade(request: Request) -> AuditFacade:
    return request.app.state.audit_facade


def _get_authenticator(request: Request) -> TokenAuthenticator:
    return request.app.state.authenticator


def _get_card(request: Request) -> dict:
    return request.app.state.agent_card


app = create_app()
