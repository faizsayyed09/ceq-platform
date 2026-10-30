from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from modules.constants import MAX_AUDIO_DURATION_SECONDS, MAX_FILE_SIZE_MB
from modules.exceptions import ValidationError


def validate_audio(path: str | Path, max_file_size_mb: int = MAX_FILE_SIZE_MB, max_duration_seconds: int = MAX_AUDIO_DURATION_SECONDS) -> dict:
    audio_path = Path(path)
    if not audio_path.is_file():
        raise ValidationError("Audio file does not exist")
    size_mb = audio_path.stat().st_size / (1024 * 1024)
    if size_mb > max_file_size_mb:
        raise ValidationError(f"Audio exceeds {max_file_size_mb} MB limit")

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise ValidationError("ffprobe is unavailable in the runtime")
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(audio_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        metadata = json.loads(result.stdout)
        duration = float(metadata["format"]["duration"])
    except (subprocess.SubprocessError, json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        raise ValidationError("Audio metadata could not be validated") from exc
    if duration <= 0 or duration > max_duration_seconds:
        raise ValidationError(f"Audio duration exceeds {max_duration_seconds} seconds")
    return {"duration_seconds": duration, "size_bytes": audio_path.stat().st_size}
