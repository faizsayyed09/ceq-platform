import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "components" / "CALL AUDITS" / "v2" / "modules" / "phi_protection.py"
SPEC = importlib.util.spec_from_file_location("v2_phi_protection_phase5", MODULE_PATH)
phi_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = phi_module
SPEC.loader.exec_module(phi_module)

PhiProtectionService = phi_module.PhiProtectionService


def test_mrn_detection_and_redaction():
    text = "Patient MRN: A123456 is on the account."
    result = PhiProtectionService("AUDIT_MODE").protect(text)

    assert "[PHI_MRN]" in result["transcript_clean"]
    assert result["phi_findings"] == [{"type": "MRN", "value_type": "PHI", "offset": 8}]


def test_dob_detection():
    result = PhiProtectionService("LLM_MODE").protect("DOB: 04/15/1985")

    assert "[PHI_DOB]" in result["transcript_clean"]
    assert result["phi_findings"][0]["type"] == "DOB"


def test_ssn_detection():
    result = PhiProtectionService("LLM_MODE").protect("Patient SSN is 123-45-6789")

    assert "123-45-6789" not in result["transcript_clean"]
    assert result["phi_findings"][0]["type"] == "SSN"


def test_insurance_id_detection():
    result = PhiProtectionService("AUDIT_MODE").protect("Insurance ID: PLAN9876543")

    assert "PLAN9876543" not in result["transcript_clean"]
    assert result["phi_findings"][0]["type"] == "INSURANCE_ID"


def test_fin_detection():
    result = PhiProtectionService("AUDIT_MODE").protect("FIN: HOSP123456")

    assert "HOSP123456" not in result["transcript_clean"]
    assert result["phi_findings"][0]["type"] == "FIN"


def test_mixed_transcript_preserves_operational_data():
    text = "Agent Jane Doe documented INC123456 for caller John Smith. Patient MRN: A123456 and patient account ACCT987654 were noted."
    result = PhiProtectionService("AUDIT_MODE").protect(text)

    assert "Agent Jane Doe" in result["transcript_clean"]
    assert "INC123456" in result["transcript_clean"]
    assert "caller John Smith" in result["transcript_clean"]
    assert "MRN" not in result["transcript_clean"] or "[PHI_MRN]" in result["transcript_clean"]
    assert {finding["type"] for finding in result["phi_findings"]} >= {"MRN", "PATIENT_ACCOUNT"}


def test_off_mode_has_no_redaction_or_findings():
    text = "Patient MRN: A123456 and DOB: 04/15/1985"
    result = PhiProtectionService("OFF").protect(text)

    assert result == {"transcript": text, "transcript_clean": text, "phi_findings": []}


def test_audit_mode_redacts_phi_only():
    text = "Agent Jane Doe ticket INC123456 diagnosis diabetes for patient MRN: A123456"
    result = PhiProtectionService("AUDIT_MODE").protect(text)

    assert "Agent Jane Doe" in result["transcript_clean"]
    assert "INC123456" in result["transcript_clean"]
    assert "[PHI_DIAGNOSIS]" in result["transcript_clean"] or "[PHI_MRN]" in result["transcript_clean"]


def test_llm_mode_redacts_phi_before_external_use():
    text = "Agent Jane documented ticket INC123456. Medication: insulin 10 units."
    result = PhiProtectionService("LLM_MODE").protect(text)

    assert "INC123456" in result["transcript_clean"]
    assert "Agent Jane" in result["transcript_clean"]
    assert "insulin 10 units" not in result["transcript_clean"]


def test_strict_mode_redacts_phi_and_configured_operational_data():
    text = "Agent Jane Doe at 555-123-4567 documented INC123456 for patient SSN 123-45-6789"
    result = PhiProtectionService("STRICT").protect(text)

    assert "555-123-4567" not in result["transcript_clean"]
    assert "INC123456" not in result["transcript_clean"]
    assert "123-45-6789" not in result["transcript_clean"]


def test_invalid_mode_is_structured():
    with pytest.raises(phi_module.InvalidPhiModeError) as exc:
        PhiProtectionService("DELETE_ALL")

    assert exc.value.code == "invalid_phi_mode"


def test_project_segments_remains_compatible():
    service = PhiProtectionService("LLM_MODE")
    result = service.project_segments([
        {"id": 1, "start": 0.0, "end": 2.0, "text": "MRN: A123456", "speaker": "caller"},
        {"id": 2, "start": 2.0, "end": 3.0, "text": "Ticket INC123456", "speaker": "agent"},
    ])

    assert result["canonical_segments"][1]["text"] == "Ticket INC123456"
    assert "INC123456" in result["protected_text"]
    assert result["mode"] == "LLM_MODE"


def test_supported_local_slm_models():
    assert phi_module.LocalSLMDetector.SUPPORTED_MODELS == frozenset({
        "gemma3", "qwen3", "mistral-small", "llama3.2"
    })


def test_local_slm_detector_rejects_unsupported_model():
    with pytest.raises(phi_module.InvalidPhiInputError):
        phi_module.LocalSLMDetector("gpt-test")


def test_optional_composite_detector_uses_regex_and_local_slm(monkeypatch):
    text = "Agent Jane Doe, ticket INC123456, patient MRN: A123456"

    class MockResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            import json
            offset = text.index("A123456")
            return json.dumps({"response": json.dumps([{
                "category": "MRN",
                "text": "A123456",
                "offset": offset,
            }])}).encode("utf-8")

    monkeypatch.setattr(phi_module.urllib.request, "urlopen", lambda request, timeout=None: MockResponse())

    service = PhiProtectionService("LLM_MODE", local_slm_model="gemma3")
    result = service.protect(text)

    assert "INC123456" in result["transcript_clean"]
    assert "Agent Jane Doe" in result["transcript_clean"]
    assert "A123456" not in result["transcript_clean"]


def test_local_slm_response_cannot_modify_operational_spans(monkeypatch):
    text = "Caller John Smith at INC123456"

    class MockResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            import json
            return json.dumps({"response": json.dumps([{
                "category": "PATIENT_IDENTIFIER",
                "text": "John Smith",
                "offset": text.index("John Smith"),
            }, {
                "category": "PATIENT_ACCOUNT",
                "text": "INC123456",
                "offset": text.index("INC123456"),
            }])}).encode("utf-8")

    monkeypatch.setattr(phi_module.urllib.request, "urlopen", lambda request, timeout=None: MockResponse())

    detector = phi_module.LocalSLMDetector("qwen3")
    findings = detector.detect(text)

    assert findings == []


def test_future_enterprise_detector_is_structured():
    detector = phi_module.FutureEnterpriseDetector("enterprise-phi")

    with pytest.raises(phi_module.PhiProtectionError) as exc:
        detector.detect("Patient Alice")

    assert exc.value.code == "enterprise_detector_not_configured"
