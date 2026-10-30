from __future__ import annotations

import logging
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


_LOGGER = logging.getLogger(__name__)
_DEFAULT_DEAD_AIR_THRESHOLD = 30.0
_DEFAULT_HOLD_UPDATE_THRESHOLD = 120.0

_HOLD_REQUEST_RE = re.compile(
    r"(?:place|put|keep|take).{0,30}on.{0,15}hold|hold the line|please hold",
    re.IGNORECASE,
)
_HOLD_RETURN_RE = re.compile(
    r"(?:thank you for (?:holding|waiting)|thanks for (?:holding|waiting)|still with me|still there|i.?m back)",
    re.IGNORECASE,
)
_CALLER_PAUSE_RE = re.compile(
    r"(?:hold on|can you hold|give me (?:a|one|two|\d+)\s*(?:sec|second|minute|min|moment)|one (?:sec|second|moment|minute)|bear with me|let me (?:check|get|find|grab|look))",
    re.IGNORECASE,
)


class SilenceDetectionError(Exception):
    """Base exception for structured silence analysis failures."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        self.code = code
        self.message = message
        self.details = dict(details or {})
        super().__init__(message)


class InvalidSegmentsError(SilenceDetectionError):
    def __init__(self, detail: str) -> None:
        super().__init__("invalid_segments", "Transcript segments are invalid", details={"detail": detail})


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _speaker(segment: Mapping[str, Any]) -> str:
    value = segment.get("speaker", segment.get("speaker_label", segment.get("speaker_id")))
    if value is None:
        return ""
    return str(value).strip().lower()


def _normalize_segments(segments: Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    if segments is None:
        return []
    if isinstance(segments, (str, bytes, Mapping)):
        raise InvalidSegmentsError("segments must be an iterable of mappings, not a single mapping or string")
    try:
        iterator = iter(segments)
    except TypeError as exc:
        raise InvalidSegmentsError("segments must be iterable") from exc

    normalized: list[dict[str, Any]] = []
    for index, source in enumerate(iterator):
        if not isinstance(source, Mapping):
            raise InvalidSegmentsError(f"segment at index {index} must be a mapping")
        text = str(source.get("text", "")).strip()
        start = max(0.0, _safe_float(source.get("start", 0.0)))
        end = max(start, _safe_float(source.get("end", start), start))
        normalized.append({
            "id": source.get("id", index + 1),
            "start": start,
            "end": end,
            "text": text,
            "speaker": _speaker(source),
            "caller_requested_pause": bool(source.get("caller_requested_pause", False)),
            "hold_marker": bool(source.get("hold_marker", False)),
        })
    return sorted(normalized, key=lambda row: (row["start"], row["end"]))


def _caller_pause_segments(
    segments: Sequence[Mapping[str, Any]],
    caller_requested_pauses: Iterable[Mapping[str, Any]] | None = None,
) -> list[tuple[float, float]]:
    ranges: list[tuple[float, float]] = []
    if caller_requested_pauses:
        for item in caller_requested_pauses:
            if not isinstance(item, Mapping):
                raise InvalidSegmentsError("caller_requested_pauses must contain mappings")
            start = _safe_float(item.get("start", item.get("requested_at", 0.0)), -1.0)
            end = _safe_float(item.get("end", start if start >= 0 else 0.0), start if start >= 0 else 0.0)
            if start >= 0 and end >= start:
                ranges.append((start, end))

    for segment in segments:
        speaker = _speaker(segment)
        if segment["caller_requested_pause"] or (
            speaker in {"caller", "customer", "user"}
            and _CALLER_PAUSE_RE.search(str(segment["text"]))
        ):
            ranges.append((segment["start"], segment["end"] + 25.0))
    return ranges


def _overlaps_pause(start: float, end: float, pause_ranges: Sequence[tuple[float, float]]) -> bool:
    return any(start < pause_end and end > pause_start for pause_start, pause_end in pause_ranges)


def _ranges_overlap(start: float, end: float, ranges: Sequence[tuple[float, float]]) -> bool:
    return any(start < range_end and end > range_start for range_start, range_end in ranges)


def _hold_ranges(segments: Sequence[Mapping[str, Any]]) -> list[tuple[float, float]]:
    ranges: list[tuple[float, float]] = []
    for index, segment in enumerate(segments):
        if not (_HOLD_REQUEST_RE.search(str(segment["text"])) or segment["hold_marker"]):
            continue
        if _speaker(segment) in {"caller", "customer", "user"}:
            continue
        hold_start = segment["end"]
        hold_end = hold_start
        for later in segments[index + 1:]:
            if _HOLD_RETURN_RE.search(str(later["text"])):
                hold_end = later["start"]
                break
        if hold_end <= hold_start and index + 1 < len(segments):
            hold_end = segments[index + 1]["start"]
        if hold_end > hold_start:
            ranges.append((hold_start, hold_end))
    return ranges


def detect_overlaps(segments: Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Return overlap intervals between segments from different speakers."""
    rows = _normalize_segments(segments)
    overlaps: list[dict[str, Any]] = []
    for index, left in enumerate(rows):
        for right in rows[index + 1:]:
            if right["start"] >= left["end"]:
                break
            left_speaker = _speaker(left)
            right_speaker = _speaker(right)
            if left_speaker and right_speaker and left_speaker == right_speaker:
                continue
            overlap_start = max(left["start"], right["start"])
            overlap_end = min(left["end"], right["end"])
            duration = overlap_end - overlap_start
            if duration > 0:
                overlaps.append({
                    "start": overlap_start,
                    "end": overlap_end,
                    "duration": round(duration, 3),
                    "speakers": [left_speaker or "unknown", right_speaker or "unknown"],
                    "segment_ids": [left["id"], right["id"]],
                })
    return overlaps


def detect_dead_air(
    segments: Iterable[Mapping[str, Any]] | None,
    threshold_seconds: float = _DEFAULT_DEAD_AIR_THRESHOLD,
    caller_requested_pauses: Iterable[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Detect material gaps, excluding holds and caller-requested pauses."""
    threshold = _safe_float(threshold_seconds, _DEFAULT_DEAD_AIR_THRESHOLD)
    if threshold < 0:
        raise SilenceDetectionError("invalid_threshold", "Dead-air threshold cannot be negative", details={"threshold": threshold})

    rows = _normalize_segments(segments)
    if not rows:
        return []

    pause_ranges = _caller_pause_segments(rows, caller_requested_pauses)
    hold_ranges = _hold_ranges(rows)
    dead_air: list[dict[str, Any]] = []
    for previous, current in zip(rows, rows[1:]):
        gap_start = previous["end"]
        gap_end = current["start"]
        duration = gap_end - gap_start
        if gap_end <= gap_start or duration < threshold:
            continue
        if _ranges_overlap(gap_start, gap_end, hold_ranges):
            continue
        if _overlaps_pause(gap_start, gap_end, pause_ranges):
            continue
        dead_air.append({
            "start": gap_start,
            "end": gap_end,
            "duration": round(duration, 3),
            "duration_seconds": round(duration, 3),
            "type": "dead_air",
            "source": "silence",
        })
    return dead_air


def detect_hold_events(
    segments: Iterable[Mapping[str, Any]] | None,
    caller_requested_pauses: Iterable[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Detect hold intervals from explicit hold language and return language."""
    rows = _normalize_segments(segments)
    if not rows:
        return []
    pause_ranges = _caller_pause_segments(rows, caller_requested_pauses)
    hold_events: list[dict[str, Any]] = []

    for index, segment in enumerate(rows):
        if not (_HOLD_REQUEST_RE.search(str(segment["text"])) or segment["hold_marker"]):
            continue
        if _speaker(segment) in {"caller", "customer", "user"}:
            continue
        start = segment["end"]
        end = start
        for later in rows[index + 1:]:
            if _HOLD_RETURN_RE.search(str(later["text"])):
                end = later["start"]
                break
        if end <= start and index + 1 < len(rows):
            end = rows[index + 1]["start"]
        if end <= start or _overlaps_pause(start, end, pause_ranges):
            continue
        duration = end - start
        hold_events.append({
            "start": start,
            "end": end,
            "duration": round(duration, 3),
            "duration_seconds": round(duration, 3),
            "type": "hold",
            "source": "transcript",
            "segment_id": segment["id"],
        })
    return hold_events


def analyze_update_intervals(
    segments: Iterable[Mapping[str, Any]] | None,
    threshold_seconds: float = _DEFAULT_HOLD_UPDATE_THRESHOLD,
    caller_requested_pauses: Iterable[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Find gaps between agent updates that exceed the hold-update threshold."""
    threshold = _safe_float(threshold_seconds, _DEFAULT_HOLD_UPDATE_THRESHOLD)
    if threshold < 0:
        raise SilenceDetectionError("invalid_threshold", "Update threshold cannot be negative", details={"threshold": threshold})

    rows = _normalize_segments(segments)
    if not rows:
        return []
    pause_ranges = _caller_pause_segments(rows, caller_requested_pauses)
    hold_ranges = _hold_ranges(rows)
    agent_segments = [row for row in rows if _speaker(row) in {"agent", "representative", "advisor"}]
    gaps: list[dict[str, Any]] = []
    for previous, current in zip(agent_segments, agent_segments[1:]):
        start = previous["end"]
        end = current["start"]
        duration = max(0.0, end - start)
        if duration < threshold:
            continue
        if _ranges_overlap(start, end, hold_ranges) or _overlaps_pause(start, end, pause_ranges):
            continue
        gaps.append({
            "start": start,
            "end": end,
            "duration": round(duration, 3),
            "duration_seconds": round(duration, 3),
            "type": "update_gap",
        })
    return gaps


def analyze_silence(
    segments: Iterable[Mapping[str, Any]] | None = None,
    dead_air_threshold_seconds: float = _DEFAULT_DEAD_AIR_THRESHOLD,
    hold_update_threshold_seconds: float = _DEFAULT_HOLD_UPDATE_THRESHOLD,
    caller_requested_pauses: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the structured V2 silence-analysis contract."""
    rows = _normalize_segments(segments)
    dead_air = detect_dead_air(rows, dead_air_threshold_seconds, caller_requested_pauses)
    hold_events = detect_hold_events(rows, caller_requested_pauses)
    update_gaps = analyze_update_intervals(rows, hold_update_threshold_seconds, caller_requested_pauses)
    long_silence_events = [event for event in dead_air if event["duration_seconds"] >= dead_air_threshold_seconds]
    result = {
        "hold_events": hold_events,
        "long_silence_events": long_silence_events,
        "update_gaps": update_gaps,
        "metrics": {
            "dead_air_seconds": round(sum(event["duration_seconds"] for event in dead_air), 3),
            "hold_seconds": round(sum(event["duration_seconds"] for event in hold_events), 3),
            "hold_count": len(hold_events),
            "silence_count": len(long_silence_events),
        },
    }
    _LOGGER.info("Silence analysis completed: %d holds, %d long silences", len(hold_events), len(long_silence_events))
    return result


def detect_silence_segments(
    audio_path: str,
    segments: list[dict] | None = None,
    minimum_gap_seconds: float = 1.0,
    hold_threshold_seconds: float = 30.0,
    long_silence_threshold_seconds: float = 10.0,
) -> list[dict]:
    """Compatibility wrapper for the existing V2 service."""
    rows = _normalize_segments(segments)
    events: list[dict] = []
    for previous, current in zip(rows, rows[1:]):
        gap_start = previous["end"]
        gap_end = current["start"]
        duration = max(0.0, gap_end - gap_start)
        threshold = min(_safe_float(minimum_gap_seconds, 1.0), _safe_float(long_silence_threshold_seconds, 10.0))
        if duration < threshold:
            continue
        if duration >= _safe_float(hold_threshold_seconds, 30.0):
            event_type = "hold"
        elif duration >= _safe_float(long_silence_threshold_seconds, 10.0):
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
        "total_hold_seconds": round(sum(_safe_float(event.get("duration_seconds")) for event in holds), 1),
        "longest_hold_seconds": round(max((_safe_float(event.get("duration_seconds")) for event in holds), default=0.0), 1),
        "total_long_silence_seconds": round(sum(_safe_float(event.get("duration_seconds")) for event in long_silences), 1),
    }
