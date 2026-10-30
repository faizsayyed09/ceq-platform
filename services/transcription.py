from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from modules.constants import MAX_AUDIO_DURATION_SECONDS, MAX_FILE_SIZE_MB
from modules.exceptions import CeqError, ValidationError


_PII_PATTERNS = (
    (re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"), "[REDACTED_SSN]"),
    (re.compile(r"(?<!\d)\d{16}(?!\d)"), "[REDACTED_CARD]"),
    (re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"), "[REDACTED_EMAIL]"),
)


class TranscriptionService:
    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        max_file_size_mb: int = MAX_FILE_SIZE_MB,
        max_audio_duration_seconds: int = MAX_AUDIO_DURATION_SECONDS,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.max_file_size_mb = max_file_size_mb
        self.max_audio_duration_seconds = max_audio_duration_seconds

    def validate(self, audio_path: str | Path) -> dict[str, float | int]:
        path = Path(audio_path)
        if not path.is_file():
            raise ValidationError("Audio file does not exist")
        size_bytes = path.stat().st_size
        if size_bytes > self.max_file_size_mb * 1024 * 1024:
            raise ValidationError(f"Audio exceeds {self.max_file_size_mb} MB limit")
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            raise CeqError("FFprobe is unavailable")
        try:
            result = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            duration = float(json.loads(result.stdout)["format"]["duration"])
        except (subprocess.SubprocessError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Audio metadata could not be validated") from exc
        if duration <= 0 or duration > self.max_audio_duration_seconds:
            raise ValidationError(f"Audio duration exceeds {self.max_audio_duration_seconds} seconds")
        return {"duration_seconds": duration, "size_bytes": size_bytes}

    def transcribe(self, audio_path: str | Path, redact: bool = True) -> dict[str, object]:
        metadata = self.validate(audio_path)
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise CeqError("faster-whisper is not installed in the runtime image") from exc

        model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
        segments, _ = model.transcribe(str(audio_path), beam_size=5, vad_filter=True)
        rows: list[dict[str, object]] = []
        for segment in segments:
            text = segment.text.strip()
            if redact:
                for pattern, replacement in _PII_PATTERNS:
                    text = pattern.sub(replacement, text)
            rows.append({"start": float(segment.start), "end": float(segment.end), "text": text})
        text = " ".join(str(row["text"]).strip() for row in rows if str(row["text"]).strip()).strip()
        return {"text": text, "segments": rows, "segment_count": len(rows), **metadata}
