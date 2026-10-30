from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from contracts.audit import AuditAttributeResult, AuditChannel, AuditVerdict, EvidenceItem, EvidenceStatus, ManagerReviewReason
from contracts.audit_payload import AuditPayload, AuditRequest
from contracts.audit_result import AuditResult
from modules.exceptions import ValidationError


ATTRIBUTE_SETS = {
    AuditChannel.CALL: (
        ("opening", "Opening", 5.0), ("empathy_accountability_ownership", "Empathy, Accountability & Ownership", 10.0),
        ("etiquette_professionalism", "Etiquette & Professionalism", 8.0), ("issue_identification", "Issue Identification", 8.0),
        ("troubleshooting_resolution", "Troubleshooting & Resolution", 12.0), ("process_adherence", "Process Adherence", 14.0),
        ("hold_wait", "Hold & Wait", 8.0), ("ticket_classification_escalation", "Ticket Classification & Escalation", 12.0),
        ("case_documentation", "Case Documentation", 18.0), ("closing", "Closing", 5.0),
    ),
    AuditChannel.EMAIL: (
        ("case_documentation", "Case Documentation", 19.0), ("ticket_classification", "Ticket Classification", 16.0),
        ("issue_identification_troubleshooting", "Issue Identification & Troubleshooting", 16.0), ("ticket_escalation", "Ticket Escalation", 16.0),
        ("resource_system_utilization", "Resource & System Utilization", 14.0), ("resolution", "Resolution", 14.0),
        ("etiquette_professionalism", "Etiquette & Professionalism", 5.0),
    ),
}


class AuditService:
    def __init__(self, pass_threshold: float = 96.0) -> None:
        self.pass_threshold = pass_threshold

    def build_payload(self, request: AuditRequest | Mapping[str, Any] | str, ticket: Mapping[str, Any] | None = None, knowledge: list[dict[str, Any]] | None = None) -> AuditPayload | dict[str, Any]:
        if isinstance(request, str):
            request = AuditRequest(interaction_text=request, ticket=ticket or {}, kb={"relevantArticles": knowledge or []})
        request = self._request(request)
        if not request.interaction_text.strip():
            raise ValidationError("Audit interaction text is required")
        if len(request.interaction_text) > 500_000:
            raise ValidationError("Transcript exceeds payload size limit")

        facts = ["=== VERIFIED FACTS (computed by code; treat as true) ==="]
        evidence: list[EvidenceItem] = []
        verification = request.ticket.get("verification") if isinstance(request.ticket.get("verification"), Mapping) else {}
        verified = verification.get("facts") if isinstance(verification.get("facts"), Mapping) else {}
        ticket_number = str(request.ticket.get("matched_ticket") or "")
        if ticket_number:
            basis = str(verification.get("basis") or request.ticket.get("match_confidence") or "")
            facts.append("ServiceNow record verified for this interaction: %s (%s)." % (ticket_number, basis))
            facts.append("Ticket timing was checked in US Eastern and is consistent; never raise ticket timing as an error.")
            evidence.append(EvidenceItem("servicenow", "ticket_verification", ticket_number, EvidenceStatus.VERIFIED))
        else:
            facts.append("No ServiceNow record could be verified. Case documentation is unverifiable and must be N/A; do not raise no ticket created.")
            evidence.append(EvidenceItem("servicenow", "ticket_verification", "not verified", EvidenceStatus.UNVERIFIED))
        if verified.get("caller_phone_in_ticket") is True:
            facts.append("The caller phone given in the interaction appears in the verified ticket.")
        elif verified.get("caller_phone_in_ticket") is False:
            facts.append("The caller phone given in the interaction does not appear in the exported ticket text.")
        cited = verified.get("kb_articles_in_ticket") or []
        if cited:
            facts.append("KB articles cited in the ticket by the agent: " + ", ".join(str(item) for item in cited) + ".")
        for number in request.prematch.get("tickets_mentioned") or []:
            facts.append("Ticket/case number stated during the interaction: " + str(number) + ".")
        for pause in request.prematch.get("caller_requested_pauses") or []:
            if isinstance(pause, Mapping):
                facts.append("At %s the caller asked the agent to wait ('%s'); this silence was caller-initiated, not agent dead air." % (pause.get("requested_at", "unknown"), pause.get("caller_said", "")))

        kb = self._policy_kb(request.kb, request.ticket)
        if not kb:
            facts.append("No KB procedure is available: procedure_adherence = NO_KB.")
        elif kb.get("enforceable") is True:
            facts.append("EXPECTED PROCEDURE is enforceable (" + str(kb.get("enforceable_reason") or "High confidence KB match") + ").")
        else:
            facts.append("EXPECTED PROCEDURE is advisory only (KB confidence %s): use it for coaching only, never as the basis for NOT_MET or critical failure." % str(kb.get("confidence") or "unknown"))

        text = "=== TICKET MATCH ===\n" + json.dumps(dict(request.ticket), ensure_ascii=False) + "\n\n=== EXPECTED PROCEDURE ===\n" + json.dumps(kb, ensure_ascii=False) + "\n\n" + "\n".join(facts) + "\n\n=== INTERACTION ===\n" + request.interaction_text
        payload = AuditPayload(text=text, verified_facts=tuple(facts), evidence=tuple(evidence), ticket=request.ticket, kb=kb, channel=request.channel)
        if not self.validate_payload(payload):
            raise ValidationError("Audit payload is incomplete")
        return payload

    def validate_payload(self, payload: AuditPayload) -> bool:
        return isinstance(payload, AuditPayload) and bool(payload.text.strip()) and bool(payload.verified_facts)

    def execute_audit(self, request: AuditRequest | Mapping[str, Any]) -> AuditResult:
        request = self._request(request)
        payload = self.build_payload(request)
        audit, parse_error = self._parse_ceq(request.ceq_response)
        return self.normalize_result(audit, parse_error, request)

    def calculate_score(self, audit_or_attributes: Mapping[str, Any] | AuditResult, channel: AuditChannel | str = AuditChannel.CALL, award_na_points: bool = False, ticket: Mapping[str, Any] | None = None) -> tuple[float | None, tuple[AuditAttributeResult, ...], tuple[str, ...]]:
        if isinstance(audit_or_attributes, AuditResult):
            return audit_or_attributes.computed_pct, audit_or_attributes.attributes, audit_or_attributes.incomplete_attributes
        channel = self._channel(channel)
        attrs = audit_or_attributes.get("attributes") if isinstance(audit_or_attributes, Mapping) else {}
        attrs = attrs if isinstance(attrs, Mapping) else {}
        earned = applicable = 0.0
        unknown: list[str] = []
        rows: list[AuditAttributeResult] = []
        ticket_verified = bool((ticket or {}).get("matched_ticket"))
        for key, label, weight in ATTRIBUTE_SETS[channel]:
            raw = attrs.get(key) if isinstance(attrs.get(key), Mapping) else {}
            result = self._normalize_result(raw.get("result") if raw else "UNKNOWN")
            if key == "case_documentation" and not ticket_verified:
                result = "NA"
            unverified = tuple(str(item) for item in (raw.get("unverified") or []) if item)
            if key == "case_documentation" and not ticket_verified:
                unverified = ("ServiceNow ticket documentation is unverifiable",)
            missed = tuple(str(item) for item in (raw.get("missed") or []) if item)
            evidence = tuple(EvidenceItem("ceq", key, str(item)) for item in (raw.get("evidence") or []) if item)
            if result == "UNKNOWN":
                unknown.append(label)
            points = weight if result == "MET" else (0.0 if result == "NOT_MET" else (weight if result == "NA" and award_na_points else None))
            if points is not None:
                applicable += weight
                earned += points
            rows.append(AuditAttributeResult(key=key, label=label, weight=weight, result=result, points=points, missed=missed, unverified=unverified, justification=str(raw.get("justification") or ""), evidence=evidence))
        score = round(earned / applicable * 100.0, 1) if applicable else None
        return score, tuple(rows), tuple(unknown)

    def determine_verdict(self, audit: Mapping[str, Any], score_pct: float | None, incomplete_attributes: Sequence[str], parse_error: str | None = None, target_pct: float | None = None) -> AuditVerdict:
        target = target_pct if target_pct is not None else self.pass_threshold
        if target <= 1:
            target *= 100
        if parse_error:
            return AuditVerdict.PARSE_ERROR
        if self._as_text_list(audit.get("critical_failures")):
            return AuditVerdict.CRITICAL_FAIL
        if incomplete_attributes or score_pct is None:
            return AuditVerdict.INCOMPLETE
        return AuditVerdict.ACHIEVED if score_pct >= target else AuditVerdict.NOT_ACHIEVED

    def determine_manager_review(self, audit: Mapping[str, Any], verdict: AuditVerdict, incomplete_attributes: Sequence[str], kb: Mapping[str, Any] | None = None, ticket: Mapping[str, Any] | None = None, parse_error: str | None = None) -> tuple[bool, tuple[ManagerReviewReason | str, ...]]:
        reasons: list[ManagerReviewReason | str] = []
        if self._as_text_list(audit.get("critical_failures")):
            reasons.append(ManagerReviewReason.CRITICAL_ERROR)
        if self._as_text_list(audit.get("potential_critical_failures")):
            reasons.append(ManagerReviewReason.POTENTIAL_CRITICAL_ERROR)
        if incomplete_attributes and not parse_error:
            reasons.append("Missing attribute results: " + ", ".join(incomplete_attributes))
        if audit.get("manager_review_required"):
            reasons.append(str(audit.get("manager_review_reason") or ManagerReviewReason.AUDIT_SERVICE_FLAG.value))
        if verdict in (AuditVerdict.PARSE_ERROR, AuditVerdict.INCOMPLETE):
            reasons.append(ManagerReviewReason.AUDIT_NOT_SCORABLE)
        adherence = str(audit.get("procedure_adherence") or "").upper()
        kb = kb or {}
        advisory_procedure_finding = bool(audit.get("advisory_procedure_finding")) or adherence in ("NOT_FOLLOWED", "PARTIAL") or any("procedure" in item.lower() or "kb" in item.lower() for item in self._as_text_list(audit.get("critical_failures")))
        if advisory_procedure_finding and kb.get("enforceable") is not True:
            reasons.append("Procedure finding based on %s-confidence KB match - verify the article applies" % str(kb.get("confidence") or "unknown").lower())
        verification = (ticket or {}).get("verification") if isinstance((ticket or {}).get("verification"), Mapping) else {}
        status = str(verification.get("prematch_status") or (ticket or {}).get("prematch_status") or (ticket or {}).get("match_status") or "")
        if status in ("PENDING_EXPORT", "NO_EXPORT"):
            reasons.append("Ticket not verifiable (" + status + ") - re-run after the next SNOW export")
        elif status == "NOT_FOUND":
            reasons.append(ManagerReviewReason.TICKET_NOT_MATCHED)
        unique = []
        for reason in reasons:
            if reason not in unique:
                unique.append(reason)
        return bool(unique), tuple(unique)

    def normalize_result(self, audit: Mapping[str, Any] | None, parse_error: str | None, request: AuditRequest | Mapping[str, Any]) -> AuditResult:
        request = self._request(request)
        audit = audit if isinstance(audit, Mapping) else {}
        channel = self._channel(audit.get("channel") or request.channel)
        score, attributes, incomplete = self.calculate_score(audit, channel, request.award_na_points, request.ticket)
        target = request.pass_threshold if request.pass_threshold is not None else self.pass_threshold
        if target <= 1:
            target *= 100
        kb = self._policy_kb(request.kb, request.ticket)
        critical = tuple(self._as_text_list(audit.get("critical_failures")))
        advisory_procedure = False
        if kb and kb.get("enforceable") is not True:
            advisory_procedure = any("procedure" in item.lower() or "kb" in item.lower() for item in critical)
            critical = tuple(item for item in critical if "procedure" not in item.lower() and "kb" not in item.lower())
        policy_audit = dict(audit)
        policy_audit["critical_failures"] = list(critical)
        policy_audit["advisory_procedure_finding"] = advisory_procedure
        verdict = self.determine_verdict(policy_audit, score, incomplete, parse_error, target)
        verification = request.ticket.get("verification") if isinstance(request.ticket.get("verification"), Mapping) else {}
        status = str(verification.get("prematch_status") or request.ticket.get("prematch_status") or "")
        if verdict in (AuditVerdict.ACHIEVED, AuditVerdict.NOT_ACHIEVED) and status in ("PENDING_EXPORT", "NO_EXPORT"):
            verdict = AuditVerdict.RETRY_LATER
        potential = tuple(self._as_text_list(audit.get("potential_critical_failures")))
        review_required, review_reasons = self.determine_manager_review(policy_audit, verdict, incomplete, kb, request.ticket, parse_error)
        mission_verdict = str(audit.get("verdict") or "").strip().upper()
        mission_score = self._float(audit.get("score_pct"))
        verdict_overridden = bool(mission_verdict and verdict not in (AuditVerdict.PARSE_ERROR, AuditVerdict.INCOMPLETE, AuditVerdict.RETRY_LATER) and mission_verdict != verdict.value)
        score_pct = 0.0 if verdict == AuditVerdict.CRITICAL_FAIL else score
        if verdict in (AuditVerdict.PARSE_ERROR, AuditVerdict.INCOMPLETE, AuditVerdict.RETRY_LATER):
            score_pct = score if verdict == AuditVerdict.RETRY_LATER else None
        return AuditResult(verdict=verdict, score_pct=score_pct, computed_pct=score, target_pct=target, attributes=attributes, critical_failures=critical, potential_critical_failures=potential, manager_review_required=review_required, manager_review_reasons=review_reasons, incomplete_attributes=incomplete, evidence={"kb": kb, "ticket": dict(request.ticket), "mission_score_pct": mission_score}, mission_verdict=mission_verdict, verdict_overridden=verdict_overridden)

    def parse_result(self, raw: str | Mapping[str, Any]) -> dict[str, Any]:
        audit, parse_error = self._parse_ceq(raw)
        request = AuditRequest(ceq_response=audit if not parse_error else raw if isinstance(raw, str) else "", interaction_text="Compatibility audit result")
        result = self.normalize_result(audit, parse_error, request).to_dict()
        legacy_score = audit.get("score") if isinstance(audit, Mapping) else None
        result["score"] = legacy_score if legacy_score is not None else result.get("score_pct")
        result["parsed"] = audit
        return result

    def _policy_kb(self, kb: Mapping[str, Any], ticket: Mapping[str, Any]) -> dict[str, Any]:
        if not kb:
            return {}
        policy = dict(kb)
        confidence = str(policy.get("confidence") or "").strip().upper()
        gap = bool(policy.get("kb_gap"))
        if confidence == "HIGH" and not gap:
            policy["enforceable"] = True
            return policy
        if gap:
            policy["enforceable"] = False
            policy["advisory_only"] = {"reason": "Knowledge base gap"}
            return policy
        policy["enforceable"] = False
        verification = ticket.get("verification") if isinstance(ticket.get("verification"), Mapping) else {}
        facts = verification.get("facts") if isinstance(verification.get("facts"), Mapping) else {}
        attached = {str(item).upper() for item in facts.get("kb_articles_in_ticket") or []}
        returned = set()
        for article in policy.get("relevantArticles") or policy.get("articles") or []:
            if isinstance(article, Mapping):
                value = article.get("id") or article.get("article_id")
                if value:
                    returned.add(str(value).upper())
            elif article:
                returned.add(str(article).upper())
        hits = sorted(attached.intersection(returned))
        if hits:
            policy["enforceable"] = True
            policy["enforceable_reason"] = "agent cited " + ", ".join(hits) + " in the ticket"
        return policy

    def _parse_ceq(self, value: str | Mapping[str, Any]) -> tuple[dict[str, Any], str | None]:
        if isinstance(value, Mapping):
            return dict(value), None
        raw = str(value or "").strip()
        if not raw:
            return {}, "Empty CEQ response."
        fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL | re.IGNORECASE)
        if fence:
            raw = fence.group(1)
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return {}, "No JSON object found in the response."
        try:
            parsed = json.loads(raw[start:end + 1])
            return parsed if isinstance(parsed, dict) else {}, "CEQ response was not a JSON object."
        except json.JSONDecodeError as exc:
            return {}, "Invalid CEQ JSON: " + str(exc)

    def _request(self, request: AuditRequest | Mapping[str, Any]) -> AuditRequest:
        if isinstance(request, AuditRequest):
            return request
        if isinstance(request, Mapping):
            return AuditRequest(interaction_text=str(request.get("interaction_text") or request.get("call_payload") or request.get("transcript") or ""), channel=self._channel(request.get("channel", "CALL")), ticket=request.get("ticket") if isinstance(request.get("ticket"), Mapping) else {}, kb=request.get("kb") if isinstance(request.get("kb"), Mapping) else {}, prematch=request.get("prematch") if isinstance(request.get("prematch"), Mapping) else {}, call_data=request.get("call_data") if isinstance(request.get("call_data"), Mapping) else {}, ceq_response=request.get("ceq_response", request.get("mission_response", "")), pass_threshold=self._float(request.get("pass_threshold"), self.pass_threshold), award_na_points=bool(request.get("award_na_points", request.get("award_na", False))))
        raise ValidationError("Audit request must be an AuditRequest or mapping")

    def _channel(self, channel: AuditChannel | str | None) -> AuditChannel:
        value = str(getattr(channel, "value", channel) or "CALL").upper()
        return AuditChannel.EMAIL if "EMAIL" in value else AuditChannel.CALL

    def _normalize_result(self, value: Any) -> str:
        normalized = re.sub(r"[^A-Z]", "", str(value or "").upper())
        if normalized in ("MET", "YES", "PASS", "TRUE", "ACHIEVED"):
            return "MET"
        if normalized in ("NOTMET", "NO", "FAIL", "FALSE", "MISSED", "NOTACHIEVED"):
            return "NOT_MET"
        if normalized in ("NA", "NOTAPPLICABLE"):
            return "NA"
        return "UNKNOWN"

    def _as_text_list(self, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        values = value if isinstance(value, list) else [value]
        output = []
        for item in values:
            if isinstance(item, Mapping):
                text = str(item.get("reason") or item.get("error") or item.get("evidence") or item.get("number") or "")
            else:
                text = str(item)
            if text.strip():
                output.append(text.strip())
        return output

    def _float(self, value: Any, default: float | None = None) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
