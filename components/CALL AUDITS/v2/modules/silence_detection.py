from __future__ import annotations


def detect_silence_segments(audio_path: str) -> list[dict]:
    """Reserved for a runtime-neutral silence detector; the Whisper VAD step is authoritative in the current implementation."""
    return []
