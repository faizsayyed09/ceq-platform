from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any


class CutoverGateService:
    """Repository-side shadow evidence and retirement eligibility; no live retirement."""

    RETIREMENT_COMPONENTS = (
        "matcha_snow_prematch",
        "azure_report_json_path",
        "azure_workflow_orchestrator",
        "azure_dispatcher",
        "azure_ticket_matching_api",
        "azure_knowledge_providers",
        "mission_47043",
    )

    def compare(
        self,
        *,
        matcha_status: object,
        azure_status: object,
        matcha_top_ticket: object = None,
        azure_top_ticket: object = None,
        matcha_score: object = None,
        azure_score: object = None,
    ) -> dict[str, object]:
        matcha_ticket = str(matcha_top_ticket or "")
        azure_ticket = str(azure_top_ticket or "")
        if str(matcha_status or "") == str(azure_status or "") and matcha_ticket == azure_ticket:
            disagreement = "same"
        elif not matcha_ticket and azure_ticket:
            disagreement = "azure_only"
        elif matcha_ticket and not azure_ticket:
            disagreement = "matcha_only"
        elif matcha_ticket != azure_ticket:
            disagreement = "different_tickets"
        else:
            disagreement = "other"
        return {
            "disagreement_class": disagreement,
            "matcha": {
                "status": str(matcha_status or ""),
                "top_ticket": matcha_ticket,
                "score": matcha_score,
            },
            "azure": {
                "status": str(azure_status or ""),
                "top_ticket": azure_ticket,
                "score": azure_score,
            },
        }

    def evaluate(
        self,
        cases: Iterable[Mapping[str, Any]],
        *,
        phi_samples_checked: bool = False,
        rollback_tested: bool = False,
    ) -> dict[str, object]:
        rows = [dict(case) for case in cases]
        disagreement_counts = Counter(
            str(row.get("disagreement_class") or "unclassified")
            for row in rows
            if str(row.get("disagreement_class") or "") != "same"
        )
        explained = all(
            bool(row.get("disagreement_class") == "same" or row.get("explained") and row.get("label"))
            for row in rows
        )
        labelled = bool(rows) and all(bool(row.get("label")) for row in rows)
        same = sum(1 for row in rows if row.get("disagreement_class") == "same")
        gate_checks = {
            "labelled_corpus_present": labelled,
            "every_disagreement_explained": explained,
            "zero_phi_in_sampled_candidates": phi_samples_checked,
            "rollback_switch_tested": rollback_tested,
        }
        passed = all(gate_checks.values())
        return {
            "mode": "azure" if passed else "shadow",
            "safe_repository_mode": "shadow",
            "rollback_mode": "matcha",
            "gate_passed": passed,
            "gate_checks": gate_checks,
            "shadow_case_count": len(rows),
            "same_case_count": same,
            "disagreement_counts": dict(sorted(disagreement_counts.items())),
            "retirement": [
                {
                    "component": component,
                    "eligible": False,
                    "reason": "Cutover gate not passed and live labelled/parity evidence is unavailable" if not passed else "Gate passed; preserve the agreed post-cutover retention period",
                }
                for component in self.RETIREMENT_COMPONENTS
            ],
        }
