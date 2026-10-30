from __future__ import annotations

import logging
import os
import threading
from pathlib import Path


_LOGGER = logging.getLogger("ceq.transcription.whisper")
_MODEL_CACHE: dict[tuple[str, str, str, str | None], object] = {}
_MODEL_CACHE_LOCK = threading.Lock()


class WhisperEngine:
    def __init__(
        self,
        model_size: str = "large-v3-turbo",
        device: str = "cpu",
        compute_type: str = "int8",
        beam_size: int = 5,
        vad_filter: bool = True,
        model_download_root: str | Path | None = None,
    ) -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("faster-whisper is not installed in the container image") from exc

        self.model_name = model_size
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.vad_filter = vad_filter
        self.model_download_root = str(model_download_root or os.getenv("WHISPER_MODEL_CACHE", "")) or None
        cache_key = (model_size, device, compute_type, self.model_download_root)
        with _MODEL_CACHE_LOCK:
            if cache_key not in _MODEL_CACHE:
                kwargs: dict[str, object] = {"device": device, "compute_type": compute_type}
                if self.model_download_root:
                    kwargs["download_root"] = self.model_download_root
                _MODEL_CACHE[cache_key] = WhisperModel(model_size, **kwargs)
                _LOGGER.info("Loaded Whisper model %s on %s (%s)", model_size, device, compute_type)
            self.model = _MODEL_CACHE[cache_key]

    def transcribe(self, audio_path: str | Path, language: str | None = None) -> list[dict]:
        segments, info = self.model.transcribe(
            str(audio_path),
            beam_size=self.beam_size,
            best_of=self.beam_size,
            patience=1.0,
            temperature=0.0,
            vad_filter=self.vad_filter,
            vad_parameters={"threshold": 0.5, "min_silence_duration_ms": 500, "speech_pad_ms": 400},
            language=language,
            condition_on_previous_text=False,
            word_timestamps=True,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
        )

        rows: list[dict] = []
        for index, segment in enumerate(segments, start=1):
            words = []
            probabilities = []
            for word in getattr(segment, "words", None) or []:
                probability = float(getattr(word, "probability", 0.0) or 0.0)
                probabilities.append(probability)
                words.append({
                    "start": float(word.start), "end": float(word.end),
                    "text": str(word.word).strip(), "probability": probability,
                })
            avg_logprob = float(getattr(segment, "avg_logprob", 0.0) or 0.0)
            mean_probability = sum(probabilities) / len(probabilities) if probabilities else 1.0
            text = segment.text.strip()
            no_speech_probability = float(getattr(segment, "no_speech_prob", 0.0) or 0.0)
            compression_ratio = float(getattr(segment, "compression_ratio", 0.0) or 0.0)
            if not text:
                continue
            rows.append({
                "id": index,
                "start": float(segment.start),
                "end": float(segment.end),
                "text": text,
                "language": getattr(info, "language", None),
                "confidence": avg_logprob,
                "avg_logprob": round(avg_logprob, 3),
                "no_speech_prob": round(no_speech_probability, 3),
                "compression_ratio": round(compression_ratio, 3),
                "mean_word_prob": round(mean_probability, 3),
                "min_word_prob": round(min(probabilities), 3) if probabilities else 1.0,
                "low_conf": avg_logprob < -0.8 or mean_probability < 0.65,
                "words": words,
            })
        return rows

    def metadata(self) -> dict:
        import faster_whisper
        return {
            "model_name": self.model_name,
            "model_size": self.model_name,
            "device": self.device,
            "compute_type": self.compute_type,
            "beam_size": self.beam_size,
            "vad_filter": self.vad_filter,
            "implementation": "faster-whisper",
            "implementation_version": str(getattr(faster_whisper, "__version__", "unknown")),
        }
