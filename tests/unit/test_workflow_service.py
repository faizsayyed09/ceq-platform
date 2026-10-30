import asyncio
from datetime import datetime, timezone

import pytest

from contracts.audit import AuditAttributeResult, AuditVerdict
from contracts.audit_payload import AuditPayload
from contracts.audit_result import AuditResult
from contracts.workflow import AuditRunRequest, AuditWorkflowState
from services.artifact_store import ArtifactStoreService
from services.audit_workflow import AuditWorkflowService
from services.knowledge import KnowledgeService

CONVERSATION_ID = "11111111-2222-3333-4444-555555555555"
AUDIT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def run(coro):
    return asyncio.run(coro)


class MockAuth:
    def authenticate(self, region=None, **kwargs):
        return {"access_token": "token", "region": region or "mypurecloud.com"}


class MockRecording:
    def __init__(self, recording_path):
        self.recording_path = recording_path

    def download_recording(self, conversation_id):
        return {"file_path": str(self.recording_path), "filename": "call.wav", "size_bytes": self.recording_path.stat().st_size}

    def get_recording_metadata(self, conversation_id):
        return {"conversation_id": conversation_id, "recording_id": "recording-1"}


class MockTranscription:
    def transcribe(self, path, protection_mode="AUDIT_MODE"):
        return {
            "transcript": "caller asked for a password reset",
            "metrics": {"audio_duration_seconds": 30.0},
            "hold_events": [],
            "phi_protection": {"mode": protection_mode, "finding_count": 0},
        }


class MockFingerprint:
    def fingerprint(self, transcript):
        return {"transcript_hash_fingerprint": "hash", "name_tokens": ["password", "reset"]}


class MockTicketMatching:
    def __init__(self, matches=None):
        self.matches = matches

    def match(self, transcript, tickets, threshold=0.5):
        if self.matches is None:
            return {"matches": [{"ticket_id": "INC001", "score": 0.9}], "match_count": 1}
        return {"matches": self.matches, "match_count": len(self.matches)}


class MockKnowledge:
    provider = None


class MockAudit:
    def __init__(self, failure=None):
        self.failure = failure

    def build_payload(self, request):
        return AuditPayload(text="verified payload", verified_facts=("verified fact",), ticket=request.ticket)

    def execute_audit(self, request):
        if self.failure:
            raise RuntimeError(self.failure)
        return AuditResult(
            verdict=AuditVerdict.ACHIEVED,
            score_pct=96.0,
            computed_pct=96.0,
            target_pct=96.0,
            attributes=(AuditAttributeResult("opening", "Opening", 5.0, "MET", 5.0),),
        )


class MockReport:
    def __init__(self):
        self.calls = []

    async def generate(self, audit_id, title, body):
        self.calls.append((audit_id, title, body))
        return {"audit_id": audit_id, "filename": "report.html", "location": "report://stored"}


def make_request(**changes):
    values = {
        "conversation_id": CONVERSATION_ID,
        "audit_id": AUDIT_ID,
        "tickets": ({"ticket_id": "INC001", "description": "password reset"},),
        "articles": ({"article_id": "KB1", "title": "Password Reset", "body": "Reset employee password"},),
        "knowledge_query": "password reset",
        "ceq_response": '{"score_pct": 96, "attributes": {}}',
    }
    values.update(changes)
    return AuditRunRequest(**values)


def make_workflow(tmp_path, **changes):
    recording_path = tmp_path / "call.wav"
    recording_path.write_bytes(b"RIFFaudio")
    return AuditWorkflowService(
        auth_service=changes.pop("auth_service", MockAuth()),
        recording_service=changes.pop("recording_service", MockRecording(recording_path)),
        transcription_service=changes.pop("transcription_service", MockTranscription()),
        fingerprint_service=changes.pop("fingerprint_service", MockFingerprint()),
        ticket_service=changes.pop("ticket_service", MockTicketMatching()),
        knowledge_service=changes.pop("knowledge_service", KnowledgeService()),
        audit_service=changes.pop("audit_service", MockAudit()),
        report_service=changes.pop("report_service", None),
        artifact_store=changes.pop("artifact_store", ArtifactStoreService(storage_root=tmp_path / "artifacts")),
        max_attempts=changes.pop("max_attempts", 1),
        **changes,
    )


def test_successful_workflow(tmp_path):
    workflow = make_workflow(tmp_path)
    result = run(workflow.execute(make_request()))

    assert result.status == AuditWorkflowState.COMPLETED
    assert result.verdict == AuditVerdict.ACHIEVED
    assert result.evidence.recording_artifact is not None
    assert result.evidence.transcript_artifact is not None


def test_ticket_not_found(tmp_path):
    workflow = make_workflow(tmp_path, ticket_service=MockTicketMatching(matches=[]))
    result = run(workflow.execute(make_request()))

    assert result.status == AuditWorkflowState.COMPLETED
    assert result.evidence.ticket_match["match_count"] == 0
    assert result.evidence.audit_payload.ticket["prematch_status"] == "NOT_FOUND"


def test_kb_gap(tmp_path):
    workflow = make_workflow(tmp_path)
    result = run(workflow.execute(make_request(articles=(), knowledge_query="password reset")))

    assert result.status == AuditWorkflowState.COMPLETED
    assert result.evidence.knowledge.kb_gap is True
    assert result.evidence.knowledge.enforceable is False


def test_recording_failure(tmp_path):
    class RecordingFailure:
        def download_recording(self, conversation_id):
            raise RuntimeError("recording download failed")

        def get_recording_metadata(self, conversation_id):
            return {}

    workflow = make_workflow(tmp_path, recording_service=RecordingFailure())
    result = run(workflow.execute(make_request()))

    assert result.status == AuditWorkflowState.FAILED
    assert result.error == "recording download failed"


def test_transcription_failure(tmp_path):
    class TranscriptionFailure:
        def transcribe(self, path, protection_mode="AUDIT_MODE"):
            raise RuntimeError("transcription failed")

    workflow = make_workflow(tmp_path, transcription_service=TranscriptionFailure())
    result = run(workflow.execute(make_request()))

    assert result.status == AuditWorkflowState.FAILED
    assert result.error == "transcription failed"


def test_audit_failure(tmp_path):
    workflow = make_workflow(tmp_path, audit_service=MockAudit("ceq execution failed"))
    result = run(workflow.execute(make_request()))

    assert result.status == AuditWorkflowState.FAILED
    assert result.error == "ceq execution failed"


def test_report_creation(tmp_path):
    report = MockReport()
    workflow = make_workflow(tmp_path, report_service=report)
    result = run(workflow.execute(make_request()))

    assert len(report.calls) == 1
    assert result.report_location == "report://stored"


def test_artifact_persistence(tmp_path):
    workflow = make_workflow(tmp_path)
    result = run(workflow.execute(make_request()))

    assert result.evidence.recording_artifact.size_bytes > 0
    assert result.evidence.transcript_artifact.size_bytes > 0
    assert result.evidence.report_artifact is not None
    assert run(workflow.artifacts.exists(result.evidence.recording_artifact.key)) is True
    assert run(workflow.artifacts.exists(result.evidence.transcript_artifact.key)) is True
    assert run(workflow.artifacts.exists(result.evidence.report_artifact.key)) is True


def test_idempotent_re_run(tmp_path):
    workflow = make_workflow(tmp_path)
    request = make_request()
    first = run(workflow.execute(request))
    second = run(workflow.execute(request))

    assert first.run_id == second.run_id
    assert second.status == AuditWorkflowState.COMPLETED
    assert len(workflow._runs) == 1
