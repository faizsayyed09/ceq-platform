from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from contracts.audit import AuditAttributeResult, AuditVerdict, ManagerReviewReason


@dataclass(frozen=True)
class AuditResult:
    verdict: AuditVerdict
    score_pct: float | None
    computed_pct: float | None
    target_pct: float
    attributes: tuple[AuditAttributeResult, ...] = ()
    critical_failures: tuple[str, ...] = ()
    potential_critical_failures: tuple[str, ...] = ()
    manager_review_required: bool = False
    manager_review_reasons: tuple[ManagerReviewReason | str, ...] = ()
    incomplete_attributes: tuple[str, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)
    mission_verdict: str = ""
    verdict_overridden: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "score_pct": self.score_pct,
            "computed_pct": self.computed_pct,
            "target_pct": self.target_pct,
            "attributes": [
                {
                    "key": item.key,
                    "label": item.label,
                    "weight": item.weight,
                    "result": item.result,
                    "points": item.points,
                    "missed": list(item.missed),
                    "unverified": list(item.unverified),
                    "justification": item.justification,
                    "evidence": [e.value for e in item.evidence],
                }
                for item in self.attributes
            ],
            "critical_failures": list(self.critical_failures),
            "potential_critical_failures": list(self.potential_critical_failures),
            "manager_review_required": self.manager_review_required,
            "manager_review_reasons": [str(reason.value if isinstance(reason, ManagerReviewReason) else reason) for reason in self.manager_review_reasons],
            "incomplete_attributes": list(self.incomplete_attributes),
            "evidence": dict(self.evidence),
            "mission_verdict": self.mission_verdict,
            "verdict_overridden": self.verdict_overridden,
        }
