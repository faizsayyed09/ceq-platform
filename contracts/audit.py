from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class AuditChannel(str, Enum):
    CALL = "CALL"
    EMAIL = "EMAIL"


class EvidenceStatus(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class EvidenceItem:
    source: str
    category: str
    value: str
    status: EvidenceStatus = EvidenceStatus.VERIFIED
    timestamp: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


class ManagerReviewReason(str, Enum):
    CRITICAL_ERROR = "Critical error"
    POTENTIAL_CRITICAL_ERROR = "Potential critical error"
    MISSING_ATTRIBUTE_RESULTS = "Missing attribute results"
    AUDIT_NOT_SCORABLE = "Audit could not be scored"
    AUDIT_SERVICE_FLAG = "Flagged by audit"
    LOW_CONFIDENCE_PROCEDURE = "Procedure finding based on non-HIGH-confidence KB match"
    TICKET_NOT_VERIFIABLE = "Ticket not verifiable"
    TICKET_NOT_MATCHED = "Ticket not matched - verify manually"


class AuditVerdict(str, Enum):
    ACHIEVED = "ACHIEVED"
    NOT_ACHIEVED = "NOT_ACHIEVED"
    CRITICAL_FAIL = "CRITICAL_FAIL"
    INCOMPLETE = "INCOMPLETE"
    PARSE_ERROR = "PARSE_ERROR"
    RETRY_LATER = "RETRY_LATER"


@dataclass(frozen=True)
class AuditAttributeResult:
    key: str
    label: str
    weight: float
    result: str = "UNKNOWN"
    points: float | None = None
    missed: tuple[str, ...] = ()
    unverified: tuple[str, ...] = ()
    justification: str = ""
    evidence: tuple[EvidenceItem, ...] = ()
