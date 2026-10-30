from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from typing import Any


def format_timestamp(seconds: float | int | str, include_milliseconds: bool = False) -> str:
    """Format a non-negative duration as MM:SS or HH:MM:SS."""
    try:
        value = max(0.0, float(seconds))
    except (TypeError, ValueError):
        value = 0.0
    if not math.isfinite(value):
        value = 0.0

    total_milliseconds = round(value * 1000)
    total_seconds = total_milliseconds // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, whole_seconds = divmod(remainder, 60)
    milliseconds = total_milliseconds % 1000

    base = f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}" if hours else f"{minutes:02d}:{whole_seconds:02d}"
    if include_milliseconds:
        return f"{base}.{milliseconds:03d}"
    return base


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _resolve_speaker(
    source: Mapping[str, Any],
    index: int,
    row_id: Any,
    attribution: Mapping[Any, Any] | Callable[[Mapping[str, Any], int], Any] | None,
) -> str | None:
    if callable(attribution):
        try:
            speaker = attribution(source)
        except TypeError:
            try:
                speaker = attribution(source, index)
            except (TypeError, ValueError):
                speaker = None
        except ValueError:
            speaker = None
    elif isinstance(attribution, Mapping):
        speaker = attribution.get(row_id, attribution.get(index + 1, None))
    else:
        speaker = source.get("speaker", source.get("speaker_label", source.get("speaker_id")))

    if speaker is None:
        return None
    normalized = str(speaker).strip()
    return normalized if normalized else None


def normalize_segment(
    source: Mapping[str, Any],
    index: int,
    speaker_attribution: Mapping[Any, Any] | Callable[[Mapping[str, Any], int], Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(source, Mapping):
        return None

    text = str(source.get("text", "")).strip()
    if not text:
        return None

    row_id = source.get("id", index + 1)
    start = _safe_float(source.get("start", 0.0))
    end = _safe_float(source.get("end", start), start)
    end = max(start, end)

    confidence = source.get("confidence")
    if confidence is None:
        confidence = source.get("mean_word_prob", source.get("avg_logprob"))
    row: dict[str, Any] = {
        "id": row_id,
        "start": start,
        "end": end,
        "start_timestamp": format_timestamp(start),
        "end_timestamp": format_timestamp(end),
        "text": text,
        "speaker": _resolve_speaker(source, index, row_id, speaker_attribution),
    }

    if confidence is not None:
        row["confidence"] = _safe_float(confidence, 0.0)
    for key in ("words", "language", "uncertain", "hold_marker", "low_conf", "avg_logprob", "no_speech_prob", "compression_ratio", "mean_word_prob"):
        if key in source:
            row[key] = source[key]
    return row


def build_transcript(
    segments: Iterable[dict] | None,
    speaker_attribution: Mapping[Any, Any] | Callable[[Mapping[str, Any], int], Any] | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for index, source in enumerate(segments or []):
        row = normalize_segment(source, index, speaker_attribution)
        if row is not None:
            rows.append(row)

    utterances: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in rows:
        if current and current["speaker"] == row["speaker"]:
            current["end"] = row["end"]
            current["text"] = f'{current["text"].rstrip()} {row["text"]}'.strip()
            current["segments"].append(row["id"])
        else:
            if current:
                utterances.append(current)
            current = {
                "start": row["start"],
                "end": row["end"],
                "speaker": row["speaker"],
                "text": row["text"],
                "segments": [row["id"]],
            }
    if current:
        utterances.append(current)

    transcript = " ".join(row["text"] for row in rows).strip()
    duration = max((row["end"] for row in rows), default=0.0)
    confidence_values = [
        _safe_float(row["confidence"])
        for row in rows
        if "confidence" in row
    ]
    average_confidence = round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else None
    metrics: dict[str, Any] = {
        "segment_count": len(rows),
        "utterance_count": len(utterances),
        "word_count": len(transcript.split()) if transcript else 0,
        "character_count": len(transcript),
        "duration": duration,
        "average_confidence": average_confidence,
        "uncertain_segment_count": sum(bool(row.get("uncertain") or row.get("low_conf")) for row in rows),
    }

    return {
        "transcript": transcript,
        "text": transcript,
        "segments": rows,
        "utterances": utterances,
        "duration": duration,
        "metrics": metrics,
        "segment_count": len(rows),
        "utterance_count": len(utterances),
    }
