from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .audio_validation import safe_delete, validate_audio
from .exceptions import ValidationError as ModuleValidationError
from .phi_protection import PhiProtectionService, PhiProtectionError
from .silence_detection import analyze_silence
from .transcript_builder import build_transcript
from .whisper_engine import WhisperEngine, WhisperEngineError


_LOGGER = logging.getLogger(__name__)


class ValidationError(ModuleValidationError):
    """Structured service validation failure."""

    def __init__(self, code: str, message: str, *, path: str | Path | None = None, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = str(path) if path is not None else None
        self.details = dict(details or {})


class TranscriptionError(Exception):
    """Structured Whisper orchestration failure."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        self.code = code
        self.message = message
        self.details = dict(details or {})
        super().__init__(message)


class TranscriptionService:
    def __init__(
        self,
        model_name: str = "large-v3-turbo",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = None,
        phi_mode: str = "AUDIT_MODE",
        dead_air_threshold_seconds: float = 30.0,
        hold_update_threshold_seconds: float = 120.0,
        allowed_roots: list[str | Path] | None = None,
        model_size: str | None = None,
    ) -> None:
        self.model_name = model_name if model_size is None else model_size
        self.language = language
        self.phi_mode = phi_mode
        self.dead_air_threshold_seconds = dead_air_threshold_seconds
        self.hold_update_threshold_seconds = hold_update_threshold_seconds
        self.allowed_roots = allowed_roots
        self.engine = WhisperEngine(
            model_name=self.model_name,
            device=device,
            compute_type=compute_type,
            language=language,
        )

    @staticmethod
    def _validation_error(exc: Exception, path: str | Path) -> ValidationError:
        code = getattr(exc, "code", "audio_validation_failed")
        details = getattr(exc, "details", {})
        message = getattr(exc, "message", str(exc))
        return ValidationError(str(code), str(message), path=path, details=details)

    def transcribe(
        self,
        audio_path: str | Path,
        language: str | None = None,
        phi_mode: str | None = None,
        delete_audio_after: bool = False,
        protection_mode: str | None = None,
        redact: bool | None = None,
    ) -> dict[str, Any]:
        path = Path(audio_path)
        validated: dict[str, Any] | None = None
        selected_phi_mode = phi_mode if phi_mode is not None else protection_mode
        if redact is not None:
            selected_phi_mode = "LLM_MODE" if redact else "OFF"
        selected_phi_mode = selected_phi_mode or self.phi_mode

        try:
            validated = validate_audio(path, allowed_roots=self.allowed_roots)
        except Exception as exc:
            _LOGGER.warning("Audio validation failed", extra={"audio_path": str(path), "error": str(exc)}, exc_info=True)
            raise self._validation_error(exc, path) from exc

        try:
            _LOGGER.info("Starting canonical V2 transcription", extra={"audio_path": str(validated["path"]), "model_name": self.model_name})
            engine_output = self.engine.transcribe(validated["path"], language=language or self.language)
            if isinstance(engine_output, Mapping):
                engine_segments = engine_output.get("segments", [])
                engine_metadata = engine_output.get("engine", self.engine.metadata())
                engine_language = engine_output.get("language", "")
                engine_duration = float(engine_output.get("duration", validated["duration_seconds"]) or 0.0)
            else:
                engine_segments = engine_output
                engine_metadata = self.engine.metadata()
                engine_language = ""
                engine_duration = validated["duration_seconds"]

            transcript_result = build_transcript(engine_segments)
            canonical_segments = transcript_result["segments"]
            silence_result = analyze_silence(
                canonical_segments,
                dead_air_threshold_seconds=self.dead_air_threshold_seconds,
                hold_update_threshold_seconds=self.hold_update_threshold_seconds,
            )

            phi_service = PhiProtectionService(selected_phi_mode)
            phi_result = phi_service.project_segments(canonical_segments, selected_phi_mode)
            protected_transcript_result = build_transcript(phi_result["protected_segments"])
            transcript_clean = protected_transcript_result["text"]
            transcript = transcript_result["text"]

            metrics: dict[str, Any] = {
                **transcript_result["metrics"],
                "audio_duration_seconds": validated["duration_seconds"],
                "engine_duration_seconds": engine_duration,
                "hold_count": silence_result["metrics"]["hold_count"],
                "silence_count": silence_result["metrics"]["silence_count"],
                "dead_air_seconds": silence_result["metrics"]["dead_air_seconds"],
                "hold_seconds": silence_result["metrics"]["hold_seconds"],
            }
            result = {
                "transcript": transcript,
                "transcript_clean": transcript_clean,
                "segments": canonical_segments,
                "hold_events": silence_result["hold_events"],
                "long_silence_events": silence_result["long_silence_events"],
                "metrics": metrics,
                "phi_findings": phi_result["findings"],
                "engine": engine_metadata,
                "language": engine_language,
                "duration": engine_duration,
                "update_gaps": silence_result["update_gaps"],
                "utterances": transcript_result["utterances"],
                "phi_protection": {
                    "mode": phi_result["mode"],
                    "categories": phi_result["phi_categories"],
                    "finding_count": len(phi_result["findings"]),
                },
            }
            _LOGGER.info("Canonical V2 transcription completed", extra={"segment_count": len(canonical_segments)})
            return result
        except (ValidationError, ModuleValidationError):
            raise
        except Exception as exc:
            if isinstance(exc, PhiProtectionError):
                raise exc
            if isinstance(exc, WhisperEngineError):
                details = getattr(exc, "details", {})
                _LOGGER.exception("Whisper transcription failed", extra={"audio_path": str(path)})
                raise TranscriptionError(
                    getattr(exc, "code", "transcription_failed"),
                    "Whisper transcription failed",
                    details=details,
                ) from exc
            _LOGGER.exception("V2 transcription orchestration failed", extra={"audio_path": str(path)})
            raise TranscriptionError("transcription_failed", "Transcription orchestration failed", details={"detail": str(exc)}) from exc
        finally:
            if delete_audio_after and validated is not None:
                try:
                    deleted = safe_delete(validated["path"], allowed_root=Path(validated["path"]).parent)
                    if deleted:
                        _LOGGER.info("Deleted audio after transcription", extra={"audio_path": str(validated["path"])} )
                except Exception:
                    _LOGGER.exception("Failed to delete audio after transcription", extra={"audio_path": str(validated["path"])} )

    def transcribe_file(
        self,
        audio_path: str | Path,
        language: str | None = None,
        phi_mode: str | None = None,
        delete_audio_after: bool = False,
    ) -> dict[str, Any]:
        return self.transcribe(audio_path, language=language, phi_mode=phi_mode, delete_audio_after=delete_audio_after)

    def transcribe_job(self, job: Mapping[str, Any] | str | Path) -> dict[str, Any]:
        if isinstance(job, Mapping):
            audio_path = job.get("audio_path", job.get("path"))
            if audio_path is None:
                raise ValidationError("missing_audio_path", "Job requires audio_path or path")
            return self.transcribe(
                audio_path,
                language=job.get("language", self.language),
                phi_mode=job.get("phi_mode", job.get("protection_mode", self.phi_mode)),
                delete_audio_after=bool(job.get("delete_audio_after", False)),
            )
        return self.transcribe_file(job)

    @staticmethod
    def safe_delete(path: str | Path, allowed_root: str | Path | None = None) -> bool:
        return safe_delete(path, allowed_root=allowed_root)
