from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .constants import MAX_AUDIO_DURATION_SECONDS, MAX_FILE_SIZE_MB
from .exceptions import ValidationError


def validate_audio(path: str | Path, max_file_size_mb: int = MAX_FILE_SIZE_MB, max_duration_seconds: int = MAX_AUDIO_DURATION_SECONDS) -> dict:
    audio_path = Path(path)
    if not audio_path.is_file():
        raise ValidationError("Audio file does not exist")

    size_bytes = audio_path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    if size_bytes <= 0:
        raise ValidationError("Audio file is empty")
    if size_mb > max_file_size_mb:
        raise ValidationError(f"Audio exceeds {max_file_size_mb} MB limit")

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise ValidationError("ffprobe is unavailable in the runtime")
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-show_entries", "format=duration,format_name:stream=codec_name,codec_type,channels,sample_rate",
                "-of", "json",
                str(audio_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        metadata = json.loads(result.stdout)
        duration = float(metadata["format"]["duration"])
        streams = metadata.get("streams", [])
        audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    except (subprocess.SubprocessError, json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        raise ValidationError("Audio metadata could not be validated") from exc

    if duration <= 0 or duration > max_duration_seconds:
        raise ValidationError(f"Audio duration exceeds {max_duration_seconds} seconds")
    if not audio_streams:
        raise ValidationError("File contains no audio stream")

    return {
        "duration_seconds": duration,
        "size_bytes": size_bytes,
        "format_name": metadata.get("format", {}).get("format_name"),
        "codec_name": audio_streams[0].get("codec_name"),
        "channels": int(audio_streams[0].get("channels", 0) or 0),
        "sample_rate": int(audio_streams[0].get("sample_rate", 0) or 0),
    }
