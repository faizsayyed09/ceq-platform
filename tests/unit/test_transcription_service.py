import importlib.util
import sys
import types
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_ROOT = REPO_ROOT / "components" / "CALL AUDITS" / "v2" / "modules"
PACKAGE_NAME = "ceq_v2_service_tests"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(MODULE_ROOT)]
sys.modules[PACKAGE_NAME] = package
SPEC = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.service",
    MODULE_ROOT / "service.py",
)
service_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = service_module
SPEC.loader.exec_module(service_module)

ValidationError = service_module.ValidationError
TranscriptionError = service_module.TranscriptionError
TranscriptionService = service_module.TranscriptionService


def _engine_output():
    return {
        "language": "en",
        "duration": 620.0,
        "segments": [{"start": 0.0, "end": 2.5, "text": "Caller reported MRN A123456"}],
        "transcript": "Caller reported MRN A123456",
        "engine": {
            "model": "large-v3-turbo",
            "device": "cpu",
            "compute_type": "int8",
            "backend": "faster-whisper",
            "engine_version": "1.2.0",
        },
    }


class MockEngine:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def transcribe(self, audio_path, language=None):
        return _engine_output()

    def metadata(self):
        return _engine_output()["engine"]


class MockPhiService:
    last_mode = None

    def __init__(self, mode):
        self.mode = mode
        MockPhiService.last_mode = mode

    def project_segments(self, segments, mode=None):
        MockPhiService.last_mode = mode or self.mode
        protected = []
        for segment in segments:
            row = dict(segment)
            row["text"] = row["text"].replace("A123456", "[PHI_MRN]")
            protected.append(row)
        return {
            "canonical_segments": list(segments),
            "protected_segments": protected,
            "mode": str(mode or self.mode),
            "findings": [{"category": "mrn", "start": 21, "end": 28}],
            "phi_categories": ["mrn"],
        }


@pytest.fixture
def orchestration(monkeypatch):
    monkeypatch.setattr(service_module, "WhisperEngine", MockEngine)
    monkeypatch.setattr(service_module, "validate_audio", lambda *args, **kwargs: {
        "path": "mock_audio.wav",
        "duration_seconds": 620.0,
        "size_bytes": 1024,
        "extension": "wav",
    })
    monkeypatch.setattr(service_module, "build_transcript", lambda segments: {
        "text": " ".join(str(row["text"]) for row in segments),
        "segments": list(segments),
        "utterances": [],
        "metrics": {"segment_count": len(segments), "word_count": 4, "duration": 2.5},
    })
    monkeypatch.setattr(service_module, "analyze_silence", lambda *args, **kwargs: {
        "hold_events": [{"start": 10.0, "end": 40.0, "duration": 30.0}],
        "long_silence_events": [{"start": 100.0, "end": 140.0, "duration": 40.0}],
        "update_gaps": [{"start": 40.0, "end": 170.0, "duration": 130.0}],
        "metrics": {"dead_air_seconds": 40.0, "hold_seconds": 30.0, "hold_count": 1, "silence_count": 1},
    })
    monkeypatch.setattr(service_module, "PhiProtectionService", MockPhiService)


def test_successful_orchestration(orchestration, monkeypatch):
    service = TranscriptionService(model_name="large-v3-turbo", language="en", phi_mode="AUDIT_MODE")
    result = service.transcribe("mock_audio.wav")

    assert result["transcript"] == "Caller reported MRN A123456"
    assert "A123456" not in result["transcript_clean"]
    assert result["segments"][0]["text"] == "Caller reported MRN A123456"
    assert result["hold_events"]
    assert result["long_silence_events"]
    assert result["phi_findings"]
    assert result["engine"]["model"] == "large-v3-turbo"
    assert result["metrics"]["audio_duration_seconds"] == 620.0
    assert result["metrics"]["segment_count"] == 1
    assert result["metrics"]["hold_count"] == 1


def test_invalid_file_raises_structured_validation_error(orchestration, monkeypatch):
    def invalid_validation(*args, **kwargs):
        raise service_module.ModuleValidationError("missing audio file")

    monkeypatch.setattr(service_module, "validate_audio", invalid_validation)
    service = TranscriptionService()

    with pytest.raises(ValidationError) as exc:
        service.transcribe("missing.wav")

    assert exc.value.code == "audio_validation_failed"
    assert exc.value.path == "missing.wav"


def test_transcription_failure_is_structured(orchestration, monkeypatch):
    class FailingEngine(MockEngine):
        def transcribe(self, audio_path, language=None):
            raise service_module.WhisperEngineError("model_load_failed", "model unavailable")

    monkeypatch.setattr(service_module, "WhisperEngine", FailingEngine)
    service = TranscriptionService()

    with pytest.raises(TranscriptionError) as exc:
        service.transcribe("mock_audio.wav")

    assert exc.value.code == "model_load_failed"


def test_phi_mode_is_propagated(orchestration):
    service = TranscriptionService(phi_mode="AUDIT_MODE")
    service.transcribe("mock_audio.wav", phi_mode="LLM_MODE")

    assert MockPhiService.last_mode == "LLM_MODE"


def test_delete_audio_after_calls_safe_delete(orchestration, monkeypatch):
    calls = []
    monkeypatch.setattr(service_module, "safe_delete", lambda path, allowed_root=None: calls.append((path, allowed_root)) or True)
    service = TranscriptionService()

    service.transcribe("mock_audio.wav", delete_audio_after=True)

    assert len(calls) == 1
    assert calls[0][0] == "mock_audio.wav"


def test_metrics_and_engine_metadata_propagation(orchestration):
    service = TranscriptionService()
    result = service.transcribe("mock_audio.wav")

    assert result["metrics"]["dead_air_seconds"] == 40.0
    assert result["metrics"]["hold_seconds"] == 30.0
    assert result["engine"] == _engine_output()["engine"]


def test_transcribe_file_and_job_are_runtime_neutral(orchestration):
    service = TranscriptionService()
    file_result = service.transcribe_file("mock_audio.wav", language="en", phi_mode="OFF")
    job_result = service.transcribe_job({"audio_path": "mock_audio.wav", "language": "en", "phi_mode": "STRICT"})

    assert file_result["transcript"] == "Caller reported MRN A123456"
    assert job_result["engine"]["backend"] == "faster-whisper"
