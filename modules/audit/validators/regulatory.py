"""RegulatoryValidator (determinista).

Por cada evidencia existente de cada afirmacion:
  - norma creadora en estado 'proyecto'       -> CRITICO (no es derecho vigente)
  - no vigente en effective_date              -> CRITICO
  - vigente pero con versiones posteriores    -> WARN (+ version vigente actual)
Las evidencias inexistentes ya las reporta CitationValidator: aqui se omiten.
"""
from modules.audit.domain import AuditRequest, Finding, FindingStatus
from modules.audit.validators.interfaces import EvidenceSource, Validator
from modules.rag import EstadoNorma, VersionNoEncontrada


class RegulatoryValidator(Validator):
    name = "regulatory"

    def __init__(self, evidence: EvidenceSource):
        self.evidence = evidence

    def validate(self, request: AuditRequest) -> list[Finding]:
        fecha = request.effective_date
        out: list[Finding] = []
        for claim in request.candidate.claims:
            for vid in claim.evidence_ids:
                try:
                    v = self.evidence.get_version(vid)
                except VersionNoEncontrada:
                    continue
                ref = f"{v.norma_codigo} art. {v.articulo_numero} (v{vid})"
                base = {"version_id": vid, "norma": v.norma_codigo, "articulo": v.articulo_numero}

                if v.estado_norma_creadora == EstadoNorma.PROYECTO:
                    out.append(self._f(claim.claim_id, FindingStatus.FAIL,
                                       f"{ref} proviene de un PROYECTO ({v.creada_por_codigo}); no es normativa vigente",
                                       critical=True, details=base))
                    continue
                if not self.evidence.vigente_en(vid, fecha):
                    hasta = v.vigente_hasta.isoformat() if v.vigente_hasta else "-"
                    out.append(self._f(claim.claim_id, FindingStatus.FAIL,
                                       f"{ref} no estaba vigente el {fecha} (vigencia {v.vigente_desde} -> {hasta})",
                                       critical=True, details=base))
                    continue
                posteriores = self.evidence.versiones_posteriores(vid)
                if posteriores:
                    actual = posteriores[-1]
                    out.append(self._f(claim.claim_id, FindingStatus.WARN,
                                       f"{ref} vigente el {fecha}, pero fue modificada despues; "
                                       f"version mas reciente: v{actual.version_id} (desde {actual.vigente_desde})",
                                       details={**base, "latest_version_id": actual.version_id}))
                else:
                    out.append(self._f(claim.claim_id, FindingStatus.PASS,
                                       f"{ref} vigente el {fecha}", details=base))
        return out

    def _f(self, claim_id, status, reason, critical=False, details=None) -> Finding:
        return Finding(validator=self.name, claim_id=claim_id, status=status, critical=critical,
                       reason=reason, details=details or {})
