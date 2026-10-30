import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "components" / "CALL AUDITS" / "v2" / "modules" / "whisper_engine.py"


def load_whisper_engine_module():
    package_name = "v2_whisper_engine_modules"
    package = types.ModuleType(package_name)
    package.__path__ = [str(MODULE_PATH.parent)]
    sys.modules[package_name] = package

    module_name = f"{package_name}.whisper_engine"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


whisper_engine = load_whisper_engine_module()


class MockWhisperModel:
    instances = []
    transcribe_calls = []

    def __init__(self, model_name, **kwargs):
        self.model_name = model_name
        self.kwargs = kwargs
        MockWhisperModel.instances.append(self)

    def transcribe(self, audio_path, **kwargs):
        MockWhisperModel.transcribe_calls.append((audio_path, kwargs))
        segments = iter([
            SimpleNamespace(start=0.0, end=2.5, text=" Hello world "),
            SimpleNamespace(start=3.0, end=4.0, text="   "),
            SimpleNamespace(start=4.0, end=5.0, text=" Second segment "),
        ])
        info = SimpleNamespace(language="en", duration=5.0)
        return segments, info


@pytest.fixture(autouse=True)
def mock_whisper(monkeypatch):
    whisper_engine._MODEL_CACHE.clear()
    MockWhisperModel.instances = []
    MockWhisperModel.transcribe_calls = []

    ctranslate2 = types.ModuleType("ctranslate2")
    faster_whisper = types.ModuleType("faster_whisper")
    faster_whisper.WhisperModel = MockWhisperModel
    faster_whisper.__version__ = "test-version"

    real_import_module = whisper_engine.importlib.import_module

    def fake_import_module(name, package=None):
        if name == "ctranslate2":
            return ctranslate2
        if name == "faster_whisper":
            return faster_whisper
        return real_import_module(name, package)

    monkeypatch.setattr(whisper_engine.importlib, "import_module", fake_import_module)
    monkeypatch.setattr(whisper_engine.importlib.metadata, "version", lambda name: "1.1.1")


def test_model_initialization():
    engine = whisper_engine.WhisperEngine(model_name="small", device="cpu", compute_type="int8", beam_size=3)

    assert engine.model_name == "small"
    assert engine.device == "cpu"
    assert engine.compute_type == "int8"
    assert engine.beam_size == 3
    assert MockWhisperModel.instances[0].model_name == "small"


def test_model_reuse():
    first = whisper_engine.WhisperEngine(model_name="base", device="cpu", compute_type="int8")
    second = whisper_engine.WhisperEngine(model_name="base", device="cpu", compute_type="int8")

    assert first.model is second.model
    assert len(MockWhisperModel.instances) == 1


def test_invalid_model():
    with pytest.raises(whisper_engine.UnsupportedModelError) as exc:
        whisper_engine.WhisperEngine(model_name="invalid-model")

    assert exc.value.code == "unsupported_model"


def test_missing_dependency(monkeypatch):
    def missing_dependency(name, package=None):
        if name == "ctranslate2":
            raise ModuleNotFoundError(name)
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(whisper_engine.importlib, "import_module", missing_dependency)

    with pytest.raises(whisper_engine.DependencyError) as exc:
        whisper_engine.WhisperEngine()

    assert exc.value.code == "dependency_missing"
    assert exc.value.details["dependency"] in {"ctranslate2", "faster-whisper"}


def test_missing_audio(tmp_path):
    engine = whisper_engine.WhisperEngine()
    missing = tmp_path / "missing.wav"

    with pytest.raises(whisper_engine.MissingAudioError) as exc:
        engine.transcribe(missing)

    assert exc.value.code == "missing_audio"


def test_transcription_result_normalization_and_metadata(tmp_path):
    audio = tmp_path / "recording.wav"
    audio.write_bytes(b"RIFF")
    engine = whisper_engine.WhisperEngine(
        model_name="large-v3-turbo",
        device="cpu",
        compute_type="int8",
        beam_size=5,
        language="en",
    )

    result = engine.transcribe(audio)

    assert result["language"] == "en"
    assert result["duration"] == 5.0
    assert result["segments"] == [
        {"start": 0.0, "end": 2.5, "text": "Hello world"},
        {"start": 4.0, "end": 5.0, "text": "Second segment"},
    ]
    assert result["transcript"] == "Hello world Second segment"
    assert result["engine"] == {
        "model": "large-v3-turbo",
        "device": "cpu",
        "compute_type": "int8",
        "backend": "faster-whisper",
        "engine_version": "1.1.1",
    }
    assert engine.metadata()["backend"] == "faster-whisper"


def test_model_load_error_is_structured(monkeypatch):
    class BrokenModel:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("model unavailable")

    faster_whisper = types.ModuleType("faster_whisper")
    faster_whisper.WhisperModel = BrokenModel

    def fake_import_module(name, package=None):
        if name == "ctranslate2":
            return types.ModuleType("ctranslate2")
        if name == "faster_whisper":
            return faster_whisper
        return whisper_engine.importlib.import_module(name, package)

    monkeypatch.setattr(whisper_engine.importlib, "import_module", fake_import_module)

    with pytest.raises(whisper_engine.ModelLoadError) as exc:
        whisper_engine.WhisperEngine()

    assert exc.value.code == "model_load_failed"
