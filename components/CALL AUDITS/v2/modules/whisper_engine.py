from __future__ import annotations

import importlib
import importlib.metadata
import logging
from pathlib import Path
from typing import Any, Mapping


_LOGGER = logging.getLogger(__name__)
_SUPPORTED_MODELS = frozenset({
    "tiny",
    "base",
    "small",
    "medium",
    "large-v3",
    "large-v3-turbo",
})
_MODEL_CACHE: dict[tuple[str, str, str, str | None], object] = {}


class WhisperEngineError(Exception):
    """Base exception for structured Whisper engine failures."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = dict(details or {})
        super().__init__(message)


class UnsupportedModelError(WhisperEngineError):
    def __init__(self, model_name: str) -> None:
        super().__init__(
            "unsupported_model",
            f"Unsupported Whisper model: {model_name}",
            details={"model_name": model_name, "supported_models": sorted(_SUPPORTED_MODELS)},
        )


class DependencyError(WhisperEngineError):
    def __init__(self, dependency: str) -> None:
        super().__init__(
            "dependency_missing",
            f"Required dependency is not installed: {dependency}",
            details={"dependency": dependency},
        )


class ModelLoadError(WhisperEngineError):
    def __init__(self, model_name: str, detail: str) -> None:
        super().__init__(
            "model_load_failed",
            f"Failed to load Whisper model: {model_name}",
            details={"model_name": model_name, "detail": detail},
        )


class MissingAudioError(WhisperEngineError):
    def __init__(self, audio_path: str | Path) -> None:
        super().__init__(
            "missing_audio",
            "Audio file does not exist",
            details={"audio_path": str(audio_path)},
        )


class TranscriptionError(WhisperEngineError):
    def __init__(self, audio_path: str | Path, detail: str) -> None:
        super().__init__(
            "transcription_failed",
            "Whisper transcription failed",
            details={"audio_path": str(audio_path), "detail": detail},
        )


class WhisperEngine:
    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
        beam_size: int | None = None,
        language: str | None = None,
        config: Mapping[str, Any] | None = None,
        model_size: str | None = None,
        model_download_root: str | Path | None = None,
        vad_filter: bool | None = None,
    ) -> None:
        settings = dict(config or {})

        effective_model = model_size or model_name or settings.get("model_name") or settings.get("model_size") or "large-v3-turbo"
        effective_device = device or settings.get("device") or "cpu"
        effective_compute = compute_type or settings.get("compute_type") or "int8"
        effective_beam = beam_size if beam_size is not None else settings.get("beam_size", 5)
        effective_language = language if language is not None else settings.get("language")
        effective_root = model_download_root or settings.get("model_download_root")
        effective_vad = vad_filter if vad_filter is not None else settings.get("vad_filter", True)

        effective_model = str(effective_model).strip().lower()
        effective_device = str(effective_device).strip().lower()
        effective_compute = str(effective_compute).strip().lower()
        effective_beam = int(effective_beam)

        if effective_model not in _SUPPORTED_MODELS:
            raise UnsupportedModelError(effective_model)
        if effective_beam < 1:
            raise WhisperEngineError("invalid_beam_size", "beam_size must be at least 1", details={"beam_size": effective_beam})

        self.model_name = effective_model
        self.model_size = effective_model
        self.device = effective_device
        self.compute_type = effective_compute
        self.beam_size = effective_beam
        self.language = effective_language
        self.model_download_root = str(effective_root) if effective_root else None
        self.vad_filter = bool(effective_vad)
        self.model = self._get_or_load_model()

    def _get_or_load_model(self) -> object:
        cache_key = (self.model_name, self.device, self.compute_type, self.model_download_root)
        if cache_key in _MODEL_CACHE:
            return _MODEL_CACHE[cache_key]

        try:
            importlib.import_module("ctranslate2")
        except (ImportError, ModuleNotFoundError) as exc:
            raise DependencyError("ctranslate2") from exc

        try:
            faster_whisper = importlib.import_module("faster_whisper")
        except (ImportError, ModuleNotFoundError) as exc:
            raise DependencyError("faster-whisper") from exc

        whisper_model = getattr(faster_whisper, "WhisperModel", None)
        if whisper_model is None:
            raise DependencyError("faster-whisper.WhisperModel")

        kwargs: dict[str, object] = {"device": self.device, "compute_type": self.compute_type}
        if self.model_download_root:
            kwargs["download_root"] = self.model_download_root

        try:
            model = whisper_model(self.model_name, **kwargs)
        except Exception as exc:
            _LOGGER.exception("Failed to load Whisper model %s", self.model_name)
            raise ModelLoadError(self.model_name, str(exc)) from exc

        _MODEL_CACHE[cache_key] = model
        _LOGGER.info("Loaded Whisper model %s on %s (%s)", self.model_name, self.device, self.compute_type)
        return model

    def transcribe(self, audio_path: str | Path, language: str | None = None) -> dict[str, Any]:
        path = Path(audio_path)
        if not path.exists() or not path.is_file():
            raise MissingAudioError(path)

        effective_language = language if language is not None else self.language

        try:
            segment_generator, info = self.model.transcribe(
                str(path),
                beam_size=self.beam_size,
                best_of=self.beam_size,
                vad_filter=self.vad_filter,
                language=effective_language,
            )
            normalized_segments: list[dict[str, float | str]] = []
            for segment in segment_generator:
                text = str(getattr(segment, "text", "")).strip()
                if not text:
                    continue
                normalized_segments.append({
                    "start": float(getattr(segment, "start", 0.0) or 0.0),
                    "end": float(getattr(segment, "end", 0.0) or 0.0),
                    "text": text,
                })
        except (MissingAudioError, UnsupportedModelError, DependencyError, ModelLoadError):
            raise
        except Exception as exc:
            _LOGGER.exception("Whisper transcription failed for %s", path)
            raise TranscriptionError(path, str(exc)) from exc

        detected_language = str(getattr(info, "language", effective_language or "") or "")
        info_duration = getattr(info, "duration", None)
        if info_duration is not None:
            duration = float(info_duration)
        elif normalized_segments:
            duration = float(normalized_segments[-1]["end"])
        else:
            duration = 0.0

        transcript = " ".join(str(segment["text"]) for segment in normalized_segments).strip()
        result = {
            "language": detected_language,
            "duration": duration,
            "segments": normalized_segments,
            "transcript": transcript,
            "engine": self.metadata(),
        }
        _LOGGER.info("Transcription completed for %s with %d segments", path.name, len(normalized_segments))
        return result

    def metadata(self) -> dict[str, str]:
        try:
            engine_version = importlib.metadata.version("faster-whisper")
        except importlib.metadata.PackageNotFoundError:
            engine_version = "unknown"
        return {
            "model": self.model_name,
            "device": self.device,
            "compute_type": self.compute_type,
            "backend": "faster-whisper",
            "engine_version": engine_version,
        }
