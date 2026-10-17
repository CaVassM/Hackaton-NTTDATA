"""Score determinista 0-100 a partir de los hallazgos de validadores puntuables."""
from collections.abc import Iterable, Mapping

from modules.audit.domain import Finding, FindingStatus


def validator_score(findings: Iterable[Finding], warn_credit: float) -> float:
    """Fraccion 0-1 de un validador. Sin hallazgos = nada que objetar = 1."""
    vals = [1.0 if f.status == FindingStatus.PASS else warn_credit if f.status == FindingStatus.WARN else 0.0
            for f in findings]
    return sum(vals) / len(vals) if vals else 1.0


def deterministic_score(
    findings: Iterable[Finding], weights: Mapping[str, float], warn_credit: float
) -> tuple[float, dict[str, float]]:
    """Media ponderada (pesos de la politica). Devuelve (score, parcial por validador)."""
    findings = list(findings)
    parciales = {
        name: validator_score([f for f in findings if f.validator == name], warn_credit) for name in weights
    }
    total_w = sum(weights.values()) or 1.0
    score = 100 * sum(weights[n] * parciales[n] for n in weights) / total_w
    return round(score, 2), {n: round(100 * s, 2) for n, s in parciales.items()}
