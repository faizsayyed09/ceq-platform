from __future__ import annotations

from pathlib import Path


class WhisperEngine:
    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8") -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("faster-whisper is not installed in the container image") from exc
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio_path: str | Path) -> list[dict]:
        segments, _ = self.model.transcribe(str(audio_path), beam_size=5, vad_filter=True)
        return [{"start": float(segment.start), "end": float(segment.end), "text": segment.text.strip()} for segment in segments]
