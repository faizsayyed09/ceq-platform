from __future__ import annotations

from pathlib import Path

from .audio_validation import validate_audio
from .phi_protection import PhiProtectionService
from .silence_detection import detect_silence_segments
from .transcript_builder import build_transcript
from .whisper_engine import WhisperEngine


class TranscriptionService:
    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = None,
    ) -> None:
        self.language = language
        self.engine = WhisperEngine(model_size=model_size, device=device, compute_type=compute_type)

    def transcribe(
        self,
        audio_path: str | Path,
        protection_mode: str = "AUDIT_MODE",
        redact: bool | None = None,
    ) -> dict:
        if redact is not None:
            protection_mode = "LLM_MODE" if redact else "OFF"

        validated = validate_audio(audio_path)
        segments = self.engine.transcribe(audio_path, language=self.language)
        silence = detect_silence_segments(str(audio_path), segments=segments)
        phi_result = PhiProtectionService(protection_mode).project_segments(segments, protection_mode)
        result = build_transcript(phi_result["canonical_segments"])
        return {
            **result,
            "silence_segments": silence,
            "silence_count": len(silence),
            "protected_text": phi_result["protected_text"],
            "protected_segments": phi_result["protected_segments"],
            "phi_protection": {
                "mode": phi_result["mode"],
                "categories": phi_result["phi_categories"],
                "finding_count": len(phi_result["findings"]),
            },
            "transcription_engine": self.engine.metadata(),
            **validated,
        }
