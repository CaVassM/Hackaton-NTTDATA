"""Servidor A2A 1.0 del auditor (binding JSON-RPC 2.0, metodo SendMessage).

No se usa el servidor del SDK (a2a-sdk[http-server]) porque arrastra
Starlette 1.x, incompatible con el FastAPI fijado en requirements. Se usa el
SDK para lo que define el protocolo: tipos, ruta well-known, codigos de error
y validacion estructural de SendMessageRequest (ParseDict).

Orden de controles (todos ANTES de evaluar):
  1. auth (401/403) - dependencia, corre antes de leer el cuerpo
  2. version A2A (-32009)
  3. JSON (-32700) -> sobre JSON-RPC (-32600) -> metodo (-32601)
  4. params = SendMessageRequest A2A (-32602)
  5. DataPart = AuditRequest (-32602)
"""
import json
import uuid
from collections.abc import Callable
from typing import Any

from a2a.types import Message, Part, Role, SendMessageRequest, SendMessageResponse
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, VERSION_HEADER
from a2a.utils.errors import (
    JSON_RPC_ERROR_CODE_MAP,
    InternalError,
    InvalidParamsError,
    InvalidRequestError,
    JSONParseError,
    MethodNotFoundError,
    VersionNotSupportedError,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from google.protobuf.json_format import MessageToDict, ParseDict, ParseError
from pydantic import ValidationError

from modules.audit.api.agent_card import A2A_RPC_PATH, AGENT_CARD_WELL_KNOWN_PATH, SKILL_ID
from modules.audit.api.auth import AuthError, ForbiddenAgent, TokenAuthenticator
from modules.audit.domain import AuditRequest
from modules.audit.facade import AuditFacade
from shared.logging import get_logger

log = get_logger(__name__)
SEND_MESSAGE = "SendMessage"


def _rpc_error(rpc_id: Any, error_cls: type, message: str, data: Any = None) -> JSONResponse:
    err = {"code": JSON_RPC_ERROR_CODE_MAP[error_cls], "message": message}
    if data is not None:
        err["data"] = data
    # JSON-RPC sobre HTTP: los errores de protocolo viajan con HTTP 200.
    return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "error": err})


def create_a2a_router(
    get_facade: Callable[..., AuditFacade],
    get_authenticator: Callable[..., TokenAuthenticator],
    get_card: Callable[..., dict[str, Any]],
) -> APIRouter:
    router = APIRouter(tags=["a2a"])

    def require_caller(request: Request, auth: TokenAuthenticator = Depends(get_authenticator)) -> str:
        try:
            agent_id = auth.authenticate(request.headers.get("authorization"))
            auth.authorize(agent_id)
        except AuthError as exc:
            log.warning("A2A 401 desde %s: %s", request.client.host if request.client else "?", exc)
            raise HTTPException(401, str(exc), headers={"WWW-Authenticate": "Bearer"}) from exc
        except ForbiddenAgent as exc:
            log.warning("A2A 403: %s", exc)
            raise HTTPException(403, str(exc)) from exc
        return agent_id

    @router.get(AGENT_CARD_WELL_KNOWN_PATH)
    def agent_card(card: dict = Depends(get_card)):
        # Publica: el descubrimiento no requiere token (la card declara como autenticarse).
        return JSONResponse(card)

    @router.post(A2A_RPC_PATH)
    async def rpc(
        request: Request,
        caller: str = Depends(require_caller),
        facade: AuditFacade = Depends(get_facade),
    ):
        version = request.headers.get(VERSION_HEADER)
        if version and version != PROTOCOL_VERSION_CURRENT:
            return _rpc_error(None, VersionNotSupportedError,
                              f"A2A-Version {version} no soportada; se soporta {PROTOCOL_VERSION_CURRENT}")

        try:
            body = json.loads(await request.body())
        except (ValueError, UnicodeDecodeError):
            return _rpc_error(None, JSONParseError, "Cuerpo no es JSON valido")

        rpc_id = body.get("id") if isinstance(body, dict) else None
        if (
            not isinstance(body, dict)
            or body.get("jsonrpc") != "2.0"
            or not isinstance(body.get("method"), str)
            or not isinstance(rpc_id, (str, int, type(None)))
        ):
            return _rpc_error(rpc_id, InvalidRequestError, "Sobre JSON-RPC 2.0 invalido")
        if body["method"] != SEND_MESSAGE:
            return _rpc_error(rpc_id, MethodNotFoundError, f"Metodo no soportado: {body['method']}")

        params = body.get("params")
        try:
            if not isinstance(params, dict):
                raise ParseError("params debe ser un objeto")
            send = ParseDict(params, SendMessageRequest())
        except ParseError as exc:
            return _rpc_error(rpc_id, InvalidParamsError, f"params no cumple SendMessageRequest (A2A 1.0): {exc}")

        # El AuditRequest se toma del JSON original (no del protobuf) para no
        # convertir enteros en float al pasar por google.protobuf.Value.
        data_parts = [p["data"] for p in params["message"].get("parts", []) if isinstance(p, dict) and "data" in p]
        if len(data_parts) != 1:
            return _rpc_error(rpc_id, InvalidParamsError,
                              f"Se espera exactamente 1 DataPart con el AuditRequest (llegaron {len(data_parts)})")
        try:
            audit_request = AuditRequest.model_validate(data_parts[0])
        except ValidationError as exc:
            return _rpc_error(rpc_id, InvalidParamsError, "DataPart no cumple el esquema AuditRequest",
                              data=json.loads(exc.json(include_url=False)))

        try:
            result = await run_in_threadpool(facade.evaluate, audit_request, requested_by=caller)
        except Exception:  # noqa: BLE001 - nunca filtrar trazas al otro agente
            log.exception("Fallo evaluando interaction %s", audit_request.interaction_id)
            return _rpc_error(rpc_id, InternalError, "Error interno del auditor")

        incoming = send.message
        reply = Message(
            message_id=str(uuid.uuid4()),
            context_id=incoming.context_id or audit_request.interaction_id,
            role=Role.ROLE_AGENT,
            parts=[
                Part(data={}, media_type="application/json"),
                Part(text=f"decision={result.decision} score={result.score} policy={result.policy_version}"),
            ],
        )
        reply.metadata.update({"skill": SKILL_ID, "audit_id": result.audit_id})
        out = MessageToDict(SendMessageResponse(message=reply))
        out["message"]["parts"][0]["data"] = result.model_dump(mode="json")
        return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": out})

    return router
