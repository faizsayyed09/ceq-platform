import pytest

from modules.exceptions import SecurityError
from services.phi_protection import PhiProtectionService


def test_audit_mode_preserves_operational_identifiers():
    text = "Agent Jane Doe at jane.doe@example.com documented INC123456 for caller John Smith at 555-123-4567 at KB123456, Building A."
    result = PhiProtectionService("AUDIT_MODE").project(text)
    assert result["text"] == text
    assert result["findings"] == []


def test_llm_mode_redacts_patient_phi_but_preserves_ticket_data():
    text = "Agent Jane Doe documented INC123456. Patient name: Alice Smith. MRN: A123456. Diagnosis: diabetes."
    result = PhiProtectionService("LLM_MODE").project(text)
    assert "INC123456" in result["text"]
    assert "Agent Jane Doe" in result["text"]
    assert "[PHI_" in result["text"]
    assert {item["category"] for item in result["findings"]} >= {"patient_name", "mrn", "clinical_detail"}


def test_strict_mode_blocks_phi():
    with pytest.raises(SecurityError):
        PhiProtectionService("STRICT").project("Patient SSN is 123-45-6789")


def test_invalid_mode_is_rejected():
    with pytest.raises(Exception):
        PhiProtectionService("DELETE_ALL")


def test_off_mode_is_unchanged():
    text = "Patient name is Alice Smith, MRN: A123456, ticket INC123456"
    result = PhiProtectionService("OFF").project(text)
    assert result["text"] == text


def test_operational_allowlist_is_not_phi():
    text = "Caller analyst.jones@example.com employee E12345 phone +1 555 123 4567 department cardiology device laptop location clinic A"
    result = PhiProtectionService("AUDIT_MODE").project(text)
    assert result["phi_categories"] == []
    assert result["text"] == text
