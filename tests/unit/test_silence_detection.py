import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "components" / "CALL AUDITS" / "v2" / "modules" / "silence_detection.py"
SPEC = importlib.util.spec_from_file_location("v2_silence_detection_phase4", MODULE_PATH)
silence_detection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(silence_detection)


def test_dead_air_detection_excludes_short_gaps():
    segments = [
        {"start": 0, "end": 2, "text": "Hello", "speaker": "agent"},
        {"start": 35, "end": 37, "text": "Are you there?", "speaker": "agent"},
    ]

    result = silence_detection.detect_dead_air(segments)

    assert result == [{
        "start": 2.0,
        "end": 35.0,
        "duration": 33.0,
        "duration_seconds": 33.0,
        "type": "dead_air",
        "source": "silence",
    }]


def test_hold_detection_from_explicit_hold_language():
    segments = [
        {"id": 1, "start": 0, "end": 2, "text": "Please hold while I check", "speaker": "agent"},
        {"id": 2, "start": 40, "end": 42, "text": "Thank you for holding", "speaker": "agent"},
    ]

    result = silence_detection.detect_hold_events(segments)

    assert len(result) == 1
    assert result[0]["start"] == 2.0
    assert result[0]["end"] == 40.0
    assert result[0]["duration"] == 38.0
    assert result[0]["type"] == "hold"


def test_hold_marker_support():
    result = silence_detection.detect_hold_events([
        {"id": 4, "start": 10, "end": 12, "text": "Checking", "speaker": "agent", "hold_marker": True},
        {"id": 5, "start": 50, "end": 51, "text": "Back now", "speaker": "agent"},
    ])
    assert len(result) == 1
    assert result[0]["duration"] == 38.0


def test_update_interval_detection():
    segments = [
        {"start": 0, "end": 1, "text": "Let me start", "speaker": "agent"},
        {"start": 125, "end": 126, "text": "Here is an update", "speaker": "agent"},
    ]

    result = silence_detection.analyze_update_intervals(segments)

    assert len(result) == 1
    assert result[0]["start"] == 1.0
    assert result[0]["end"] == 125.0
    assert result[0]["duration"] == 124.0


def test_caller_requested_pause_is_excluded():
    segments = [
        {"start": 0, "end": 2, "text": "Give me one moment to find it", "speaker": "caller"},
        {"start": 40, "end": 42, "text": "Okay, I am ready", "speaker": "caller"},
    ]

    result = silence_detection.detect_dead_air(segments)

    assert result == []


def test_explicit_caller_requested_pause_is_excluded():
    segments = [
        {"start": 0, "end": 2, "text": "Starting", "speaker": "caller"},
        {"start": 45, "end": 46, "text": "Continue", "speaker": "caller"},
    ]
    pauses = [{"start": 0, "end": 10, "caller_said": "Please give me a moment"}]

    result = silence_detection.detect_dead_air(segments, caller_requested_pauses=pauses)

    assert result == []


def test_overlap_detection():
    segments = [
        {"id": 1, "start": 0, "end": 5, "text": "Agent speaking", "speaker": "agent"},
        {"id": 2, "start": 3, "end": 7, "text": "Caller speaking", "speaker": "caller"},
        {"id": 3, "start": 7, "end": 8, "text": "Agent continues", "speaker": "agent"},
    ]

    result = silence_detection.detect_overlaps(segments)

    assert len(result) == 1
    assert result[0]["start"] == 3.0
    assert result[0]["end"] == 5.0
    assert result[0]["duration"] == 2.0
    assert result[0]["speakers"] == ["agent", "caller"]


def test_empty_transcript_contract():
    result = silence_detection.analyze_silence([])

    assert result == {
        "hold_events": [],
        "long_silence_events": [],
        "update_gaps": [],
        "metrics": {
            "dead_air_seconds": 0.0,
            "hold_seconds": 0.0,
            "hold_count": 0,
            "silence_count": 0,
        },
    }


def test_analysis_metrics_contract():
    segments = [
        {"id": 1, "start": 0, "end": 2, "text": "Please hold", "speaker": "agent"},
        {"id": 2, "start": 35, "end": 36, "text": "Thank you for holding", "speaker": "agent"},
        {"id": 3, "start": 70, "end": 72, "text": "Continue", "speaker": "agent"},
    ]

    result = silence_detection.analyze_silence(segments)

    assert result["metrics"]["hold_count"] == 1
    assert result["metrics"]["hold_seconds"] == 33.0
    assert len(result["hold_events"])


def test_invalid_segments_raise_structured_error():
    with pytest.raises(silence_detection.InvalidSegmentsError) as exc:
        silence_detection.detect_dead_air(["not a segment"])

    assert exc.value.code == "invalid_segments"


def test_compatibility_wrapper_is_preserved():
    result = silence_detection.detect_silence_segments(
        "unused.wav",
        segments=[{"start": 0, "end": 1, "text": "Hello"}, {"start": 35, "end": 36, "text": "Still here"}],
    )
    assert result[0]["type"] == "hold"
