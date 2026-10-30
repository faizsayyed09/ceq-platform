from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from contracts.job import AuditJob, AuditChannel, JobStatus


class QueueDeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ENQUEUED = "ENQUEUED"
    COMPLETED = "COMPLETED"
    DEAD_LETTERED = "DEAD_LETTERED"


@dataclass(frozen=True)
class QueueMessage:
    message_id: str
    job_id: str
    idempotency_key: str
    job: AuditJob
    delivery_status: QueueDeliveryStatus = QueueDeliveryStatus.SCHEDULED
    scheduled_at: datetime | None = None
    attempt: int = 0
    headers: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReconciliationState:
    reconciled_at: datetime
    checked_jobs: int = 0
    recovered_running_jobs: int = 0
    scheduled_retries: int = 0
    orphaned_messages: int = 0


@dataclass
class DispatcherState:
    jobs: dict[str, AuditJob] = field(default_factory=dict)
    daily_counts: dict[str, int] = field(default_factory=dict)
    delivered_messages: dict[str, QueueMessage] = field(default_factory=dict)
    last_poll_at: datetime | None = None
    reconciliation: ReconciliationState | None = None
    paused: bool = False

    def add_job(self, job: AuditJob) -> bool:
        if job.job_id in self.jobs:
            return False
        self.jobs[job.job_id] = job
        return True

    def count_daily(self, date_key: str, agent_id: str, channel: AuditChannel) -> int:
        return self.daily_counts.get(f"{date_key}|{agent_id}|{channel.value}", 0)

    def increment_daily(self, date_key: str, agent_id: str, channel: AuditChannel) -> None:
        key = f"{date_key}|{agent_id}|{channel.value}"
        self.daily_counts[key] = self.daily_counts.get(key, 0) + 1
