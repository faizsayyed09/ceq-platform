from __future__ import annotations

from lfx.custom.custom_component.component import Component
from lfx.io import FileInput, StrInput, BoolInput, Output
from lfx.schema.data import Data

from services.transcription import TranscriptionService


class CustomComponent(Component):
    display_name = "CEQ QA Transcriber V2"
    description = "Runtime-neutral transcription adapter using the CEQ TranscriptionService."

    inputs = [
        FileInput(name="audio_file", display_name="Audio File", required=True),
        StrInput(name="protection_mode", display_name="PHI Protection Mode", value="AUDIT_MODE"),
        BoolInput(name="redact_pii", display_name="Deprecated legacy PII flag", value=False, advanced=True),
    ]

    outputs = [Output(display_name="Transcript", name="transcript", method="transcribe")]

    def transcribe(self) -> Data:
        service = TranscriptionService()
        legacy_redact = None if not bool(self.redact_pii) else True
        result = service.transcribe(
            str(self.audio_file),
            protection_mode=str(self.protection_mode or "AUDIT_MODE"),
            redact=legacy_redact,
        )
        return Data(data=result)
