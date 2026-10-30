from __future__ import annotations


def detect_silence_segments(
    audio_path: str,
    segments: list[dict] | None = None,
    minimum_gap_seconds: float = 1.0,
    hold_threshold_seconds: float = 30.0,
    long_silence_threshold_seconds: float = 10.0,
) -> list[dict]:
    """Classify dead-air intervals without inventing caller/agent state."""
    rows = list(segments or [])
    if not rows:
        return []

    events: list[dict] = []
    ordered = sorted(rows, key=lambda row: float(row.get("start", 0.0)))
    for previous, current in zip(ordered, ordered[1:]):
        gap_start = float(previous.get("end", previous.get("start", 0.0)))
        gap_end = float(current.get("start", gap_start))
        duration = max(0.0, gap_end - gap_start)
        threshold = min(minimum_gap_seconds, long_silence_threshold_seconds)
        if duration < threshold:
            continue
        if duration >= hold_threshold_seconds:
            event_type = "hold"
        elif duration >= long_silence_threshold_seconds:
            event_type = "long_silence"
        else:
            event_type = "silence_gap"
        events.append({
            "start": gap_start,
            "end": gap_end,
            "duration": round(duration, 1),
            "duration_seconds": round(duration, 1),
            "source": "silence",
            "type": event_type,
        })

    return events


def summarize_silence(events: list[dict]) -> dict:
    holds = [event for event in events if event.get("type") == "hold"]
    long_silences = [event for event in events if event.get("type") == "long_silence"]
    return {
        "total_hold_seconds": round(sum(float(event["duration_seconds"]) for event in holds), 1),
        "longest_hold_seconds": round(max((float(event["duration_seconds"]) for event in holds), default=0.0), 1),
        "total_long_silence_seconds": round(sum(float(event["duration_seconds"]) for event in long_silences), 1),
    }
