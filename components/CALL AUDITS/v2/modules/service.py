from __future__ import annotations

import logging
from pathlib import Path

from .audio_validation import safe_delete, validate_audio
from .phi_protection import PhiProtectionService
from .silence_detection import detect_silence_segments, summarize_silence
from .transcript_builder import build_transcript
from .whisper_engine import WhisperEngine


_LOGGER = logging.getLogger("ceq.transcription.service")


class TranscriptionService:
    def __init__(
        self,
        model_size: str = "large-v3-turbo",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = None,
        hold_threshold_seconds: float = 30.0,
        long_silence_threshold_seconds: float = 10.0,
    ) -> None:
        self.language = language
        self.hold_threshold_seconds = hold_threshold_seconds
        self.long_silence_threshold_seconds = long_silence_threshold_seconds
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
        _LOGGER.info("Starting transcription", extra={"correlation_id": Path(audio_path).name})
        segments = self.engine.transcribe(audio_path, language=self.language)
        silence = detect_silence_segments(
            str(audio_path),
            segments=segments,
            minimum_gap_seconds=min(self.hold_threshold_seconds, self.long_silence_threshold_seconds),
            hold_threshold_seconds=self.hold_threshold_seconds,
            long_silence_threshold_seconds=self.long_silence_threshold_seconds,
        )
        hold_events = [event for event in silence if event["type"] == "hold"]
        long_silence_events = [event for event in silence if event["type"] == "long_silence"]
        phi_result = PhiProtectionService(protection_mode).project_segments(segments, protection_mode)
        result = build_transcript(phi_result["canonical_segments"])
        silence_metrics = summarize_silence(silence)
        metrics = {
            "audio_duration_seconds": validated["duration_seconds"],
            "segment_count": result["segment_count"],
            "utterance_count": result["utterance_count"],
            "hold_event_count": len(hold_events),
            "long_silence_event_count": len(long_silence_events),
            **silence_metrics,
        }
        _LOGGER.info("Transcription completed with %d segments", result["segment_count"])
        return {
            "transcript": result["text"],
            "segments": result["segments"],
            "utterances": result["utterances"],
            "hold_events": hold_events,
            "long_silence_events": long_silence_events,
            "metrics": metrics,
            "phi_findings": phi_result["findings"],
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

    @staticmethod
    def safe_delete(path: str | Path, allowed_root: str | Path | None = None) -> bool:
        return safe_delete(path, allowed_root=allowed_root)
