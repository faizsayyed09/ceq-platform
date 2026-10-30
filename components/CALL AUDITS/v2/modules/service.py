from __future__ import annotations

from pathlib import Path

from .audio_validation import validate_audio
from .pii_redaction import redact_pii
from .transcript_builder import build_transcript
from .whisper_engine import WhisperEngine


class TranscriptionService:
    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8") -> None:
        self.engine = WhisperEngine(model_size=model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio_path: str | Path, redact: bool = True) -> dict:
        validated = validate_audio(audio_path)
        segments = self.engine.transcribe(audio_path)
        if redact:
            segments = [{**segment, "text": redact_pii(segment["text"])} for segment in segments]
        result = build_transcript(segments)
        return {**result, **validated}
