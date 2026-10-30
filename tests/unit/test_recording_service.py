from pathlib import Path

import pytest
import requests

from services.recording import (
    RecordingAuthorizationError,
    RecordingDownloadError,
    RecordingNotFoundError,
    RecordingService,
    RecordingStorageError,
)
from modules.validation import validate_safe_filename


CONVERSATION_ID = "11111111-2222-3333-4444-555555555555"
RECORDING_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class MockAuth:
    def authenticate(self, region=None):
        return {"access_token": "test-token", "region": region or "mypurecloud.com"}


class MockResponse:
    def __init__(self, status_code=200, payload=None, chunks=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self._chunks = chunks or []
        self.headers = headers or {}
        self.text = text if text else ("{}" if payload is not None else "")

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def iter_content(self, chunk_size=None):
        yield from self._chunks


class MockSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise requests.ConnectionError("mock connection failure")
        return self.responses.pop(0)


def recording_payload(media_state="AVAILABLE", with_second_track=False):
    media_uris = {"primary": {"mediaUri": "https://api.mypurecloud.com/audio/primary", "contentType": "audio/mpeg"}}
    if with_second_track:
        media_uris["secondary"] = {"mediaUri": "https://api.mypurecloud.com/audio/secondary", "contentType": "audio/mpeg"}
    return {"entities": [{
        "id": RECORDING_ID,
        "media": "audio",
        "fileState": media_state,
        "startTime": "2026-01-01T00:00:00Z",
        "endTime": "2026-01-01T00:10:00Z",
        "mediaUris": media_uris,
    }]}


def test_metadata_retrieval(tmp_path):
    session = MockSession([MockResponse(payload=recording_payload())])
    service = RecordingService(MockAuth(), storage_path=tmp_path, session=session)

    result = service.get_recording_metadata(CONVERSATION_ID)

    assert result == {
        "conversation_id": CONVERSATION_ID,
        "recording_id": RECORDING_ID,
        "start_time": "2026-01-01T00:00:00Z",
        "end_time": "2026-01-01T00:10:00Z",
        "queue_ids": [],
        "wrapup_code_ids": [],
    }
    assert session.calls[0][1]["headers"]["Authorization"].startswith("Bearer ")


def test_recording_discovery_dual_channel(tmp_path):
    session = MockSession([MockResponse(payload=recording_payload(with_second_track=True))])
    service = RecordingService(MockAuth(), storage_path=tmp_path, session=session)

    result = service.discover_recordings(CONVERSATION_ID)

    assert result["dual_channel"] is True
    assert [track["track"] for track in result["tracks"]] == ["primary", "secondary"]


def test_chunked_download_writes_stream_and_returns_safe_path(tmp_path):
    session = MockSession([
        MockResponse(payload=recording_payload(with_second_track=True)),
        MockResponse(payload=recording_payload(with_second_track=True)),
        MockResponse(status_code=200, chunks=[b"abc", b"def"], headers={"Content-Length": "6", "Content-Type": "audio/mpeg"}),
    ])
    service = RecordingService(MockAuth(), storage_path=tmp_path, session=session, chunk_size_bytes=3)

    result = service.download_recording(CONVERSATION_ID, track="primary")

    path = Path(result["file_path"])
    assert path.read_bytes() == b"abcdef"
    assert result["size_bytes"] == 6
    assert result["reused"] is False
    assert path.parent == tmp_path.resolve()
    assert service.safe_delete(path) is True


def test_download_accumulated_size_limit(tmp_path):
    session = MockSession([
        MockResponse(payload=recording_payload()),
        MockResponse(payload=recording_payload()),
        MockResponse(status_code=200, chunks=[b"a" * (1024 * 1024 + 1)]),
    ])
    service = RecordingService(MockAuth(), storage_path=tmp_path, session=session, max_file_size_mb=1)

    with pytest.raises(RecordingDownloadError):
        service.download_recording(CONVERSATION_ID)


def test_missing_recording(tmp_path):
    session = MockSession([MockResponse(status_code=404)])
    service = RecordingService(MockAuth(), storage_path=tmp_path, session=session)

    with pytest.raises(RecordingNotFoundError):
        service.discover_recordings(CONVERSATION_ID)


@pytest.mark.parametrize("status", [401, 403])
def test_unauthorized_recording(tmp_path, status):
    session = MockSession([MockResponse(status_code=status)])
    service = RecordingService(MockAuth(), storage_path=tmp_path, session=session)

    with pytest.raises(RecordingAuthorizationError):
        service.discover_recordings(CONVERSATION_ID)


def test_storage_error_from_replace(tmp_path, monkeypatch):
    session = MockSession([
        MockResponse(payload=recording_payload()),
        MockResponse(payload=recording_payload()),
        MockResponse(status_code=200, chunks=[b"audio"]),
    ])
    service = RecordingService(MockAuth(), storage_path=tmp_path, session=session)
    monkeypatch.setattr("services.recording.os.replace", lambda *_args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(RecordingStorageError):
        service.download_recording(CONVERSATION_ID)


def test_safe_delete_rejects_outside_root(tmp_path):
    outside = tmp_path.parent / "outside-recording.mp3"
    outside.write_bytes(b"audio")
    service = RecordingService(MockAuth(), storage_path=tmp_path)

    assert service.safe_delete(outside) is False
    assert outside.exists() is True
    outside.unlink()


def test_safe_delete_and_delete_after_processing(tmp_path):
    session = MockSession([
        MockResponse(payload=recording_payload()),
        MockResponse(payload=recording_payload()),
        MockResponse(status_code=200, chunks=[b"audio"]),
        MockResponse(payload=recording_payload()),
        MockResponse(payload=recording_payload()),
        MockResponse(status_code=200, chunks=[b"next"]),
    ])
    service = RecordingService(MockAuth(), storage_path=tmp_path, session=session)

    first = service.download_recording(CONVERSATION_ID)
    assert service.delete_recording(first["file_path"])

    second = service.download_recording(CONVERSATION_ID, delete_after_processing=True)
    assert second["deleted_after_processing"] is True
    assert not Path(second["file_path"]).exists()


def test_retention_purge(tmp_path):
    old = tmp_path / "old.webm"
    old.write_bytes(b"old")
    old_time = old.stat().st_mtime - 7200
    import os
    os.utime(old, (old_time, old_time))
    service = RecordingService(MockAuth(), storage_path=tmp_path, retention_hours=1)

    assert service.purge_expired() == 1
    assert not old.exists()


def test_hold_events(tmp_path):
    payload = {"conversationStart": "2026-01-01T00:00:00Z", "participants": [{
        "purpose": "agent",
        "sessions": [{"mediaType": "voice", "segments": [
            {"segmentType": "hold", "segmentStart": "2026-01-01T00:01:00Z", "segmentEnd": "2026-01-01T00:01:20Z"},
            {"segmentType": "hold", "segmentStart": "2026-01-01T00:01:15Z", "segmentEnd": "2026-01-01T00:01:30Z"},
        ]}],
    }]}
    session = MockSession([MockResponse(payload=payload)])
    service = RecordingService(MockAuth(), storage_path=tmp_path, session=session)

    result = service.get_hold_events(CONVERSATION_ID, "2026-01-01T00:00:00Z")

    assert result["source"] == "genesys"
    assert result["hold_events"] == [{"start": 60.0, "end": 90.0, "duration": 30.0}]


def test_filename_validation(tmp_path):
    assert validate_safe_filename("recording.mp3") == "recording.mp3"
    with pytest.raises(Exception):
        validate_safe_filename("../recording.mp3")
