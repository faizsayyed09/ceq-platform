from __future__ import annotations

from pathlib import Path


class WhisperEngine:
    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        beam_size: int = 5,
        vad_filter: bool = True,
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
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio_path: str | Path, language: str | None = None) -> list[dict]:
        segments, info = self.model.transcribe(
            str(audio_path),
            beam_size=self.beam_size,
            vad_filter=self.vad_filter,
            language=language,
        )
        return [
            {
                "id": index + 1,
                "start": float(segment.start),
                "end": float(segment.end),
                "text": segment.text.strip(),
                "language": getattr(info, "language", None),
                "confidence": float(getattr(segment, "avg_logprob", 0.0)),
            }
            for index, segment in enumerate(segments)
        ]

    def metadata(self) -> dict:
        return {
            "model_name": self.model_name,
            "device": self.device,
            "compute_type": self.compute_type,
            "beam_size": self.beam_size,
            "vad_filter": self.vad_filter,
            "implementation": "faster-whisper",
        }
