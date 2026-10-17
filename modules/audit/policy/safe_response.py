"""Respuesta segura. Nunca reescribe con LLM: compone desde la candidata y
los hallazgos.

  ALLOW     -> texto candidato tal cual
  WARN      -> texto candidato + advertencias
  BLOCK     -> solo afirmaciones verificadas (con cita) + lista de pendientes
  ESCALATE  -> igual que BLOCK + aviso de revision humana
"""
from modules.audit.domain import AuditRequest, Decision, Finding, FindingStatus


def _verificada(claim_id: str, findings: list[Finding]) -> bool:
    propios = [f for f in findings if f.claim_id == claim_id]
    # Verificada = al menos un PASS y ningun FAIL/WARN sobre ella.
    return bool(propios) and all(f.status == FindingStatus.PASS for f in propios)


def _cita(claim_id: str, findings: list[Finding]) -> str:
    refs = {
        f"{f.details['norma']}, art. {f.details['articulo']} (v{f.details['version_id']})"
        for f in findings
        if f.claim_id == claim_id and f.validator == "regulatory" and "norma" in f.details
    }
    return "; ".join(sorted(refs))


class SafeResponseBuilder:
    def build(self, request: AuditRequest, decision: Decision, findings: list[Finding]) -> str:
        if decision == Decision.ALLOW:
            return request.candidate.text
        if decision == Decision.WARN:
            avisos = [f"- {f.reason}" for f in findings if f.status == FindingStatus.WARN]
            return request.candidate.text + "\n\nAdvertencias:\n" + "\n".join(avisos)

        verificadas, pendientes = [], []
        for c in request.candidate.claims:
            if _verificada(c.claim_id, findings):
                verificadas.append(f"- {c.text} [{_cita(c.claim_id, findings) or 'sin cita'}]")
            else:
                motivos = "; ".join(f.reason for f in findings if f.claim_id == c.claim_id and f.status != FindingStatus.PASS)
                pendientes.append(f"- [{c.claim_id}] {c.text} -> {motivos or 'no verificada'}")

        partes = []
        if decision == Decision.ESCALATE:
            partes.append("Esta consulta requiere revision de un oficial de cumplimiento antes de cualquier accion.")
        else:
            partes.append("La respuesta no puede publicarse completa: contiene afirmaciones no verificadas.")
        partes.append("Afirmaciones verificadas:\n" + ("\n".join(verificadas) if verificadas else "- (ninguna)"))
        partes.append("Pendiente de verificacion:\n" + ("\n".join(pendientes) if pendientes else "- (nada)"))
        return "\n\n".join(partes)
