"""Motor de decision. El ORDEN de las reglas es fijo y no configurable:
  1) hallazgo critico -> BLOCK (aunque el score sea 100)
  2) requires_human_approval -> ESCALATE
  3) score determinista contra umbrales -> ALLOW / WARN / BLOCK
Lo configurable (umbrales, pesos, patrones) vive en el YAML versionado.
"""
from dataclasses import dataclass
from pathlib import Path

import yaml

from modules.audit.domain import AuditRequest, Decision, Finding, PolicyError
from modules.audit.policy.score import deterministic_score

# De mas permisiva a mas restrictiva. Un techo nunca baja en esta escala.
_RESTRICCION = {Decision.ALLOW: 0, Decision.WARN: 1, Decision.ESCALATE: 2, Decision.BLOCK: 3}


@dataclass(frozen=True)
class Techo:
    """Decision maxima cuando el candidato cumple alguna condicion."""

    nombre: str
    max_decision: Decision
    motivo: str
    claim_types: frozenset[str]
    use_cases: frozenset[str]

    def aplica(self, request: AuditRequest) -> bool:
        return request.use_case in self.use_cases or any(
            c.type.value in self.claim_types for c in request.candidate.claims)


@dataclass(frozen=True)
class Policy:
    version: str
    allow_threshold: float
    warn_threshold: float
    weights: dict[str, float]
    warn_credit: float
    risk_levels: dict[str, str]
    sensitive_patterns: dict[str, str]
    techos: tuple[Techo, ...] = ()

    @classmethod
    def load(cls, path: Path) -> "Policy":
        try:
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
            p = cls(
                version=str(raw["policy_version"]),
                allow_threshold=float(raw["thresholds"]["allow"]),
                warn_threshold=float(raw["thresholds"]["warn"]),
                weights={k: float(v) for k, v in raw["weights"].items()},
                warn_credit=float(raw.get("warn_credit", 0.5)),
                risk_levels={k: str(v) for k, v in raw["risk_levels"].items()},
                sensitive_patterns={k: str(v) for k, v in raw.get("sensitive_patterns", {}).items()},
                techos=tuple(
                    Techo(nombre, Decision(t["max_decision"]), str(t.get("motivo", nombre)),
                          frozenset(t.get("claim_types", [])), frozenset(t.get("use_cases", [])))
                    for nombre, t in (raw.get("techos") or {}).items()
                ),
            )
        except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
            raise PolicyError(f"Politica invalida en {path}: {exc}") from exc
        if not p.warn_threshold <= p.allow_threshold:
            raise PolicyError("thresholds.warn debe ser <= thresholds.allow")
        if any(t.max_decision == Decision.ALLOW for t in p.techos):
            raise PolicyError("Un techo con max_decision=ALLOW no restringe nada")
        return p


@dataclass(frozen=True)
class DecisionOutcome:
    decision: Decision
    score: float
    risk_level: str
    reason: str
    partial_scores: dict[str, float]
    requires_human_approval: bool


class DecisionEngine:
    def __init__(self, policy: Policy):
        self.policy = policy

    def decide(self, findings: list[Finding], request: AuditRequest | None = None) -> DecisionOutcome:
        outcome = self._decide(findings)
        if request is None:
            return outcome
        # 4) Techos: solo pueden volver la decision MAS restrictiva (ALLOW -> WARN).
        for t in self.policy.techos:
            if t.aplica(request) and _RESTRICCION[outcome.decision] < _RESTRICCION[t.max_decision]:
                outcome = DecisionOutcome(
                    t.max_decision, outcome.score, self.policy.risk_levels.get(t.max_decision.value, "alto"),
                    f"{outcome.reason}; techo '{t.nombre}' -> {t.max_decision.value}: {t.motivo}",
                    outcome.partial_scores, outcome.requires_human_approval,
                )
        return outcome

    def _decide(self, findings: list[Finding]) -> DecisionOutcome:
        score, parciales = deterministic_score(findings, self.policy.weights, self.policy.warn_credit)
        human = any(f.requires_human_approval for f in findings)
        criticos = [f for f in findings if f.critical]

        if criticos:
            decision, reason = Decision.BLOCK, f"{len(criticos)} hallazgo(s) critico(s)"
        elif human:
            decision, reason = Decision.ESCALATE, "Consulta sensible: requiere aprobacion humana"
        elif score >= self.policy.allow_threshold:
            decision, reason = Decision.ALLOW, f"score {score} >= {self.policy.allow_threshold}"
        elif score >= self.policy.warn_threshold:
            decision, reason = Decision.WARN, f"score {score} >= {self.policy.warn_threshold}"
        else:
            decision, reason = Decision.BLOCK, f"score {score} < {self.policy.warn_threshold}"

        return DecisionOutcome(
            decision, score, self.policy.risk_levels.get(decision.value, "alto"), reason, parciales, human
        )
