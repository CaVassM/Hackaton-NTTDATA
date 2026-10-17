"""Agent Card A2A del auditor.

Verificado contra a2a-sdk 1.2.2 (protocolo A2A 1.0):
  - ruta well-known: a2a.utils.constants.AGENT_CARD_WELL_KNOWN_PATH
    ("/.well-known/agent-card.json"; en 0.2.x era "/.well-known/agent.json")
  - binding JSON-RPC, metodo "SendMessage", header "A2A-Version"
Se construye con los tipos protobuf del SDK y se serializa con su mapeo JSON
oficial (camelCase), asi el formato lo garantiza el SDK y no este codigo.
"""
from typing import Any

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    HTTPAuthSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH, PROTOCOL_VERSION_CURRENT
from google.protobuf.json_format import MessageToDict

SKILL_ID = "audit_candidate_response"
A2A_RPC_PATH = "/a2a"
JSONRPC_BINDING = "JSONRPC"
BEARER = "bearer"

__all__ = ["A2A_RPC_PATH", "AGENT_CARD_WELL_KNOWN_PATH", "SKILL_ID", "build_agent_card", "card_to_json"]


def build_agent_card(public_url: str, policy_version: str, version: str = "0.1.0") -> AgentCard:
    base = public_url.rstrip("/")
    return AgentCard(
        name="auditor-normativo-aml",
        description=(
            "Servicio de aseguramiento: decide si una respuesta candidata de un copiloto "
            "normativo/AML puede publicarse (ALLOW|WARN|BLOCK|ESCALATE). Audita afirmacion por "
            f"afirmacion con controles deterministas sobre la normativa SBS. Politica: {policy_version}."
        ),
        version=version,
        supported_interfaces=[
            AgentInterface(
                url=base + A2A_RPC_PATH,
                protocol_binding=JSONRPC_BINDING,
                protocol_version=PROTOCOL_VERSION_CURRENT,
            )
        ],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        security_schemes={
            BEARER: SecurityScheme(
                http_auth_security_scheme=HTTPAuthSecurityScheme(
                    scheme="bearer",
                    description="Token local por agente (A2A_AGENT_TOKENS) + lista de agentes permitidos.",
                )
            )
        },
        security_requirements=[SecurityRequirement(schemes={BEARER: StringList()})],
        default_input_modes=["application/json"],
        default_output_modes=["application/json", "text/plain"],
        skills=[
            AgentSkill(
                id=SKILL_ID,
                name="Auditar respuesta candidata",
                description=(
                    "Recibe un AuditRequest como DataPart (interaction_id, user_id, role, query, "
                    "effective_date?, use_case, candidate{text, claims[{claim_id, text, "
                    "type: normativa|dato_caso|inferencia, evidence_ids[version_id]}]}) y devuelve "
                    "un AuditResult como DataPart: decision, score, findings por afirmacion, safe_response."
                ),
                tags=["audit", "aml", "compliance", "sbs", "guardrail"],
                examples=["Auditar: 'El plazo de atencion de reclamos es de 15 dias' citando la version 6"],
                input_modes=["application/json"],
                output_modes=["application/json"],
            )
        ],
    )


def card_to_json(card: AgentCard) -> dict[str, Any]:
    return MessageToDict(card)
