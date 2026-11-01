from services.phi_protection import PhiProtectionService


def test_caller_self_introduction_remains_in_workforce_lane():
    result = PhiProtectionService("LLM_MODE").project_role_aware(
        "This is Dr. Maya Patel, nurse practitioner.",
        source_track="caller",
        mode="LLM_MODE",
    )

    assert result["workforce_lane"] is True
    assert result["text"] == "This is Dr. Maya Patel, nurse practitioner."
    assert "Dr. Maya Patel" in result["model_text"]


def test_workforce_ticket_fields_keep_names_but_redact_identifiers():
    result = PhiProtectionService("LLM_MODE").project_role_aware(
        "Requester: Dr. Maya Patel; callback 555-123-4567",
        source_field="requester",
        mode="LLM_MODE",
    )

    assert result["workforce_lane"] is True
    assert "Dr. Maya Patel" in result["model_text"]
    assert "555-123-4567" not in result["model_text"]


def test_patient_cue_and_clinical_detail_are_redacted_in_model_text():
    result = PhiProtectionService("LLM_MODE").project_role_aware(
        "Patient name is John Smith. Diagnosis diabetes.",
        source_field="Description",
        mode="LLM_MODE",
    )

    assert "John Smith" not in result["model_text"]
    assert "diagnosis" not in result["model_text"].lower()
    assert result["phi_policy_version"] == "phi-v2.0-baseline"


def test_role_aware_projection_returns_counts_only_metadata():
    result = PhiProtectionService("LLM_MODE").project_role_aware(
        "Patient MRN: A123456; patient account ACCT987654",
        source_field="Description",
        mode="LLM_MODE",
    )

    assert result["phi_counts"]["mrn"] == 1
    assert result["phi_counts"]["patient_account"] == 1
