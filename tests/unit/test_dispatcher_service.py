from datetime import datetime, timedelta, timezone

from contracts.job import AuditChannel, JobStatus
from services.dispatcher import DispatcherService


def conversation(conversation_id, agent_id="agent-1", queue_id="queue-1", minutes_ago=30, channel="CALL"):
    end = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc) - timedelta(minutes=minutes_ago)
    start = end - timedelta(minutes=10)
    return {
        "conversationId": conversation_id,
        "conversationStart": start.isoformat(),
        "conversationEnd": end.isoformat(),
        "channel": channel,
        "participants": [{
            "userId": agent_id,
            "purpose": "agent",
            "sessions": [{"segments": [{"queueId": queue_id}]}],
        }],
        "originatingDirection": "inbound",
    }


def service(**changes):
    values = {
        "roster": {"agent-1": {"name": "Agent One", "manager": "Manager One"}},
        "grace_period_minutes": 10,
        "min_duration_seconds": 0,
    }
    values.update(changes)
    return DispatcherService(**values)


def test_daily_limit_per_agent_and_channel():
    dispatcher = service(max_calls_per_agent=1, max_emails_per_agent=1)
    now = datetime(2026, 1, 15, 12, 30, tzinfo=timezone.utc)
    first = dispatcher.poll_conversations([conversation("conv-1")], now)[0]
    second = dispatcher.poll_conversations([conversation("conv-2")], now)[0]
    assert first.status == JobStatus.QUEUED
    assert second.status == JobStatus.SKIPPED_CAP


def test_duplicate_conversation_is_not_recreated():
    dispatcher = service()
    now = datetime(2026, 1, 15, 12, 30, tzinfo=timezone.utc)
    first_jobs = dispatcher.poll_conversations([conversation("conv-1")], now)
    second_jobs = dispatcher.poll_conversations([conversation("conv-1")], now)
    assert len(first_jobs) == 1
    assert len(second_jobs) == 1
    assert len(dispatcher.state.jobs) == 1
    assert dispatcher.is_duplicate("conv-1", AuditChannel.CALL)


def test_grace_period_delays_dispatch():
    dispatcher = service(grace_period_minutes=20)
    now = datetime(2026, 1, 15, 12, 30, tzinfo=timezone.utc)
    waiting = dispatcher.poll_conversations([conversation("conv-1", minutes_ago=-20)], now)[0]
    assert waiting.status == JobStatus.WAITING
    ready = dispatcher.reconcile(datetime(2026, 1, 15, 13, 30, tzinfo=timezone.utc))
    assert dispatcher.state.jobs[waiting.job_id].status == JobStatus.QUEUED
    assert ready.scheduled_retries >= 1


def test_queue_filtering():
    dispatcher = service(excluded_queue_ids=["blocked-queue"])
    now = datetime(2026, 1, 15, 12, 30, tzinfo=timezone.utc)
    job = dispatcher.poll_conversations([conversation("conv-1", queue_id="blocked-queue")], now)[0]
    assert job.status == JobStatus.SKIPPED_EXCLUDED


def test_roster_filtering_and_manager_assignment():
    dispatcher = service(excluded_agent_ids=["blocked-agent"])
    now = datetime(2026, 1, 15, 12, 30, tzinfo=timezone.utc)
    job = dispatcher.poll_conversations([conversation("conv-1", agent_id="blocked-agent")], now)
    assert job == []

    rostered = service()
    job = rostered.poll_conversations([conversation("conv-2")], now)[0]
    assert job.agent_name == "Agent One"
    assert job.manager == "Manager One"


def test_queue_idempotency_returns_same_message():
    dispatcher = service()
    now = datetime(2026, 1, 15, 12, 30, tzinfo=timezone.utc)
    job = dispatcher.poll_conversations([conversation("conv-1")], now)[0]
    first = dispatcher.enqueue(job, now)
    second = dispatcher.enqueue(job, now)
    assert first.message_id == second.message_id
    assert len(dispatcher.state.delivered_messages) == 1


def test_retry_and_retry_limit():
    dispatcher = service(max_attempts=2)
    now = datetime(2026, 1, 15, 12, 30, tzinfo=timezone.utc)
    job = dispatcher.poll_conversations([conversation("conv-1")], now)[0]
    message = dispatcher.enqueue(job, now)
    dispatcher.mark_failed(message.job_id, "temporary failure")
    retried = dispatcher.state.jobs[message.job_id]
    assert retried.status == JobStatus.RETRY_SCHEDULED
    retried = dispatcher.mark_failed(retried.job_id, "second failure")
    assert retried.status == JobStatus.FAILED


def test_completed_job_and_reconciliation():
    dispatcher = service(running_timeout_minutes=10)
    now = datetime(2026, 1, 15, 12, 30, tzinfo=timezone.utc)
    job = dispatcher.poll_conversations([conversation("conv-1")], now)[0]
    message = dispatcher.enqueue(job, now)
    dispatcher.mark_completed(message.job_id, {"result": "ACHIEVED"})
    result = dispatcher.reconcile(now + timedelta(minutes=20))
    assert dispatcher.state.jobs[message.job_id].status == JobStatus.COMPLETED
    assert result.checked_jobs == 1


def test_reconciliation_recovers_stale_running_job():
    dispatcher = service(max_attempts=3, running_timeout_minutes=5)
    now = datetime(2026, 1, 15, 12, 30, tzinfo=timezone.utc)
    job = dispatcher.poll_conversations([conversation("conv-1")], now)[0]
    message = dispatcher.enqueue(job, now)
    reconciliation = dispatcher.reconcile(now + timedelta(minutes=10))
    assert reconciliation.recovered_running_jobs == 1
    assert reconciliation.scheduled_retries == 1
