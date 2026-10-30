from __future__ import annotations

from pathlib import Path

from .modules.service import TranscriptionService


class CEQTranscriberV2:
    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = None,
    ) -> None:
        self.service = TranscriptionService(
            model_size=model_size,
            device=device,
            compute_type=compute_type,
            language=language,
        )

    def transcribe(
        self,
        audio_path: str | Path,
        protection_mode: str = "AUDIT_MODE",
        redact: bool | None = None,
    ) -> dict:
        return self.service.transcribe(
            audio_path,
            protection_mode=protection_mode,
            redact=redact,
        )


def transcribe_audio(
    audio_path: str | Path,
    protection_mode: str = "AUDIT_MODE",
    redact: bool | None = None,
    model_size: str = "base",
    device: str = "cpu",
    compute_type: str = "int8",
    language: str | None = None,
) -> dict:
    return CEQTranscriberV2(
        model_size=model_size,
        device=device,
        compute_type=compute_type,
        language=language,
    ).transcribe(audio_path, protection_mode=protection_mode, redact=redact)
