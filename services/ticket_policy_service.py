from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .fingerprint_service import FingerprintResult
from .ticket_matching_service import AMBIGUOUS, MATCHED, NO_EXPORT, NOT_FOUND, PENDING_EXPORT, PrematchResult


@dataclass(frozen=True)
class VerificationResult:
    matched_ticket: str
    match_status: str
    match_confidence: str
    basis: str
    notes: tuple[str, ...]
    facts: Mapping[str, Any] | None
    candidates: tuple[Mapping[str, Any], ...]
    export_error: str | None
    ticket: Mapping[str, Any]


@dataclass(frozen=True)
class KBQuery:
    issue_summary: str
    client: str = ""
    product: str = ""
    location: str = ""
    scope_rule: str = ""


class TicketPolicyService:
    LOCATION_RE = re.compile(
        r"^\s*(Department|Dept|Location|Device Location|Site calling from|Site|Ward calling from|Ward|Unit)\s*[:\-]+\s*(.+)$",
        re.IGNORECASE | re.MULTILINE,
    )

    @staticmethod
    def _json(raw: object) -> dict[str, Any]:
        text = str(raw or "")
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return {}
        try:
            value = json.loads(text[start:end + 1])
            return value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}

    @staticmethod
    def _get(row: Mapping[str, Any], *keys: str) -> str:
        lowered = {str(key).strip().lower(): value for key, value in row.items()}
        for key in keys:
            value = lowered.get(key.lower())
            if value not in (None, ""):
                return str(value)
        return ""

    def _from_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "ticket": {
                "number": self._get(row, "Number"),
                "type": self._get(row, "Type"),
                "opened_et": self._get(row, "Opened"),
                "opened_by": self._get(row, "Opened by"),
                "updated_et": self._get(row, "Updated", "Updated(u_updated_on)"),
                "updated_by": self._get(row, "Updated by", "Updated by(u_updated_by)"),
                "account": self._get(row, "Company"),
                "short_description": self._get(row, "Short description"),
                "contact_type": self._get(row, "Contact type"),
                "assignment_group": self._get(row, "Assignment group"),
                "priority": self._get(row, "Priority"),
                "state": self._get(row, "State"),
            },
            "ticket_notes": {
                "description_excerpt": self._get(row, "Description")[:1500],
                "work_notes_excerpt": self._get(row, "Work notes")[:1500],
                "additional_comments_excerpt": self._get(row, "Additional comments")[:1000],
            },
        }

    def verify(self, prematch: PrematchResult, external_proposal: object = None, documentation_checks: Mapping[str, Any] | None = None, fingerprint: FingerprintResult | None = None) -> VerificationResult:
        proposal = self._json(external_proposal)
        proposal_number = str(proposal.get("matched_ticket") or "").strip().upper()
        status = prematch.status or NO_EXPORT
        best = str(prematch.best_ticket or "").upper()
        rows = dict(prematch.candidate_rows)
        notes: list[str] = []

        if status in (NO_EXPORT, "SKIPPED"):
            final, basis = "", "mission only - export not available to code (unverified)"
            if proposal_number:
                notes.append("Mission proposed " + proposal_number + " but it could not be verified against the export")
        elif status == MATCHED:
            final, basis = best, "deterministic HIGH match"
            if proposal_number and proposal_number != best:
                notes.append("Mission proposed " + proposal_number + "; overridden by " + best)
        elif proposal_number and proposal_number in rows:
            final, basis = proposal_number, "mission chose among code candidates"
        else:
            final, basis = "", "no verifiable ticket"
            if proposal_number:
                notes.append("Mission proposed " + proposal_number + " - not a code candidate for this agent/window; rejected")

        ticket = dict(proposal)
        check_keys = list((proposal.get("documentation_checks") or {}).keys())
        if final and final != proposal_number and final in rows:
            ticket.update(self._from_row(rows[final]))
            ticket["documentation_checks"] = {key: "UNKNOWN" for key in check_keys}
            ticket["documentation_findings"] = []
            ticket["issueSummary"] = ""
            ticket["product"] = ""

        facts: Mapping[str, Any] | None = None
        for candidate in prematch.candidates:
            if candidate.number == final:
                facts = {
                    "opened_by_agent": candidate.facts.opened_by_agent,
                    "opened_in_window": candidate.facts.opened_in_window,
                    "agent_touched_in_window": candidate.facts.agent_touched_in_window,
                    "caller_name_in_ticket": candidate.facts.caller_name_in_ticket,
                    "caller_phone_in_ticket": candidate.facts.caller_phone_in_ticket,
                    "contact_type_matches_channel": candidate.facts.contact_type_matches_channel,
                    "kb_articles_in_ticket": candidate.facts.kb_articles_in_ticket,
                }
                break

        checks = dict(ticket.get("documentation_checks") if isinstance(ticket.get("documentation_checks"), dict) else documentation_checks or {})
        if facts and facts.get("caller_phone_in_ticket") is True:
            checks["contact_info_documented"] = "YES"
        if facts and "contact_type_matches_channel" in facts:
            checks["contact_type_matches_channel"] = "YES" if facts["contact_type_matches_channel"] else "NO"

        if final:
            ticket["matched_ticket"] = final
            ticket["match_status"] = MATCHED
            ticket["match_confidence"] = "HIGH" if status == MATCHED else proposal.get("match_confidence", "MEDIUM")
        else:
            ticket.update({"match_status": NOT_FOUND, "match_confidence": "LOW", "matched_ticket": "", "ticket": {}, "ticket_notes": {}, "documentation_findings": [], "issueSummary": ""})
            ticket["documentation_checks"] = {key: "UNKNOWN" for key in check_keys}

        ticket["documentation_checks"] = checks
        candidate_contracts = tuple({"number": candidate.number, "score": candidate.score} for candidate in prematch.candidates)
        ticket["verification"] = {"basis": basis, "notes": list(notes), "facts": facts or {}, "candidates": list(candidate_contracts), "prematch_status": prematch.status, "export_error": prematch.export_error}

        return VerificationResult(final, str(ticket["match_status"]), str(ticket["match_confidence"]), basis, tuple(notes), facts, candidate_contracts, prematch.export_error, ticket)

    def build_kb_query(self, verification: VerificationResult, fingerprint: FingerprintResult) -> KBQuery:
        issue_summary = str(verification.ticket.get("issueSummary") or fingerprint.issue_excerpt)
        location = ", ".join(fingerprint.location_statements)
        for label, value in self.LOCATION_RE.findall(fingerprint.interaction.clean_transcript):
            location = re.split(r"[.\n]", value.strip(), maxsplit=1)[0].strip()
            break
        if location == "" or location == ", ".join(fingerprint.location_statements) and fingerprint.location_statements:
            match = re.search(r"(?:Department|Dept|Location|Device Location|Site calling from|Site|Ward calling from|Ward|Unit)\s*[:\-]+\s*([^.\n]+)", fingerprint.interaction.clean_transcript, re.IGNORECASE)
            if match:
                location = match.group(1).strip()
        return KBQuery(issue_summary=issue_summary, location=location, product=str(verification.ticket.get("product") or ""), client="", scope_rule="Use verified ticket facts only; if no ticket is verified, do not scope against a ticket number.")
