"""SensitiveQueryDetector (reglas). La IA no decide un ROS ni medidas
restrictivas: si la consulta o una afirmacion los toca, se exige aprobacion
humana. No participa en el score: tiene su propia regla en el motor."""
import re

from modules.audit.domain import AuditRequest, Finding, FindingStatus
from modules.audit.validators.facts import normalize
from modules.audit.validators.interfaces import Validator


class SensitiveQueryDetector(Validator):
    name = "sensitive"
    scored = False

    def __init__(self, patterns: dict[str, str]):
        self.patterns = {k: re.compile(p) for k, p in patterns.items()}

    def validate(self, request: AuditRequest) -> list[Finding]:
        textos = [(None, request.query)] + [(c.claim_id, c.text) for c in request.candidate.claims]
        hits: dict[str, list[str]] = {}
        for claim_id, texto in textos:
            norm = normalize(texto)
            for regla, rx in self.patterns.items():
                if rx.search(norm):
                    hits.setdefault(regla, []).append(claim_id or "query")
        if not hits:
            return []
        return [
            Finding(
                validator=self.name,
                status=FindingStatus.WARN,
                reason=f"Tema sensible ({', '.join(sorted(hits))}): requiere aprobacion humana",
                requires_human_approval=True,
                details={"rules": hits},
            )
        ]
