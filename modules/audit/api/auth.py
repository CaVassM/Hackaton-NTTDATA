"""Autenticacion (token -> agente) y autorizacion (lista de agentes permitidos).

Dos pasos separados a proposito:
  401 = no se quien eres (sin token / token desconocido)
  403 = se quien eres, pero no puedes pedir auditorias
Ambos ocurren ANTES de leer el cuerpo y, por tanto, antes de evaluar.
"""
import hmac
from collections.abc import Iterable, Mapping

from modules.audit.domain import AuditError


class AuthError(AuditError):
    status_code = 401


class ForbiddenAgent(AuditError):
    status_code = 403


class TokenAuthenticator:
    def __init__(self, agent_tokens: Mapping[str, str], allowed_agents: Iterable[str]):
        tokens = {agent: tok for agent, tok in agent_tokens.items() if tok}
        if len(set(tokens.values())) != len(tokens):
            raise ValueError("A2A_AGENT_TOKENS: dos agentes comparten token; la identidad seria ambigua")
        self._tokens = tokens
        self.allowed_agents = frozenset(allowed_agents)

    @property
    def enabled(self) -> bool:
        return bool(self._tokens)

    def authenticate(self, authorization: str | None) -> str:
        """Devuelve el agent_id dueno del token o lanza AuthError."""
        if not authorization:
            raise AuthError("Falta el header Authorization: Bearer <token>")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise AuthError("Esquema de autenticacion no soportado; se espera Bearer")
        token = token.strip()
        found = None
        # Se compara contra TODOS (sin salida temprana) con comparacion en tiempo constante.
        for agent, expected in self._tokens.items():
            if hmac.compare_digest(token.encode(), expected.encode()):
                found = agent
        if found is None:
            raise AuthError("Token invalido")
        return found

    def authorize(self, agent_id: str) -> None:
        if agent_id not in self.allowed_agents:
            raise ForbiddenAgent(f"El agente '{agent_id}' no esta autorizado para solicitar auditorias")
