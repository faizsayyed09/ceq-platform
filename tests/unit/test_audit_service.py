import pytest

from contracts.audit import AuditVerdict
from contracts.audit_payload import AuditRequest
from modules.exceptions import ValidationError
from services.audit import AuditService


CALL_ATTRIBUTES = {
    "opening": {"result": "MET"},
    "empathy_accountability_ownership": {"result": "MET"},
    "etiquette_professionalism": {"result": "MET"},
    "issue_identification": {"result": "MET"},
    "troubleshooting_resolution": {"result": "MET"},
    "process_adherence": {"result": "MET"},
    "hold_wait": {"result": "MET"},
    "ticket_classification_escalation": {"result": "MET"},
    "case_documentation": {"result": "MET"},
    "closing": {"result": "MET"},
}


def request_with_audit(audit, **changes):
    values = {
        "interaction_text": "Agent reset the employee password.",
        "ticket": {"matched_ticket": "INC001"},
        "ceq_response": audit,
    }
    values.update(changes)
    return AuditRequest(**values)


def test_score_calculation_and_96_percent_target():
    service = AuditService()
    score, rows, incomplete = service.calculate_score({"attributes": CALL_ATTRIBUTES})
    assert score == 100.0
    assert not incomplete
    result = service.execute_audit(request_with_audit({"attributes": CALL_ATTRIBUTES}))
    assert result.verdict == AuditVerdict.ACHIEVED
    assert result.score_pct == 100.0
    assert result.target_pct == 96.0


def test_score_below_target_is_not_achieved():
    attrs = {key: dict(value) for key, value in CALL_ATTRIBUTES.items()}
    attrs["closing"] = {"result": "NOT_MET"}
    result = AuditService().execute_audit(request_with_audit({"attributes": attrs}))
    assert result.verdict == AuditVerdict.NOT_ACHIEVED
    assert result.score_pct == 95.0


def test_critical_failure_takes_priority_and_manager_review():
    result = AuditService().execute_audit(request_with_audit({
        "attributes": CALL_ATTRIBUTES,
        "critical_failures": ["Shared sensitive information"],
    }))
    assert result.verdict == AuditVerdict.CRITICAL_FAIL
    assert result.score_pct == 0.0
    assert result.manager_review_required is True


def test_incomplete_audit_handling():
    result = AuditService().execute_audit(request_with_audit({
        "attributes": {"opening": {"result": "MET"}},
    }))
    assert result.verdict == AuditVerdict.INCOMPLETE
    assert result.score_pct is None
    assert len(result.incomplete_attributes) == 9
    assert result.manager_review_required is True


def test_parse_error_is_incomplete_and_reviewed():
    request = AuditRequest(interaction_text="interaction", ceq_response="not json")
    result = AuditService().execute_audit(request)
    assert result.verdict == AuditVerdict.PARSE_ERROR
    assert result.manager_review_required is True


def test_verified_facts_override_missing_ticket_for_case_documentation():
    attrs = {key: dict(value) for key, value in CALL_ATTRIBUTES.items()}
    attrs["case_documentation"] = {"result": "MET"}
    result = AuditService().execute_audit(request_with_audit(
        {"attributes": attrs},
        ticket={"matched_ticket": "", "match_status": "NOT_FOUND"},
    ))
    case_row = next(row for row in result.attributes if row.key == "case_documentation")
    assert case_row.result == "NA"
    assert case_row.unverified
    assert result.manager_review_required is True


def test_advisory_kb_cannot_support_critical_failure():
    result = AuditService().execute_audit(request_with_audit(
        {
            "attributes": CALL_ATTRIBUTES,
            "critical_failures": ["Procedure was not followed"],
        },
        kb={"confidence": "MEDIUM", "relevantArticles": [{"id": "KB-1"}]},
    ))
    assert result.verdict == AuditVerdict.ACHIEVED
    assert result.critical_failures == ()
    assert result.manager_review_required is True


def test_enforceable_kb_allows_critical_failure():
    result = AuditService().execute_audit(request_with_audit(
        {
            "attributes": CALL_ATTRIBUTES,
            "critical_failures": ["Required procedure was not followed"],
        },
        kb={"confidence": "HIGH", "kb_gap": False, "relevantArticles": [{"id": "KB-1"}]},
    ))
    assert result.verdict == AuditVerdict.CRITICAL_FAIL


def test_kb_gap_is_advisory_and_not_enforceable():
    payload = AuditService().build_payload(AuditRequest(
        interaction_text="Agent handled the request.",
        kb={"confidence": "HIGH", "kb_gap": True},
    ))
    assert "advisory only" in payload.text


def test_pending_export_becomes_retry_later():
    ticket = {"matched_ticket": "INC001", "verification": {"prematch_status": "PENDING_EXPORT"}}
    result = AuditService().execute_audit(request_with_audit({"attributes": CALL_ATTRIBUTES}, ticket=ticket))
    assert result.verdict == AuditVerdict.RETRY_LATER


def test_payload_validation_and_limit():
    service = AuditService()
    with pytest.raises(ValidationError):
        service.build_payload(AuditRequest(interaction_text=""))
    with pytest.raises(ValidationError):
        service.build_payload(AuditRequest(interaction_text="x" * 500_001))


def test_parse_result_legacy_compatibility():
    result = AuditService().parse_result('{"score": 96, "findings": []}')
    assert result["score"] == 96
