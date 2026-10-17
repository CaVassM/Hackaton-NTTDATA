"""Motor de decision. El ORDEN de las reglas es fijo y no configurable:
  1) hallazgo critico -> BLOCK (aunque el score sea 100)
  2) requires_human_approval -> ESCALATE
  3) score determinista contra umbrales -> ALLOW / WARN / BLOCK
Lo configurable (umbrales, pesos, patrones) vive en el YAML versionado.
"""
from dataclasses import dataclass
from pathlib import Path

import yaml

from modules.audit.domain import Decision, Finding, PolicyError
from modules.audit.policy.score import deterministic_score


@dataclass(frozen=True)
class Policy:
    version: str
    allow_threshold: float
    warn_threshold: float
    weights: dict[str, float]
    warn_credit: float
    risk_levels: dict[str, str]
    sensitive_patterns: dict[str, str]

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
            )
        except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
            raise PolicyError(f"Politica invalida en {path}: {exc}") from exc
        if not p.warn_threshold <= p.allow_threshold:
            raise PolicyError("thresholds.warn debe ser <= thresholds.allow")
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

    def decide(self, findings: list[Finding]) -> DecisionOutcome:
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
