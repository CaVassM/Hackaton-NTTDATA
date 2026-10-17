"""Demo: el copiloto pide auditorias al auditor A2A con el cliente nanda.

Requisitos: auditor corriendo (uvicorn modules.audit.api.app:app --port 8100),
ingesta hecha y NANDA_AGENT_TOKEN en .env igual al token de A2A_AGENT_TOKENS.

    python scripts/demo_audit_client.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nanda import A2AClientError, AuditClient  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEMO = Path(__file__).resolve().parent.parent / "modules" / "audit" / "examples" / "send_message_demo.json"

CORRECTA = {
    "interaction_id": "demo-ok-001",
    "user_id": "analista-01",
    "role": "analista",
    "query": "¿Cuál es el plazo para atender un reclamo?",
    "use_case": "consulta_normativa",
    "candidate": {
        "text": "El plazo máximo de atención es de 15 días calendario.",
        "claims": [{
            "claim_id": "c1",
            "text": "El plazo máximo de atención es de 15 días calendario.",
            "type": "normativa",
            "evidence_ids": [6],
        }],
    },
}


def mostrar(titulo: str, r: dict) -> None:
    print(f"\n=== {titulo}: {r['decision']} (score {r['score']}, {r['checks']['decision_reason']})")
    for f in r["findings"]:
        marca = " [CRITICO]" if f["critical"] else ""
        print(f"  - {f['validator']:<10} {f.get('claim_id') or '-':<4} {f['status']}{marca}: {f['reason']}")
    print("\nRespuesta segura:\n" + r["safe_response"])


def main() -> int:
    demo_uif = json.loads(DEMO.read_text(encoding="utf-8"))["params"]["message"]["parts"][0]["data"]
    try:
        client = AuditClient.from_env()
        mostrar("Respuesta correcta", client.request_audit(CORRECTA))
        mostrar("Caso demo UIF", client.request_audit(demo_uif))
    except A2AClientError as exc:
        print(f"ERROR ({exc.http_status or exc.code}): {exc}")
        print("Revisa: auditor corriendo en el puerto 8100, tokens del .env y que hiciste la ingesta.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
