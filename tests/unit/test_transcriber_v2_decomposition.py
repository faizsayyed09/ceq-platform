import importlib.util
from pathlib import Path

V2_MODULES = Path(__file__).resolve().parents[2] / "components" / "CALL AUDITS" / "v2" / "modules"


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, V2_MODULES / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


silence_detection = load_module("v2_silence_detection", "silence_detection.py")
detect_silence_segments = silence_detection.detect_silence_segments

transcript_builder = load_module("v2_transcript_builder", "transcript_builder.py")
build_transcript = transcript_builder.build_transcript


def test_silence_detection_only_reports_material_gaps():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "Hello"},
        {"start": 3.0, "end": 4.0, "text": "Continue"},
    ]

    events = detect_silence_segments("unused.wav", segments=segments, minimum_gap_seconds=1.0)

    assert len(events) == 1
    assert events[0]["start"] == 1.0
    assert events[0]["end"] == 3.0
    assert events[0]["type"] == "silence_gap"


def test_transcript_builder_groups_same_speaker_utterances():
    result = build_transcript([
        {"id": 1, "start": 0.0, "end": 0.8, "speaker": "agent", "text": "Good morning"},
        {"id": 2, "start": 0.9, "end": 1.5, "speaker": "agent", "text": "how can I help?"},
        {"id": 3, "start": 1.6, "end": 2.0, "speaker": "caller", "text": "Reset my password."},
    ])

    assert result["text"] == "Good morning how can I help? Reset my password."
    assert result["segment_count"] == 3
    assert result["utterance_count"] == 2
    assert result["utterances"][0]["speaker"] == "agent"


def test_silence_detection_classifies_hold_and_long_silence():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "Please hold"},
        {"start": 35.0, "end": 36.0, "text": "Still here"},
        {"start": 48.0, "end": 49.0, "text": "Thank you"},
    ]

    events = detect_silence_segments("unused.wav", segments=segments)

    assert [event["type"] for event in events] == ["hold", "long_silence"]


def test_phi_protection_preserves_operational_service_desk_data():
    from services.phi_protection import PhiProtectionService

    text = "Agent Jane Doe called caller John Smith at 555-123-4567 for ticket INC1234567 KB000123"
    result = PhiProtectionService("LLM_MODE").project(text)

    assert result["text"] == text
    assert result["findings"] == []


def test_phi_protection_detects_mrn_fin_and_medication_information():
    from services.phi_protection import PhiProtectionService

    text = "MRN 12345678 FIN 98765432 Medication insulin 10 units"
    result = PhiProtectionService("LLM_MODE").project(text)

    assert "[PHI_" in result["text"]
    assert {finding["category"] for finding in result["findings"]} >= {"mrn", "encounter", "clinical_detail"}
