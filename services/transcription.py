from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
from pathlib import Path

from modules.constants import MAX_AUDIO_DURATION_SECONDS, MAX_FILE_SIZE_MB
from modules.exceptions import CeqError, ValidationError
from services.phi_protection import PhiProtectionService


_LOGGER = logging.getLogger("ceq.transcription.service")
_MODEL_CACHE: dict[tuple[str, str, str, str | None], object] = {}
_MODEL_CACHE_LOCK = threading.Lock()
_ALLOWED_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wma", ".webm", ".mp4"}


class TranscriptionService:
    def __init__(
        self,
        model_size: str = "large-v3-turbo",
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
        if path.is_symlink():
            raise ValidationError("Symbolic-link audio paths are not allowed")
        if not path.is_file():
            raise ValidationError("Audio file does not exist")
        if path.suffix.lower() not in _ALLOWED_SUFFIXES:
            raise ValidationError("Unsupported audio file type")
        size_bytes = path.stat().st_size
        if size_bytes <= 0:
            raise ValidationError("Audio file is empty")
        if size_bytes > self.max_file_size_mb * 1024 * 1024:
            raise ValidationError(f"Audio exceeds {self.max_file_size_mb} MB limit")
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            raise CeqError("FFprobe is unavailable")
        try:
            result = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration,format_name:stream=codec_name,codec_type,channels,sample_rate", "-of", "json", str(path)],
                check=True, capture_output=True, text=True, timeout=30,
            )
            data = json.loads(result.stdout)
            duration = float(data["format"]["duration"])
            streams = data.get("streams", [])
            audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
        except (subprocess.SubprocessError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValidationError("Audio metadata could not be validated") from exc
        if duration <= 0:
            raise ValidationError("Audio duration is invalid")
        if duration > self.max_audio_duration_seconds:
            raise ValidationError(f"Audio duration exceeds {self.max_audio_duration_seconds} seconds")
        if not audio_streams:
            raise ValidationError("File contains no audio stream")
        return {"duration_seconds": round(duration, 3), "size_bytes": size_bytes}

    def _get_model(self):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise CeqError("faster-whisper is not installed in the runtime image") from exc
        import os
        download_root = os.getenv("WHISPER_MODEL_CACHE") or None
        cache_key = (self.model_size, self.device, self.compute_type, download_root)
        with _MODEL_CACHE_LOCK:
            if cache_key not in _MODEL_CACHE:
                kwargs: dict[str, object] = {"device": self.device, "compute_type": self.compute_type}
                if download_root:
                    kwargs["download_root"] = download_root
                _MODEL_CACHE[cache_key] = WhisperModel(self.model_size, **kwargs)
                _LOGGER.info("Loaded Whisper model %s on %s (%s)", self.model_size, self.device, self.compute_type)
            return _MODEL_CACHE[cache_key]

    def transcribe(
        self,
        audio_path: str | Path,
        protection_mode: str = "AUDIT_MODE",
        redact: bool | None = None,
    ) -> dict[str, object]:
        if redact is not None:
            protection_mode = "LLM_MODE" if redact else "OFF"
        phi_service = PhiProtectionService(protection_mode)
        validated = self.validate(audio_path)
        model = self._get_model()
        segments, info = model.transcribe(
            str(audio_path), beam_size=5, best_of=5, patience=1.0, temperature=0.0,
            vad_filter=True, vad_parameters={"threshold": 0.5, "min_silence_duration_ms": 500, "speech_pad_ms": 400},
            condition_on_previous_text=False, word_timestamps=True,
        )
        rows: list[dict[str, object]] = []
        for index, segment in enumerate(segments, start=1):
            text = segment.text.strip()
            if not text:
                continue
            words = []
            probabilities = []
            for word in getattr(segment, "words", None) or []:
                probability = float(getattr(word, "probability", 0.0) or 0.0)
                probabilities.append(probability)
                words.append({"start": float(word.start), "end": float(word.end), "text": str(word.word).strip(), "probability": probability})
            avg_logprob = float(getattr(segment, "avg_logprob", 0.0) or 0.0)
            mean_probability = sum(probabilities) / len(probabilities) if probabilities else 1.0
            rows.append({
                "id": index, "start": float(segment.start), "end": float(segment.end), "text": text,
                "language": getattr(info, "language", None), "confidence": avg_logprob,
                "avg_logprob": round(avg_logprob, 3), "no_speech_prob": round(float(getattr(segment, "no_speech_prob", 0.0) or 0.0), 3),
                "compression_ratio": round(float(getattr(segment, "compression_ratio", 0.0) or 0.0), 3),
                "mean_word_prob": round(mean_probability, 3), "low_conf": avg_logprob < -0.8 or mean_probability < 0.65,
                "words": words,
            })
        phi_result = phi_service.project_segments(rows, protection_mode)
        canonical_segments = phi_result["canonical_segments"]
        text = " ".join(str(row["text"]).strip() for row in canonical_segments if str(row.get("text", "")).strip()).strip()

        hold_events: list[dict[str, object]] = []
        long_silence_events: list[dict[str, object]] = []
        for previous, current in zip(canonical_segments, canonical_segments[1:]):
            gap_start = float(previous["end"])
            gap_end = float(current["start"])
            duration = max(0.0, gap_end - gap_start)
            if duration >= 30:
                hold_events.append({"start": gap_start, "end": gap_end, "duration": round(duration, 1), "duration_seconds": round(duration, 1), "source": "silence", "type": "hold"})
            elif duration >= 10:
                long_silence_events.append({"start": gap_start, "end": gap_end, "duration": round(duration, 1), "duration_seconds": round(duration, 1), "source": "silence", "type": "long_silence"})

        longest_hold = max((float(event["duration_seconds"] ) for event in hold_events), default=0.0)
        metrics = {
            "audio_duration_seconds": validated["duration_seconds"],
            "segment_count": len(canonical_segments),
            "utterance_count": len(canonical_segments),
            "hold_event_count": len(hold_events),
            "long_silence_event_count": len(long_silence_events),
            "total_hold_seconds": round(sum(float(event["duration_seconds"] ) for event in hold_events), 1),
            "longest_hold_seconds": round(longest_hold, 1),
            "total_long_silence_seconds": round(sum(float(event["duration_seconds"] ) for event in long_silence_events), 1),
        }
        return {
            "transcript": text,
            "segments": canonical_segments,
            "hold_events": hold_events,
            "long_silence_events": long_silence_events,
            "metrics": metrics,
            "phi_findings": phi_result["findings"],
            "protected_text": phi_result["protected_text"],
            "protected_segments": phi_result["protected_segments"],
            "phi_protection": {"mode": phi_result["mode"], "categories": phi_result["phi_categories"], "finding_count": len(phi_result["findings"])},
            "transcription_engine": {"model_name": self.model_size, "model_size": self.model_size, "device": self.device, "compute_type": self.compute_type, "implementation": "faster-whisper"},
            **validated,
        }
