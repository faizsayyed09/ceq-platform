from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from contracts.artifact import ArtifactMetadata
from contracts.audit import AuditVerdict
from contracts.audit_payload import AuditPayload
from contracts.audit_result import AuditResult
from contracts.knowledge import KnowledgePolicyResult
from modules.exceptions import CeqError


class WorkflowStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"


class AuditWorkflowState(str, Enum):
    """Canonical workflow lifecycle states."""

    PENDING = WorkflowStatus.PENDING.value
    RUNNING = WorkflowStatus.RUNNING.value
    COMPLETED = WorkflowStatus.COMPLETED.value
    FAILED = WorkflowStatus.FAILED.value
    RETRY_SCHEDULED = WorkflowStatus.RETRY_SCHEDULED.value


class WorkflowError(CeqError):
    """An end-to-end audit workflow operation failed safely."""


@dataclass(frozen=True)
class AuditRunRequest:
    conversation_id: str
    audit_id: str = ""
    region: str = "mypurecloud.com"
    protection_mode: str = "AUDIT_MODE"
    threshold: float = 0.5
    tickets: tuple[Mapping[str, Any], ...] = ()
    articles: tuple[Mapping[str, Any], ...] = ()
    knowledge_query: str = ""
    ceq_response: str | Mapping[str, Any] = ""
    report_title: str = "CEQ Audit Report"
    retention_days: int | None = None
    idempotency_key: str = ""


@dataclass(frozen=True)
class ServiceEvidenceBundle:
    recording_metadata: Mapping[str, Any] = field(default_factory=dict)
    recording_artifact: ArtifactMetadata | None = None
    transcript_artifact: ArtifactMetadata | None = None
    transcription: Mapping[str, Any] = field(default_factory=dict)
    fingerprint: Mapping[str, Any] = field(default_factory=dict)
    ticket_match: Mapping[str, Any] = field(default_factory=dict)
    knowledge: KnowledgePolicyResult | None = None
    audit_payload: AuditPayload | None = None
    audit_result: AuditResult | None = None
    report_artifact: ArtifactMetadata | None = None


@dataclass(frozen=True)
class AuditRunResult:
    run_id: str
    conversation_id: str
    audit_id: str
    status: AuditWorkflowState
    evidence: ServiceEvidenceBundle
    verdict: AuditVerdict | None = None
    report_location: str = ""
    error: str = ""

    def with_status(self, status: AuditWorkflowState, **changes: Any) -> "AuditRunResult":
        values = dict(self.__dict__)
        values.update(changes)
        values["status"] = status
        return AuditRunResult(**values)
