from __future__ import annotations

from lfx.custom.custom_component.component import Component
from lfx.io import FileInput, BoolInput, Output
from lfx.schema.data import Data

from services.transcription import TranscriptionService


class CustomComponent(Component):
    display_name = "CEQ QA Transcriber V2"
    description = "Runtime-neutral transcription adapter using the CEQ TranscriptionService."

    inputs = [
        FileInput(name="audio_file", display_name="Audio File", required=True),
        BoolInput(name="redact_pii", display_name="Redact PII", value=True),
    ]

    outputs = [Output(display_name="Transcript", name="transcript", method="transcribe")]

    def transcribe(self) -> Data:
        service = TranscriptionService()
        result = service.transcribe(str(self.audio_file), redact=bool(self.redact_pii))
        return Data(data=result)
