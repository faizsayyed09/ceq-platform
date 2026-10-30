from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from contracts.dispatcher import DispatcherState, QueueDeliveryStatus, QueueMessage, ReconciliationState
from contracts.job import AuditChannel, AuditJob, JobStatus
from modules.exceptions import ValidationError


class DispatcherService:
    """Roster-based dispatcher with durable-state contracts, queue messages, and reconciliation."""

    def __init__(
        self,
        roster: Mapping[str, Any] | Sequence[Mapping[str, Any]] | str | None = None,
        state: DispatcherState | None = None,
        daily_limit_calls: int = 2,
        daily_limit_emails: int = 3,
        max_calls_per_agent: int | None = None,
        max_emails_per_agent: int | None = None,
        grace_period_minutes: int = 10,
        ticket_grace_min: int | None = None,
        excluded_agent_ids: Iterable[str] = (),
        excluded_agents: Iterable[str] = (),
        excluded_queue_ids: Iterable[str] = (),
        excluded_queues: Iterable[str] = (),
        inbound_only: bool = True,
        min_duration_seconds: int = 60,
        poll_interval_minutes: int = 2,
        recheck_min: int | None = None,
        max_attempts: int = 5,
        running_timeout_minutes: int = 90,
        conversation_provider: Callable[..., Iterable[Mapping[str, Any]]] | None = None,
        clock: Callable[[], datetime] | None = None,
        daily_limits: Mapping[str, int] | None = None,
        grace_period_min: int | None = None,
        **options: Any,
    ) -> None:
        if grace_period_min is not None:
            grace_period_minutes = grace_period_min
        if daily_limits is not None:
            daily_limit_calls = int(daily_limits.get("CALL", daily_limits.get("calls", daily_limit_calls)))
            daily_limit_emails = int(daily_limits.get("EMAIL", daily_limits.get("emails", daily_limit_emails)))
        excluded_agent_ids = options.pop("excluded_agent_names", ()) if "excluded_agent_names" in options else excluded_agent_ids
        excluded_queue_ids = options.pop("excluded_queue_names", ()) if "excluded_queue_names" in options else excluded_queue_ids
        self.state = state or DispatcherState()
        self.daily_limits = {
            AuditChannel.CALL: max_calls_per_agent if max_calls_per_agent is not None else daily_limit_calls,
            AuditChannel.EMAIL: max_emails_per_agent if max_emails_per_agent is not None else daily_limit_emails,
        }
        if ticket_grace_min is not None:
            grace_period_minutes = ticket_grace_min
        self.grace_period = timedelta(minutes=max(0, grace_period_minutes))
        self.excluded_agent_ids = {str(value).strip().lower() for value in set(excluded_agent_ids) | set(excluded_agents) if str(value).strip()}
        self.excluded_queue_ids = {str(value).strip().lower() for value in set(excluded_queue_ids) | set(excluded_queues) if str(value).strip()}
        self.inbound_only = inbound_only
        self.min_duration_seconds = min_duration_seconds
        self.poll_interval_minutes = recheck_min if recheck_min is not None else poll_interval_minutes
        self.max_attempts = max_attempts
        self.running_timeout = timedelta(minutes=running_timeout_minutes)
        self.conversation_provider = conversation_provider
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.agents = self._normalize_roster(roster or {})

    def poll_conversations(self, conversations: Iterable[Mapping[str, Any]] | None = None, now: datetime | None = None) -> list[AuditJob]:
        if conversations is None:
            if self.conversation_provider is None:
                return []
            conversations = self.conversation_provider()
        current = self._as_utc(now or self.clock())
        jobs: list[AuditJob] = []
        for conversation in conversations:
            conversation = dict(conversation)
            channel = self._channel(conversation)
            conversation_id = str(conversation.get("conversationId") or conversation.get("conversation_id") or "").strip()
            if not conversation_id:
                continue
            agent_id, agent_name, manager = self._find_agent(conversation)
            if not agent_id:
                continue
            if str(agent_id).lower() in self.excluded_agent_ids or str(agent_name).lower() in self.excluded_agent_ids:
                job = self._new_job(conversation, channel, agent_id, agent_name, manager, status=JobStatus.SKIPPED_EXCLUDED, now=current)
                self.state.add_job(job)
                jobs.append(job)
                continue
            queues = tuple(sorted(self._queue_ids(conversation)))
            if self.excluded_queue_ids.intersection(set(queues)):
                job = self._new_job(conversation, channel, agent_id, agent_name, manager, status=JobStatus.SKIPPED_EXCLUDED, now=current, queue_ids=queues)
                self.state.add_job(job)
                jobs.append(job)
                continue
            ended = self._datetime(conversation.get("conversationEnd") or conversation.get("conversation_end") or conversation.get("ended_at"))
            started = self._datetime(conversation.get("conversationStart") or conversation.get("conversation_start") or conversation.get("started_at"))
            if not started or not ended:
                continue
            if channel == AuditChannel.CALL and (ended - started).total_seconds() < self.min_duration_seconds:
                continue
            if self.inbound_only and not self._is_inbound(conversation):
                continue
            job = self._new_job(conversation, channel, agent_id, agent_name, manager, now=current, queue_ids=queues, started=started, ended=ended)
            if not self.state.add_job(job):
                existing = self.state.jobs.get(job.job_id)
                if existing is not None:
                    jobs.append(existing)
                continue
            day_key = self._et_date(ended)
            count = self.state.count_daily(day_key, agent_id, channel)
            limit = int(self.daily_limits[channel])
            if limit > 0 and count >= limit:
                job = job.with_status(JobStatus.SKIPPED_CAP)
                self.state.jobs[job.job_id] = job
            else:
                if current < job.due_at:
                    job = job.with_status(JobStatus.WAITING)
                else:
                    job = job.with_status(JobStatus.QUEUED)
                self.state.jobs[job.job_id] = job
                self.state.increment_daily(day_key, agent_id, channel)
            jobs.append(job)
        self.state.last_poll_at = current
        return jobs

    poll = poll_conversations
    dispatch = poll_conversations
    poll_and_dispatch = poll_conversations
    dispatch_conversations = poll_conversations

    def is_duplicate(self, conversation_id: str, channel: AuditChannel | str = AuditChannel.CALL) -> bool:
        channel_value = AuditChannel(channel).value if isinstance(channel, AuditChannel) else str(channel).upper()
        idempotency_key = hashlib.sha256((conversation_id + "|" + channel_value).encode("utf-8")).hexdigest()
        return idempotency_key in self.state.jobs or idempotency_key in {message.job_id for message in self.state.delivered_messages.values()}

    def get_job(self, job_id: str) -> AuditJob | None:
        return self.state.jobs.get(job_id)

    def create_job(self, conversation: Mapping[str, Any], now: datetime | None = None) -> AuditJob | None:
        return next(iter(self.poll_conversations([conversation], now)), None)

    def enqueue(self, job: AuditJob, now: datetime | None = None) -> QueueMessage:
        if job.job_id in {item.job_id for item in self.state.delivered_messages.values() if item.delivery_status != QueueDeliveryStatus.DEAD_LETTERED}:
            existing = next(item for item in self.state.delivered_messages.values() if item.job_id == job.job_id and item.delivery_status != QueueDeliveryStatus.DEAD_LETTERED)
            return existing
        if job.status not in (JobStatus.QUEUED, JobStatus.RETRY_SCHEDULED):
            raise ValidationError("Only queued or retry-scheduled jobs can be enqueued")
        current = self._as_utc(now or self.clock())
        message_id = "msg-" + job.idempotency_key
        message = QueueMessage(
            message_id=message_id,
            job_id=job.job_id,
            idempotency_key=job.idempotency_key,
            job=job,
            delivery_status=QueueDeliveryStatus.ENQUEUED,
            scheduled_at=current,
            attempt=job.attempts + 1,
        )
        self.state.delivered_messages[message.message_id] = message
        updated = job.with_status(JobStatus.RUNNING, attempts=job.attempts + 1)
        self.state.jobs[job.job_id] = updated
        return message

    def mark_running(self, job_id: str, now: datetime | None = None) -> AuditJob:
        current = self._as_utc(now or self.clock())
        job = self._require_job(job_id)
        return self._transition(job_id, JobStatus.RUNNING, attempts=job.attempts, metadata={"started_at": current.isoformat()})

    def mark_completed(self, job_id: str, result: Mapping[str, Any] | None = None) -> AuditJob:
        completed = self._transition(job_id, JobStatus.COMPLETED, metadata=result or {})
        for message_id, message in list(self.state.delivered_messages.items()):
            if message.job_id == job_id:
                self.state.delivered_messages[message_id] = QueueMessage(message_id=message.message_id, job_id=message.job_id, idempotency_key=message.idempotency_key, job=completed, delivery_status=QueueDeliveryStatus.COMPLETED, scheduled_at=message.scheduled_at, attempt=message.attempt, headers=message.headers)
        return completed

    def mark_failed(self, job_id: str, error: str) -> AuditJob:
        job = self._require_job(job_id)
        failure_count = int(job.metadata.get("failure_count", 0)) + 1
        if failure_count < self.max_attempts and failure_count < job.max_attempts:
            scheduled = self._transition(job_id, JobStatus.RETRY_SCHEDULED, last_error=str(error), metadata={"failure_count": failure_count})
            current = self._as_utc(self.clock())
            backoff_minutes = min(60, 2 ** max(0, scheduled.attempts - 1))
            message = QueueMessage(message_id="retry-" + scheduled.idempotency_key + "-" + str(scheduled.attempts), job_id=scheduled.job_id, idempotency_key=scheduled.idempotency_key, job=scheduled, delivery_status=QueueDeliveryStatus.SCHEDULED, scheduled_at=current + timedelta(minutes=backoff_minutes), attempt=scheduled.attempts)
            self.state.delivered_messages[message.message_id] = message
            return scheduled
        return self._transition(job_id, JobStatus.FAILED, last_error=str(error), metadata={"failure_count": failure_count})

    retry = mark_failed
    retry_job = mark_failed

    def handle_message(self, message: QueueMessage, error: str | None = None) -> AuditJob:
        existing = self.state.jobs.get(message.job_id)
        if existing is None:
            raise ValidationError("Queue message references an unknown job")
        return self.mark_completed(message.job_id) if error is None else self.mark_failed(message.job_id, error)

    def reconcile(self, now: datetime | None = None) -> ReconciliationState:
        current = self._as_utc(now or self.clock())
        checked = len(self.state.jobs)
        recovered = 0
        scheduled = 0
        orphaned = 0
        for job_id, job in list(self.state.jobs.items()):
            if job.status == JobStatus.RUNNING:
                timeout_at = (job.metadata.get("started_at") if isinstance(job.metadata, Mapping) else None)
                if timeout_at is None or self._as_utc(datetime.fromisoformat(str(timeout_at))) < current - self.running_timeout:
                    if job.attempts < self.max_attempts and job.attempts < job.max_attempts:
                        self.state.jobs[job_id] = job.with_status(JobStatus.RETRY_SCHEDULED, last_error="Running job timed out")
                        scheduled += 1
                    else:
                        self.state.jobs[job_id] = job.with_status(JobStatus.FAILED, last_error="Running job timed out")
                    recovered += 1
            elif job.status == JobStatus.WAITING and job.due_at and current >= job.due_at:
                self.state.jobs[job_id] = job.with_status(JobStatus.QUEUED)
                scheduled += 1
        known_ids = set(self.state.jobs)
        for message in self.state.delivered_messages.values():
            if message.job_id not in known_ids:
                orphaned += 1
        result = ReconciliationState(current, checked, recovered, scheduled, orphaned)
        self.state.reconciliation = result
        return result

    reconcile_jobs = reconcile

    def _normalize_roster(self, roster: Mapping[str, Any] | Sequence[Mapping[str, Any]] | str) -> dict[str, Mapping[str, Any]]:
        if isinstance(roster, str):
            result = {}
            for line in roster.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                manager, names = line.split(":", 1)
                for raw_name in re.split(r"[,;\t]", names):
                    raw_name = raw_name.strip()
                    if not raw_name:
                        continue
                    name = raw_name
                    override = ""
                    if "=" in raw_name:
                        name, override = [part.strip() for part in raw_name.rsplit("=", 1)]
                    if override:
                        result[override.lower()] = {"name": name, "manager": manager.strip(), "email": ""}
            return result
        if isinstance(roster, Sequence) and not isinstance(roster, (str, bytes)):
            result = {}
            for item in roster:
                agent_id = str(item.get("agent_id") or item.get("id") or "").lower()
                if agent_id:
                    result[agent_id] = {"name": item.get("name") or item.get("roster_name") or agent_id, "manager": item.get("manager") or ""}
            return result
        if isinstance(roster, Mapping) and isinstance(roster.get("agents"), Mapping):
            roster = roster["agents"]
        if not isinstance(roster, Mapping):
            return {}
        result = {}
        for agent_id, details in roster.items():
            normalized_id = str(agent_id).lower()
            if isinstance(details, Mapping):
                result[normalized_id] = {"name": details.get("name") or details.get("roster_name") or normalized_id, "manager": details.get("manager") or "", "email": details.get("email") or ""}
            else:
                result[normalized_id] = {"name": str(details), "manager": "", "email": ""}
        return result

    def _find_agent(self, conversation: Mapping[str, Any]) -> tuple[str, str, str]:
        for participant in conversation.get("participants") or []:
            if not isinstance(participant, Mapping):
                continue
            agent_id = str(participant.get("userId") or participant.get("user_id") or "").lower()
            if agent_id in self.agents:
                details = self.agents[agent_id]
                if str(participant.get("purpose") or "").lower() in ("agent", "user") or "purpose" not in participant:
                    return agent_id, str(details.get("name") or agent_id), str(details.get("manager") or "")
        return "", "", ""

    def _queue_ids(self, conversation: Mapping[str, Any]) -> set[str]:
        result = set()
        for participant in conversation.get("participants") or []:
            if not isinstance(participant, Mapping):
                continue
            for session in participant.get("sessions") or []:
                if not isinstance(session, Mapping):
                    continue
                for segment in session.get("segments") or []:
                    if isinstance(segment, Mapping):
                        queue_id = segment.get("queueId") or segment.get("queue_id")
                        if queue_id:
                            result.add(str(queue_id).lower())
        return result

    def _is_inbound(self, conversation: Mapping[str, Any]) -> bool:
        if not self.inbound_only:
            return True
        direction = str(conversation.get("originatingDirection") or conversation.get("direction") or conversation.get("originating_direction") or "").lower()
        if direction:
            return direction == "inbound"
        return True

    def _channel(self, conversation: Mapping[str, Any]) -> AuditChannel:
        value = str(conversation.get("channel") or conversation.get("mediaType") or conversation.get("media_type") or "").upper()
        return AuditChannel.EMAIL if "EMAIL" in value else AuditChannel.CALL

    def _new_job(self, conversation: Mapping[str, Any], channel: AuditChannel, agent_id: str, agent_name: str, manager: str, status: JobStatus = JobStatus.WAITING, now: datetime | None = None, queue_ids: tuple[str, ...] | None = None, started: datetime | None = None, ended: datetime | None = None) -> AuditJob:
        conversation_id = str(conversation.get("conversationId") or conversation.get("conversation_id") or "").strip()
        ended = ended or self._datetime(conversation.get("conversationEnd") or conversation.get("conversation_end") or conversation.get("ended_at")) or (now or self.clock())
        started = started or self._datetime(conversation.get("conversationStart") or conversation.get("conversation_start") or conversation.get("started_at"))
        due_at = ended + self.grace_period
        idempotency_key = hashlib.sha256((conversation_id + "|" + channel.value).encode("utf-8")).hexdigest()
        return AuditJob(job_id=idempotency_key, conversation_id=conversation_id, channel=channel, agent_id=agent_id, agent_name=agent_name, manager=manager, queue_ids=queue_ids or self._queue_ids_tuple(conversation), conversation_started_at=started, conversation_ended_at=ended, due_at=due_at, status=status, max_attempts=self.max_attempts, idempotency_key=idempotency_key, metadata={"created_at": (now or self.clock()).isoformat()})

    def _queue_ids_tuple(self, conversation: Mapping[str, Any]) -> tuple[str, ...]:
        return tuple(sorted(self._queue_ids(conversation)))

    def _transition(self, job_id: str, status: JobStatus, **changes: Any) -> AuditJob:
        job = self._require_job(job_id)
        metadata = dict(job.metadata)
        if status == JobStatus.RUNNING:
            metadata["started_at"] = self.clock().isoformat()
        metadata.update(changes.pop("metadata", {}))
        updated = job.with_status(status, metadata=metadata, **changes)
        self.state.jobs[job_id] = updated
        return updated

    def _require_job(self, job_id: str) -> AuditJob:
        job = self.state.jobs.get(job_id)
        if job is None:
            raise ValidationError("Audit job not found: " + job_id)
        return job

    def _as_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _datetime(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return self._as_utc(value)
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if re.fullmatch(r"\d+(?:\.\d+)?", text):
            return datetime.fromtimestamp(float(text), timezone.utc)
        try:
            return self._as_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
        except (TypeError, ValueError):
            return None

    def _et_date(self, value: datetime) -> str:
        return self._as_utc(value).astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
