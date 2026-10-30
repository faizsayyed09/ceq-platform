import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "components" / "CALL AUDITS" / "v2" / "modules" / "transcript_builder.py"
SPEC = importlib.util.spec_from_file_location("v2_transcript_builder_module", MODULE_PATH)
transcript_builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transcript_builder)


def test_segment_normalization_and_transcript_contract():
    result = transcript_builder.build_transcript([
        {"id": 7, "start": "0.25", "end": "2.5", "text": "  Hello world  ", "confidence": 0.91},
        {"start": None, "end": None, "text": "   ", "confidence": 0.5},
        {"id": 9, "start": 3, "end": 4, "text": "How can I help?", "avg_logprob": -0.2},
    ])

    assert result["transcript"] == "Hello world How can I help?"
    assert result["text"] == result["transcript"]
    assert result["duration"] == 4.0
    assert result["segments"] == [
        {
            "id": 7,
            "start": 0.25,
            "end": 2.5,
            "start_timestamp": "00:00",
            "end_timestamp": "00:02",
            "text": "Hello world",
            "speaker": None,
            "confidence": 0.91,
        },
        {
            "id": 9,
            "start": 3.0,
            "end": 4.0,
            "start_timestamp": "00:03",
            "end_timestamp": "00:04",
            "text": "How can I help?",
            "speaker": None,
            "confidence": -0.2,
            "avg_logprob": -0.2,
        },
    ]
    assert result["metrics"]["segment_count"] == 2
    assert result["metrics"]["word_count"] == 6


def test_timestamp_formatting():
    assert transcript_builder.format_timestamp(2.5) == "00:02"
    assert transcript_builder.format_timestamp(65) == "01:05"
    assert transcript_builder.format_timestamp(3661) == "01:01:01"
    assert transcript_builder.format_timestamp(3661, include_milliseconds=True) == "01:01:01.000"
    assert transcript_builder.format_timestamp(-1) == "00:00"
    assert transcript_builder.format_timestamp("invalid") == "00:00"


def test_speaker_attribution_support_and_utterance_grouping():
    result = transcript_builder.build_transcript([
        {"id": 1, "start": 0, "end": 1, "text": "Good morning", "speaker": "agent"},
        {"id": 2, "start": 1, "end": 2, "text": "How can I help?", "speaker": "agent"},
        {"id": 3, "start": 2, "end": 3, "text": "My password is locked", "speaker": "caller"},
    ])

    assert result["utterance_count"] == 2
    assert result["utterances"][0] == {
        "start": 0.0,
        "end": 2.0,
        "speaker": "agent",
        "text": "Good morning How can I help?",
        "segments": [1, 2],
    }
    assert result["utterances"][1]["speaker"] == "caller"


def test_speaker_attribution_mapping_and_callable():
    segments = [
        {"id": "a", "start": 0, "end": 1, "text": "One"},
        {"id": "b", "start": 1, "end": 2, "text": "Two"},
    ]

    mapped = transcript_builder.build_transcript(segments, speaker_attribution={"a": "agent", "b": "caller"})
    assert [segment["speaker"] for segment in mapped["segments"]] == ["agent", "caller"]

    called = transcript_builder.build_transcript(segments, speaker_attribution=lambda source: "agent")
    assert {segment["speaker"] for segment in called["segments"]} == {"agent"}


def test_confidence_and_transcript_metrics():
    result = transcript_builder.build_transcript([
        {"start": 0, "end": 2, "text": "Clear", "confidence": 0.9},
        {"start": 2, "end": 5, "text": "Uncertain", "confidence": 0.4, "low_conf": True},
    ])

    assert result["metrics"] == {
        "segment_count": 2,
        "utterance_count": 1,
        "word_count": 2,
        "character_count": 15,
        "duration": 5.0,
        "average_confidence": 0.65,
        "uncertain_segment_count": 1,
    }


def test_empty_segments_return_zero_metrics():
    result = transcript_builder.build_transcript(None)

    assert result["transcript"] == ""
    assert result["segments"] == []
    assert result["utterances"] == []
    assert result["duration"] == 0.0
    assert result["metrics"]["segment_count"] == 0
    assert result["metrics"]["average_confidence"] is None
