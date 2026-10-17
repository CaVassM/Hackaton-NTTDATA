"""CitationValidator (determinista).

Por afirmacion:
  - cada evidence_id existe en rag; inexistente = CRITICO;
  - una afirmacion `normativa` sin evidencia = CRITICO;
  - montos, plazos y fechas de la afirmacion aparecen en el texto de su
    evidencia; una cifra ausente = CRITICO (es exactamente la alucinacion
    mas peligrosa: "24 horas" donde la norma dice otra cosa).
`dato_caso` e `inferencia` no se contrastan contra normativa: quedan WARN
(pendientes de verificacion), nunca PASS por defecto.
"""
from modules.audit.domain import AuditRequest, ClaimType, Finding, FindingStatus
from modules.audit.validators.facts import extract_facts
from modules.audit.validators.interfaces import EvidenceSource, Validator
from modules.rag import VersionNoEncontrada


class CitationValidator(Validator):
    name = "citation"

    def __init__(self, evidence: EvidenceSource):
        self.evidence = evidence

    def validate(self, request: AuditRequest) -> list[Finding]:
        out: list[Finding] = []
        for claim in request.candidate.claims:
            if claim.type != ClaimType.NORMATIVA and not claim.evidence_ids:
                out.append(self._f(claim.claim_id, FindingStatus.WARN,
                                   f"Afirmacion de tipo '{claim.type}' sin evidencia normativa: pendiente de verificacion"))
                continue
            if not claim.evidence_ids:
                out.append(self._f(claim.claim_id, FindingStatus.FAIL,
                                   "Afirmacion normativa sin evidencia citada", critical=True))
                continue

            textos, faltantes = [], []
            for vid in claim.evidence_ids:
                try:
                    textos.append(self.evidence.get_version(vid).texto)
                except VersionNoEncontrada:
                    faltantes.append(vid)
            if faltantes:
                out.append(self._f(claim.claim_id, FindingStatus.FAIL,
                                   f"Evidencia inexistente: version_id {faltantes}", critical=True,
                                   details={"missing_evidence_ids": faltantes}))
                continue

            esperadas = extract_facts(claim.text)
            presentes = set().union(*(extract_facts(t) for t in textos))
            ausentes = sorted(esperadas - presentes)
            if ausentes:
                out.append(self._f(claim.claim_id, FindingStatus.FAIL,
                                   f"Cifras no presentes en la evidencia: {', '.join(a.split(':', 1)[1] for a in ausentes)}",
                                   critical=True, details={"missing_facts": ausentes}))
            else:
                out.append(self._f(claim.claim_id, FindingStatus.PASS,
                                   f"Evidencia existente; {len(esperadas)} cifra(s) verificada(s)",
                                   details={"verified_facts": sorted(esperadas)}))
        return out

    def _f(self, claim_id, status, reason, critical=False, details=None) -> Finding:
        return Finding(validator=self.name, claim_id=claim_id, status=status, critical=critical,
                       reason=reason, details=details or {})
