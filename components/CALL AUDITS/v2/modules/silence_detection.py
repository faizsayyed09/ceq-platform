from __future__ import annotations


def detect_silence_segments(
    audio_path: str,
    segments: list[dict] | None = None,
    minimum_gap_seconds: float = 1.0,
) -> list[dict]:
    """Build dead-air intervals from segment boundaries and optional external diarization."""
    rows = list(segments or [])
    if not rows:
        return []

    events: list[dict] = []
    ordered = sorted(rows, key=lambda row: float(row.get("start", 0.0)))
    for previous, current in zip(ordered, ordered[1:]):
        gap_start = float(previous.get("end", previous.get("start", 0.0)))
        gap_end = float(current.get("start", gap_start))
        duration = max(0.0, gap_end - gap_start)
        if duration >= minimum_gap_seconds:
            events.append({
                "start": gap_start,
                "end": gap_end,
                "duration_seconds": duration,
                "type": "silence_gap",
            })

    return events
