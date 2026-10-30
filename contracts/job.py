from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping


class JobStatus(str, Enum):
    WAITING = "WAITING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED_CAP = "SKIPPED_CAP"
    SKIPPED_EXCLUDED = "SKIPPED_EXCLUDED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"


class AuditChannel(str, Enum):
    CALL = "CALL"
    EMAIL = "EMAIL"


@dataclass(frozen=True)
class AuditJob:
    job_id: str
    conversation_id: str
    channel: AuditChannel
    agent_id: str
    agent_name: str = ""
    manager: str = ""
    queue_ids: tuple[str, ...] = ()
    conversation_started_at: datetime | None = None
    conversation_ended_at: datetime | None = None
    due_at: datetime | None = None
    status: JobStatus = JobStatus.WAITING
    attempts: int = 0
    max_attempts: int = 5
    last_error: str = ""
    idempotency_key: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def with_status(self, status: JobStatus, **changes: Any) -> "AuditJob":
        values = dict(self.__dict__)
        values.pop("__dict__", None)
        values.update(changes)
        values["status"] = status
        return AuditJob(**values)
