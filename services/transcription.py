from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from modules.constants import MAX_AUDIO_DURATION_SECONDS, MAX_FILE_SIZE_MB
from modules.exceptions import CeqError, ValidationError
from services.phi_protection import PhiProtectionService


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

    def transcribe(
        self,
        audio_path: str | Path,
        protection_mode: str = "AUDIT_MODE",
        redact: bool | None = None,
    ) -> dict[str, object]:
        if redact is not None:
            protection_mode = "LLM_MODE" if redact else "OFF"
        phi_service = PhiProtectionService(protection_mode)
        metadata = self.validate(audio_path)
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise CeqError("faster-whisper is not installed in the runtime image") from exc

        model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
        segments, _ = model.transcribe(str(audio_path), beam_size=5, vad_filter=True)
        rows: list[dict[str, object]] = []
        for segment in segments:
            rows.append({"start": float(segment.start), "end": float(segment.end), "text": segment.text.strip()})
        phi_result = phi_service.project_segments(rows, protection_mode)
        return {
            "text": phi_result["canonical_text"],
            "segments": phi_result["canonical_segments"],
            "protected_text": phi_result["protected_text"],
            "protected_segments": phi_result["protected_segments"],
            "segment_count": len(rows),
            "phi_protection": {
                "mode": phi_result["mode"],
                "categories": phi_result["phi_categories"],
                "finding_count": len(phi_result["findings"]),
            },
            **metadata,
        }
