from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from collections.abc import Iterable, Mapping
from typing import Any


_LOGGER = logging.getLogger(__name__)


class PhiProtectionMode(str, Enum):
    OFF = "OFF"
    AUDIT_MODE = "AUDIT_MODE"
    LLM_MODE = "LLM_MODE"
    STRICT = "STRICT"


class PhiProtectionError(Exception):
    """Base class for structured PHI protection errors."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        self.code = code
        self.message = message
        self.details = dict(details or {})
        super().__init__(message)


class InvalidPhiModeError(PhiProtectionError):
    def __init__(self, mode: Any) -> None:
        super().__init__("invalid_phi_mode", "Invalid PHI protection mode", details={"mode": str(mode)})


class InvalidPhiInputError(PhiProtectionError):
    def __init__(self, detail: str = "PHI protection input must be text") -> None:
        super().__init__("invalid_phi_input", detail)


@dataclass(frozen=True)
class PhiFinding:
    category: str
    value: str
    start: int
    end: int


class PhiDetector(ABC):
    """Detector interface: detect(text) returns only PHI findings."""

    @abstractmethod
    def detect(self, text: str) -> list[PhiFinding]:
        raise NotImplementedError


# Backward-compatible provider abstraction name.
PhiProvider = PhiDetector


class RegexDetector(PhiProvider):
    """Regex-based HIPAA-sensitive PHI detector."""

    _PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
        ("SSN", "ssn", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")),
        ("DOB", "dob", re.compile(r"(?i)(?:date\s+of\s+birth|D\.?O\.?B\.?)\s*[:#]?\s*(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})")),
        ("MRN", "mrn", re.compile(r"(?i)(?:MRN|medical\s+record(?:\s+number)?|patient\s+record)\s*[:#]?\s*[A-Z0-9][A-Z0-9-]{3,19}")),
        ("FIN", "fin", re.compile(r"(?i)(?:FIN|financial\s+(?:identifier|number)|encounter\s+(?:number|id)?|admission\s+(?:number|id)|visit\s+(?:number|id))\s*[:#]?\s*[A-Z0-9][A-Z0-9-]{3,19}")),
        ("ENCOUNTER_NUMBER", "encounter", re.compile(r"(?i)(?:encounter|admission|visit)\s*(?:number|id|#)?\s*[:#]?\s*[A-Z0-9][A-Z0-9-]{3,19}")),
        ("INSURANCE_ID", "insurance_id", re.compile(r"(?i)(?:insurance|member|subscriber|policy)(?:\s+(?:id|number|#))?\s*[:#]?\s*[A-Z0-9][A-Z0-9-]{4,20}")),
        ("PATIENT_ACCOUNT", "patient_account", re.compile(r"(?i)(?:patient|billing|hospital|guarantor)(?:\s+(?:account|billing))?(?:\s+(?:number|id|#))?\s*[:#]?\s*[A-Z0-9][A-Z0-9-]{3,19}")),
        ("PATIENT_IDENTIFIER", "patient_identifier", re.compile(r"(?i)(?:patient(?:'s)?\s+(?:name|named|called|is)|patient\s*[:#])\s*[A-Z][A-Za-z'-]*(?:\s+[A-Z][A-Za-z'-]*)?")),
        ("DIAGNOSIS", "diagnosis", re.compile(r"(?i)(?:diagnosis|diagnosed\s+with|disease|condition)\s*[:#]?[^.!?]{0,120}")),
        ("MEDICATION", "medication", re.compile(r"(?i)(?:medication|medications|prescription|dosage|insulin|prescribed|take(s)?\s+(?:\d+\s+)?(?:mg|mcg))\s*[:#]?[^.!?]{0,120}")),
    )

    def detect(self, text: str) -> list[PhiFinding]:
        findings: list[PhiFinding] = []
        for _display_type, category, pattern in self._PATTERNS:
            for match in pattern.finditer(text):
                findings.append(PhiFinding(category=category, value=match.group(0), start=match.start(), end=match.end()))

        # Remove overlapping matches, preferring the earliest and then the longest span.
        findings.sort(key=lambda item: (item.start, -(item.end - item.start), item.category))
        merged: list[PhiFinding] = []
        for finding in findings:
            if merged and finding.start < merged[-1].end:
                continue
            merged.append(finding)
        merged.sort(key=lambda item: (item.start, item.end))
        return merged


# Backward-compatible name for deployments and existing integrations.
RegexPhiProvider = RegexDetector


class LocalSLMDetector(PhiProvider):
    """Optional local Ollama detector limited to PHI span classification."""

    SUPPORTED_MODELS = frozenset({"gemma3", "qwen3", "mistral-small", "llama3.2"})
    PHI_CATEGORIES = frozenset({
        "mrn", "fin", "encounter", "dob", "ssn", "insurance_id",
        "patient_account", "diagnosis", "medication", "patient_identifier",
    })

    def __init__(
        self,
        model: str = "llama3.2",
        endpoint: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.model = str(model).strip().lower()
        if self.model not in self.SUPPORTED_MODELS:
            raise InvalidPhiInputError(f"Unsupported local PHI model: {self.model}")
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def detect(self, text: str) -> list[PhiFinding]:
        if not isinstance(text, str):
            raise InvalidPhiInputError()

        prompt = (
            "You are a PHI span classifier only. Do not audit, summarize, score, or explain the call. "
            "Return JSON only as an array of objects. Each object must contain category, text, and offset. "
            "Detect only HIPAA-sensitive PHI spans: MRN, FIN, encounter numbers, DOB, SSN, insurance/member IDs, "
            "patient account numbers, diagnoses, medication references, and explicit patient identifiers. "
            "Do not modify or include agent names, caller names, phone numbers, extensions, employee IDs, ticket numbers, "
            "KB references, ServiceNow references, departments, locations, devices, or systems. "
            "The offset must be the exact character offset in the source text. Use category values exactly from: "
            "MRN, FIN, ENCOUNTER, DOB, SSN, INSURANCE_ID, PATIENT_ACCOUNT, DIAGNOSIS, MEDICATION, PATIENT_IDENTIFIER.\n"
            f"SOURCE_TEXT: {json.dumps(text, ensure_ascii=False)}"
        )
        payload = json.dumps({"model": self.model, "prompt": prompt, "stream": False}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.endpoint}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            raise PhiProtectionError("local_slm_unavailable", "Local PHI SLM is unavailable", details={"model": self.model, "detail": str(exc)}) from exc

        raw_response = str(body.get("response", "")).strip()
        if raw_response.startswith("```"):
            raw_response = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_response, flags=re.IGNORECASE).strip()
        try:
            items = json.loads(raw_response)
        except json.JSONDecodeError:
            _LOGGER.warning("Local PHI SLM returned non-JSON output; ignoring SLM findings")
            return []
        if not isinstance(items, list):
            return []

        findings: list[PhiFinding] = []
        category_aliases = {
            "encounter_number": "encounter",
            "insurance": "insurance_id",
            "member_id": "insurance_id",
            "patient_name": "patient_identifier",
            "clinical_detail": "diagnosis",
        }
        for item in items:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category", "")).strip().lower().replace("-", "_")
            category = category_aliases.get(category, category)
            if category not in self.PHI_CATEGORIES:
                continue
            span = item.get("text")
            if not isinstance(span, str) or not span:
                continue
            try:
                offset = int(item.get("offset"))
            except (TypeError, ValueError):
                continue
            if offset < 0 or text[offset:offset + len(span)] != span:
                continue
            operational_pattern = re.compile(
                r"(?i)(?:ticket|INC|KB|employee|extension|ext\.?|SNOW|ServiceNow|phone|email|caller|agent)\s*[:#-]?\s*[A-Z0-9@._+-]*"
            )
            if re.search(r"(?<!\w)(?:\+?1[- .]?)?(?:\(?\d{3}\)?[- .]\d{3}[- .]\d{4})(?!\w)", span):
                continue
            if operational_pattern.search(span) or re.search(r"(?i)(?:caller|agent)\s*[:#-]?\s*$", text[max(0, offset - 30):offset]):
                continue
            if category == "patient_identifier" and not re.search(r"(?i)patient(?:'s)?\s+(?:name|named|called|is)?\s*[:#-]?\s*$", text[max(0, offset - 30):offset]):
                continue
            findings.append(PhiFinding(category=category, value=span, start=offset, end=offset + len(span)))

        return _merge_findings(findings)


class FutureEnterpriseDetector(PhiProvider):
    """Reserved enterprise detector integration point."""

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    def detect(self, text: str) -> list[PhiFinding]:
        raise PhiProtectionError(
            "enterprise_detector_not_configured",
            "Future enterprise PHI detector is not configured",
            details={"provider_name": self.provider_name},
        )


class CompositeDetector(PhiProvider):
    """Combines regex and optional local or future detectors with overlap-safe merging."""

    def __init__(self, detectors: Iterable[PhiProvider]) -> None:
        self.detectors = tuple(detectors)

    def detect(self, text: str) -> list[PhiFinding]:
        findings: list[PhiFinding] = []
        for detector in self.detectors:
            findings.extend(detector.detect(text))
        return _merge_findings(findings)


def _merge_findings(findings: Iterable[PhiFinding]) -> list[PhiFinding]:
    ordered = sorted(findings, key=lambda item: (item.start, -(item.end - item.start), item.category))
    merged: list[PhiFinding] = []
    for finding in ordered:
        if merged and finding.start < merged[-1].end:
            continue
        merged.append(finding)
    return sorted(merged, key=lambda item: (item.start, item.end))


class PhiProtectionService:
    def __init__(
        self,
        default_mode: str | PhiProtectionMode = PhiProtectionMode.AUDIT_MODE,
        provider: PhiProvider | None = None,
        detector: PhiProvider | None = None,
        detectors: Iterable[PhiProvider] | None = None,
        local_slm_model: str | None = None,
        ollama_endpoint: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.default_mode = self.normalize_mode(default_mode)

        if detector is not None and provider is not None:
            raise PhiProtectionError("detector_configuration_conflict", "Configure provider or detector, not both")
        if detectors is not None:
            selected_detector: PhiProvider = CompositeDetector(detectors)
        elif detector is not None:
            selected_detector = detector
        elif provider is not None:
            selected_detector = provider
        elif local_slm_model is not None:
            selected_detector = CompositeDetector((
                RegexDetector(),
                LocalSLMDetector(local_slm_model, ollama_endpoint, timeout_seconds),
            ))
        else:
            selected_detector = RegexDetector()

        self.detector = selected_detector
        self.provider = selected_detector

    @staticmethod
    def normalize_mode(mode: str | PhiProtectionMode) -> PhiProtectionMode:
        if isinstance(mode, PhiProtectionMode):
            return mode
        try:
            return PhiProtectionMode(str(mode).strip().upper())
        except ValueError as exc:
            raise InvalidPhiModeError(mode) from exc

    def detect(self, text: str) -> list[PhiFinding]:
        if not isinstance(text, str):
            raise InvalidPhiInputError()
        return self.provider.detect(text)

    @staticmethod
    def _marker(finding: PhiFinding) -> str:
        return f"[PHI_{finding.category.upper()}]"

    def _strict_patterns(self) -> tuple[re.Pattern[str], ...]:
        return (
            re.compile(r"(?i)\b(?:agent|caller|patient)\s+[A-Z][A-Za-z'-]*(?:\s+[A-Z][A-Za-z'-]*)?"),
            re.compile(r"(?<!\w)(?:\+?1[- .]?)?(?:\(?\d{3}\)?[- .]\d{3}[- .]\d{4})(?!\w)"),
            re.compile(r"(?i)(?:ticket|INC|KB|employee|extension|ext\.?|SNOW|ServiceNow)\s*[:#-]?\s*[A-Z0-9][A-Z0-9._-]{2,}"),
        )

    def _redact(self, text: str, findings: list[PhiFinding], strict: bool = False) -> tuple[str, list[dict[str, Any]]]:
        redactions: list[tuple[int, int, str]] = [
            (finding.start, finding.end, self._marker(finding)) for finding in findings
        ]
        if strict:
            offset = 0
            strict_text = text
            reserved: list[tuple[int, int, str]] = []
            for pattern in self._strict_patterns():
                for match in pattern.finditer(strict_text):
                    reserved.append((match.start(), match.end(), "[SENSITIVE_OPERATIONAL_DATA]"))
            redactions.extend(reserved)
            # Merge overlapping strict and PHI spans before applying replacements.
            redactions.sort(key=lambda item: (item[0], -(item[1] - item[0])))
            merged: list[tuple[int, int, str]] = []
            for start, end, marker in redactions:
                if merged and start < merged[-1][1]:
                    if merged[-1][1] == end:
                        continue
                    previous_start, previous_end, previous_marker = merged[-1]
                    merged[-1] = (previous_start, max(previous_end, end), previous_marker)
                else:
                    merged.append((start, end, marker))

            projected = text
            for start, end, marker in reversed(merged):
                projected = projected[:start] + marker + projected[end:]
            applied = merged
        else:
            redactions.sort(key=lambda item: (item[0], -(item[1] - item[0])))
            merged = []
            for start, end, marker in redactions:
                if merged and start < merged[-1][1]:
                    continue
                merged.append((start, end, marker))
            projected = text
            for start, end, marker in reversed(merged):
                projected = projected[:start] + marker + projected[end:]
            applied = merged

        output_findings: list[dict[str, Any]] = []
        for finding in findings:
            output_findings.append({"type": finding.category.upper(), "value_type": "PHI", "offset": finding.start})
        return projected, output_findings

    def protect(self, text: str, mode: str | PhiProtectionMode | None = None) -> dict[str, Any]:
        if not isinstance(text, str):
            raise InvalidPhiInputError()
        selected = self.normalize_mode(mode) if mode is not None else self.default_mode
        if selected == PhiProtectionMode.OFF:
            return {"transcript": text, "transcript_clean": text, "phi_findings": []}

        findings = self.detect(text)
        projected, output_findings = self._redact(text, findings, strict=selected == PhiProtectionMode.STRICT)
        _LOGGER.info("PHI protection applied in %s mode; %d findings", selected.value, len(findings))
        return {"transcript": text, "transcript_clean": projected, "phi_findings": output_findings}

    def project(self, text: str, mode: str | PhiProtectionMode | None = None) -> dict[str, Any]:
        selected = self.normalize_mode(mode) if mode is not None else self.default_mode
        findings = [] if selected == PhiProtectionMode.OFF else self.detect(text)
        if selected == PhiProtectionMode.OFF:
            return {"text": text, "mode": selected.value, "findings": [], "phi_categories": [], "blocked": False}
        projected, output_findings = self._redact(text, findings, strict=selected == PhiProtectionMode.STRICT)
        return {
            "text": projected if selected != PhiProtectionMode.AUDIT_MODE else projected,
            "mode": selected.value,
            "findings": [{"category": finding.category, "start": finding.start, "end": finding.end} for finding in findings],
            "phi_categories": sorted({finding.category for finding in findings}),
            "blocked": False,
        }

    def project_segments(self, segments: Iterable[dict[str, object]], mode: str | PhiProtectionMode | None = None) -> dict[str, object]:
        selected = self.normalize_mode(mode) if mode is not None else self.default_mode
        canonical_segments: list[dict[str, object]] = []
        protected_segments: list[dict[str, object]] = []
        all_findings: list[dict[str, object]] = []
        phi_categories: set[str] = set()

        for segment in segments:
            canonical = dict(segment)
            canonical_segments.append(canonical)
            result = self.project(str(canonical.get("text", "")), selected)
            protected = dict(canonical)
            protected["text"] = result["text"]
            protected_segments.append(protected)
            all_findings.extend(result["findings"])
            phi_categories.update(result["phi_categories"])

        canonical_text = " ".join(str(row["text"]).strip() for row in canonical_segments if str(row.get("text", "")).strip()).strip()
        projected_text = " ".join(str(row["text"]).strip() for row in protected_segments if str(row.get("text", "")).strip()).strip()
        return {
            "canonical_text": canonical_text,
            "protected_text": projected_text,
            "canonical_segments": canonical_segments,
            "protected_segments": protected_segments,
            "mode": selected.value,
            "findings": all_findings,
            "phi_categories": sorted(phi_categories),
            "blocked": False,
        }


__all__ = [
    "PhiFinding",
    "PhiProtectionMode",
    "PhiProvider",
    "PhiDetector",
    "RegexDetector",
    "RegexPhiProvider",
    "LocalSLMDetector",
    "FutureEnterpriseDetector",
    "CompositeDetector",
    "PhiProtectionError",
    "InvalidPhiModeError",
    "InvalidPhiInputError",
    "PhiProtectionService",
]
