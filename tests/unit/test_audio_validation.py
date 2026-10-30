import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = REPO_ROOT / "components" / "CALL AUDITS" / "v2" / "modules"


def load_audio_validation_module():
    package_name = "v2_audio_validation_modules"
    package = types.ModuleType(package_name)
    package.__path__ = [str(MODULE_DIR)]
    sys.modules[package_name] = package

    for filename in ("constants.py", "exceptions.py", "audio_validation.py"):
        name = filename[:-3]
        module_name = f"{package_name}.{name}"
        spec = importlib.util.spec_from_file_location(module_name, MODULE_DIR / filename)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        if name == "audio_validation":
            return module


audio_validation = load_audio_validation_module()


class CompletedProcess:
    stdout = json.dumps({
        "format": {"duration": "60.0", "format_name": "wav"},
        "streams": [{
            "codec_type": "audio",
            "codec_name": "pcm_s16le",
            "channels": 1,
            "sample_rate": 8000,
        }],
    })


def valid_ffprobe(monkeypatch, duration="60.0"):
    monkeypatch.setattr(audio_validation.shutil, "which", lambda name: "ffprobe")

    def run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout=json.dumps({
            "format": {"duration": duration, "format_name": "wav"},
            "streams": [{
                "codec_type": "audio",
                "codec_name": "pcm_s16le",
                "channels": 1,
                "sample_rate": 8000,
            }],
        }), stderr="")

    monkeypatch.setattr(audio_validation.subprocess, "run", run)


def test_valid_file(tmp_path, monkeypatch):
    audio = tmp_path / "recording.wav"
    audio.write_bytes(b"RIFF" + b"\x00" * 100)
    valid_ffprobe(monkeypatch)

    result = audio_validation.validate_audio(audio, allowed_roots=[tmp_path])

    assert result["extension"] == "wav"
    assert result["duration_seconds"] == 60.0
    assert result["size_bytes"] == 104


def test_invalid_extension(tmp_path):
    audio = tmp_path / "recording.aac"
    audio.write_bytes(b"audio")

    with pytest.raises(audio_validation.AudioValidationError) as exc:
        audio_validation.validate_audio_path(audio)
        audio_validation.validate_file_extension(audio)

    assert exc.value.code == "unsupported_extension"


def test_windows_style_traversal_rejected():
    windows_path = r"C:\temp\..\Windows\system32\audio.wav"

    with pytest.raises(audio_validation.AudioValidationError) as exc:
        audio_validation.validate_audio_path(windows_path)

    assert exc.value.code == "path_traversal"


def test_missing_file(tmp_path):
    missing = tmp_path / "missing.wav"

    with pytest.raises(audio_validation.AudioValidationError) as exc:
        audio_validation.validate_audio_path(missing)

    assert exc.value.code == "file_missing"


def test_path_traversal_rejected(tmp_path):
    traversal = tmp_path / ".." / "outside.wav"

    with pytest.raises(audio_validation.AudioValidationError) as exc:
        audio_validation.validate_audio_path(traversal)

    assert exc.value.code == "path_traversal"


def test_symlink_rejected(tmp_path):
    target = tmp_path / "target.wav"
    target.write_bytes(b"audio")
    link = tmp_path / "link.wav"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"Symlinks unavailable in this environment: {exc}")

    with pytest.raises(audio_validation.AudioValidationError) as exc:
        audio_validation.validate_audio_path(link)

    assert exc.value.code == "symlink_not_allowed"


def test_oversized_file(tmp_path):
    audio = tmp_path / "oversized.mp3"
    with audio.open("wb") as stream:
        stream.truncate(500 * 1024 * 1024 + 1)

    with pytest.raises(audio_validation.AudioValidationError) as exc:
        audio_validation.validate_file_size(audio)

    assert exc.value.code == "file_too_large"


def test_over_duration_file(tmp_path, monkeypatch):
    audio = tmp_path / "long.wav"
    audio.write_bytes(b"audio")
    valid_ffprobe(monkeypatch, duration="14400.1")

    with pytest.raises(audio_validation.AudioValidationError) as exc:
        audio_validation.validate_audio_duration(audio)

    assert exc.value.code == "duration_too_long"


def test_safe_delete_allowed(tmp_path):
    audio = tmp_path / "delete.wav"
    audio.write_bytes(b"audio")

    assert audio_validation.safe_delete(audio, allowed_root=tmp_path, allow_delete=True) is True
    assert not audio.exists()


def test_safe_delete_denied_outside_root(tmp_path):
    approved_root = tmp_path / "approved"
    approved_root.mkdir()
    audio = tmp_path / "deny.wav"
    audio.write_bytes(b"audio")

    assert audio_validation.safe_delete(audio, allowed_root=approved_root, allow_delete=True) is False
    assert audio.exists()


def test_safe_delete_denied_without_root(tmp_path):
    audio = tmp_path / "deny.wav"
    audio.write_bytes(b"audio")

    assert audio_validation.safe_delete(audio) is False
    assert audio.exists()
