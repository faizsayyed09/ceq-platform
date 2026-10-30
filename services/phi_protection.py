from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from modules.exceptions import SecurityError, ValidationError


class PhiProtectionMode(str, Enum):
    OFF = "OFF"
    AUDIT_MODE = "AUDIT_MODE"
    LLM_MODE = "LLM_MODE"
    STRICT = "STRICT"


@dataclass(frozen=True)
class PhiFinding:
    category: str
    value: str
    start: int
    end: int


_PATTERNS: tuple[tuple[str, re.Pattern[str]]] = (
    ("ssn", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")),
    ("mrn", re.compile(r"(?i)\b(?:MRN|medical record(?:\s+number)?|patient\s+(?:id|account)\s*(?:number)?|member\s+(?:id|number))\b\s*[:#]?\s*[A-Z0-9-]{4,20}")),
    ("patient_account", re.compile(r"(?i)\b(?:patient\s+account(?:\s+number)?|billing\s+account(?:\s+number)?|hospital\s+account(?:\s+number)?|guarantor\s+(?:id|number))\b\s*[:#]?\s*[A-Z0-9-]{4,20}")),
    ("encounter", re.compile(r"(?i)\b(?:FIN|encounter(?:\s+number|\s+id)?|admission\s+(?:id|number)|visit\s+(?:id|number)|health\s+plan|insurance\s+(?:id|number)|member\s+(?:id|number))\b\s*[:#]?\s*[A-Z0-9-]{4,20}")),
    ("dob", re.compile(r"(?i)\b(?:date\s+of\s+birth|D\.?O\.?B\.?)\b\s*[:#]?\s*(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|[A-Z][a-z]+\s+\d{1,2},?\s+\d{4})")),
    ("patient_name", re.compile(r"(?i)\bpatient(?:'s)?(?:\s+name|\s+named|\s+called|\s+is)?\s*[:#-]?\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?")),
    ("clinical_detail", re.compile(r"(?i)\b(?:diagnosis|diagnosed with|medication|dosage|prescription|lab results?|test results?|allergy|allergies|surgery|admitted|discharged|treatment plan|insulin|chemotherapy|pregnancy|HIV|cancer|overdose|psychiatric)\b[^.!?]{0,160}")),
)


class PhiProtectionService:
    """Detects patient PHI and creates destination-specific projections."""

    def __init__(self, default_mode: str | PhiProtectionMode = PhiProtectionMode.AUDIT_MODE) -> None:
        self.default_mode = self.normalize_mode(default_mode)

    @staticmethod
    def normalize_mode(mode: str | PhiProtectionMode) -> PhiProtectionMode:
        value = mode.value if isinstance(mode, PhiProtectionMode) else str(mode).strip().upper()
        try:
            return PhiProtectionMode(value)
        except ValueError as exc:
            raise ValidationError("Invalid PHI protection mode") from exc

    def detect(self, text: str) -> list[PhiFinding]:
        if not isinstance(text, str):
            raise ValidationError("PHI detection input must be text")
        findings: list[PhiFinding] = []
        for category, pattern in _PATTERNS:
            for match in pattern.finditer(text):
                findings.append(PhiFinding(category=category, value=match.group(0), start=match.start(), end=match.end()))
        return sorted(findings, key=lambda item: (item.start, item.category))

    def project(self, text: str, mode: str | PhiProtectionMode | None = None) -> dict[str, object]:
        selected = self.normalize_mode(mode) if mode is not None else self.default_mode
        if selected == PhiProtectionMode.OFF:
            return {"text": text, "mode": selected.value, "findings": [], "blocked": False}

        findings = self.detect(text)
        categories = sorted({finding.category for finding in findings})
        if selected == PhiProtectionMode.STRICT and findings:
            raise SecurityError("PHI detected; operation blocked by STRICT protection mode")

        projected = text
        if selected == PhiProtectionMode.LLM_MODE:
            for finding in reversed(findings):
                marker = f"[PHI_{finding.category.upper()}]"
                projected = projected[:finding.start] + marker + projected[finding.end:]

        return {
            "text": projected,
            "mode": selected.value,
            "findings": [{"category": finding.category, "start": finding.start, "end": finding.end} for finding in findings],
            "blocked": False,
            "phi_categories": categories,
        }

    def project_segments(self, segments: Iterable[dict[str, object]], mode: str | PhiProtectionMode | None = None) -> dict[str, object]:
        selected = self.normalize_mode(mode) if mode is not None else self.default_mode
        canonical_segments: list[dict[str, object]] = []
        protected_segments: list[dict[str, object]] = []
        all_findings: list[dict[str, object]] = []
        for segment in segments:
            canonical = dict(segment)
            canonical_segments.append(canonical)
            result = self.project(str(canonical.get("text", "")), selected)
            protected = dict(canonical)
            protected["text"] = result["text"]
            protected_segments.append(protected)
            all_findings.extend(result["findings"])
        canonical_text = " ".join(str(row["text"]).strip() for row in canonical_segments if str(row.get("text", "")).strip()).strip()
        projected_text = " ".join(str(row["text"]).strip() for row in protected_segments if str(row.get("text", "")).strip()).strip()
        return {
            "canonical_text": canonical_text,
            "protected_text": projected_text if selected != PhiProtectionMode.AUDIT_MODE else canonical_text,
            "canonical_segments": canonical_segments,
            "protected_segments": protected_segments if selected != PhiProtectionMode.AUDIT_MODE else canonical_segments,
            "mode": selected.value,
            "findings": all_findings,
            "phi_categories": sorted({str(item["category"]) for item in all_findings}),
            "blocked": False,
        }
