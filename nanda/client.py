"""Cliente A2A minimo para que otro agente (el copiloto) pida una auditoria.

    from nanda import AuditClient
    client = AuditClient.from_env()          # NANDA_AGENT_ID / NANDA_AGENT_TOKEN
    result = client.request_audit(audit_request_dict)
    if result["decision"] != "ALLOW": mostrar result["safe_response"]

Flujo: registro (capacidad -> URL) -> Agent Card (well-known) -> interfaz
JSONRPC 1.0 + skill -> SendMessage con Bearer -> AuditResult (DataPart).
No importa nada de modules/: habla con el auditor solo por el protocolo.
"""
import uuid
from pathlib import Path
from typing import Any

import httpx
from a2a.types import AgentCard, Message, Part, Role, SendMessageRequest, SendMessageResponse
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, VERSION_HEADER
from google.protobuf.json_format import MessageToDict, ParseDict, ParseError

from nanda.registry import AgentRecord, AgentRegistry
from shared.config import PROJECT_ROOT, BaseAppSettings

AUDIT_CAPABILITY = "audit_candidate_response"
DEFAULT_REGISTRY = PROJECT_ROOT / "nanda" / "registry.yaml"


class A2AClientError(Exception):
    def __init__(self, message: str, *, code: int | None = None, http_status: int | None = None, data: Any = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.data = data


class NandaSettings(BaseAppSettings):
    nanda_registry_path: Path = DEFAULT_REGISTRY
    nanda_agent_id: str = "copilot"
    nanda_agent_token: str = ""
    nanda_timeout_s: float = 30.0


class AuditClient:
    def __init__(
        self,
        *,
        token: str,
        registry: AgentRegistry,
        agent_id: str = "copilot",
        http: httpx.Client | None = None,
        timeout_s: float = 30.0,
    ):
        if not token:
            raise A2AClientError("Falta el token del agente (NANDA_AGENT_TOKEN)")
        self.agent_id = agent_id
        self._token = token
        self.registry = registry
        self._http = http or httpx.Client(timeout=timeout_s)
        self._cards: dict[str, dict[str, Any]] = {}

    @classmethod
    def from_env(cls, settings: NandaSettings | None = None, **kw: Any) -> "AuditClient":
        s = settings or NandaSettings()
        return cls(token=s.nanda_agent_token, registry=AgentRegistry(s.nanda_registry_path),
                   agent_id=s.nanda_agent_id, timeout_s=s.nanda_timeout_s, **kw)

    # ----------------------------------------------------------- descubrimiento
    def resolve_auditor(self, auditor_id: str | None = None) -> AgentRecord:
        if auditor_id:
            return self.registry.resolve(auditor_id)
        candidatos = self.registry.find_by_capability(AUDIT_CAPABILITY)
        if not candidatos:
            raise A2AClientError(f"Ningun agente registrado ofrece '{AUDIT_CAPABILITY}'")
        return candidatos[0]

    def fetch_card(self, record: AgentRecord) -> dict[str, Any]:
        if record.card_url not in self._cards:
            try:
                resp = self._http.get(record.card_url)
                resp.raise_for_status()
                card = resp.json()
                ParseDict(card, AgentCard())  # la card debe ser A2A valida
            except (httpx.HTTPError, ValueError, ParseError) as exc:
                raise A2AClientError(f"Agent Card invalida o inaccesible en {record.card_url}: {exc}") from exc
            self._cards[record.card_url] = card
        return self._cards[record.card_url]

    @staticmethod
    def _rpc_url(card: dict[str, Any]) -> str:
        if AUDIT_CAPABILITY not in {s.get("id") for s in card.get("skills", [])}:
            raise A2AClientError(f"La Agent Card no anuncia la skill '{AUDIT_CAPABILITY}'")
        for itf in card.get("supportedInterfaces", []):
            if itf.get("protocolBinding") == "JSONRPC" and itf.get("protocolVersion") == PROTOCOL_VERSION_CURRENT:
                return itf["url"]
        raise A2AClientError(f"El agente no ofrece JSONRPC A2A {PROTOCOL_VERSION_CURRENT}")

    # -------------------------------------------------------------- auditoria
    def request_audit(self, audit_request: dict[str, Any], *, auditor_id: str | None = None) -> dict[str, Any]:
        """Envia el AuditRequest y devuelve el AuditResult (dict). Lanza A2AClientError."""
        rpc_url = self._rpc_url(self.fetch_card(self.resolve_auditor(auditor_id)))

        msg = Message(
            message_id=str(uuid.uuid4()),
            context_id=str(audit_request.get("interaction_id", "")),
            role=Role.ROLE_USER,
            parts=[Part(data={}, media_type="application/json")],
        )
        msg.metadata.update({"skill": AUDIT_CAPABILITY, "from_agent": self.agent_id})
        params = MessageToDict(SendMessageRequest(message=msg))
        # El payload va tal cual (sin pasar por protobuf Value, que vuelve float los enteros).
        params["message"]["parts"][0]["data"] = audit_request
        body = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "SendMessage", "params": params}

        try:
            resp = self._http.post(rpc_url, json=body, headers={
                "Authorization": f"Bearer {self._token}",
                VERSION_HEADER: PROTOCOL_VERSION_CURRENT,
            })
        except httpx.HTTPError as exc:
            raise A2AClientError(f"No se pudo contactar al auditor en {rpc_url}: {exc}") from exc
        if resp.status_code in (401, 403):
            raise A2AClientError(resp.json().get("detail", resp.text), http_status=resp.status_code)
        if resp.status_code != 200:
            raise A2AClientError(f"HTTP {resp.status_code} del auditor", http_status=resp.status_code)

        payload = resp.json()
        if "error" in payload:
            e = payload["error"]
            raise A2AClientError(e.get("message", "error A2A"), code=e.get("code"), data=e.get("data"))
        try:
            ParseDict(payload["result"], SendMessageResponse())
            parts = payload["result"]["message"]["parts"]
            return next(p["data"] for p in parts if "data" in p)
        except (KeyError, StopIteration, ParseError) as exc:
            raise A2AClientError(f"Respuesta A2A sin AuditResult: {exc}") from exc
