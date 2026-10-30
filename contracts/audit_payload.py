from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from contracts.audit import AuditChannel, EvidenceItem


@dataclass(frozen=True)
class AuditRequest:
    interaction_text: str = ""
    channel: AuditChannel = AuditChannel.CALL
    ticket: Mapping[str, Any] = field(default_factory=dict)
    kb: Mapping[str, Any] = field(default_factory=dict)
    prematch: Mapping[str, Any] = field(default_factory=dict)
    call_data: Mapping[str, Any] = field(default_factory=dict)
    ceq_response: str | Mapping[str, Any] = ""
    pass_threshold: float = 96.0
    award_na_points: bool = False


@dataclass(frozen=True)
class AuditPayload:
    text: str
    verified_facts: tuple[str, ...] = ()
    evidence: tuple[EvidenceItem, ...] = ()
    ticket: Mapping[str, Any] = field(default_factory=dict)
    kb: Mapping[str, Any] = field(default_factory=dict)
    channel: AuditChannel = AuditChannel.CALL

    def validate(self) -> bool:
        return bool(self.text.strip()) and bool(self.verified_facts)
