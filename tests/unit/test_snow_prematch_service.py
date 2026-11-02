from datetime import datetime

from api.main import app
from fastapi.testclient import TestClient

from modules.exceptions import ValidationError
from services.snow_prematch import SnowPrematchService
from services.cutover import CutoverGateService
from services.preflight import RuntimePreflight


client = TestClient(app)


def test_refresh_reports_metadata_without_ticket_content():
    service = SnowPrematchService()
    state = service.refresh({
        "file_id": "123",
        "updated_at": "2026-11-01T15:00:00+00:00",
        "row_count": 72,
        "export_rows": 72,
        "coverage_start": "2026-10-29T15:00:00+00:00",
        "sha256": "a" * 64,
    })
    status = service.status()

    assert state.row_count == 72
    assert status["refresh_state"] == "ready"
    assert status["export_rows"] == 72
    assert "ticket_text" not in status


def test_refresh_rejects_invalid_sha256():
    service = SnowPrematchService()
    try:
        service.refresh({"sha256": "not-a-sha256"})
    except ValidationError:
        return
    raise AssertionError("Invalid sha256 was accepted")


def test_prematch_returns_sanitized_projection_and_is_idempotent():
    service = SnowPrematchService()
    service.refresh({
        "updated_at": "2026-11-01T15:30:00+00:00",
        "export_rows": 1,
        "coverage_start": "2026-10-29T15:30:00+00:00",
    })
    request = {
        "conversation_id": "conversation-1",
        "run_id": "run-1",
        "transcript": "[00:00] CALLER: My ticket is INC123456 and patient name is John Smith",
        "tickets": [{
            "Number": "INC123456",
            "Opened": "2026-11-01 14:30:00",
            "Updated": "2026-11-01 15:00:00",
            "State": "Active",
            "Company": "Example",
            "Short description": "Password reset",
            "Description": "Patient name is John Smith needs reset",
        }],
        "call_start": "2026-11-01T14:00:00+00:00",
        "call_end": "2026-11-01T15:00:00+00:00",
        "top_n": 3,
    }

    first = service.prematch(prematch_mode="shadow", **request)
    second = service.prematch(prematch_mode="azure", **request)

    assert first["snow_status"] in {"MATCHED", "AMBIGUOUS", "NOT_FOUND"}
    assert len(first["candidates"]) <= 3
    assert second["_idempotency_key"] == first["_idempotency_key"]
    assert "John Smith" not in str(first["candidates"])


def test_snow_api_refresh_status_and_prematch():
    refresh = client.post("/snow/refresh", json={
        "file_id": "123",
        "updated_at": "2026-11-01T15:30:00+00:00",
        "row_count": 1,
        "export_rows": 1,
        "coverage_start": "2026-10-29T15:30:00+00:00",
    })
    assert refresh.status_code == 200
    assert refresh.json()["refresh_state"] == "ready"

    status = client.get("/snow/status")
    assert status.status_code == 200
    assert status.json()["export_rows"] == 1

    prematch = client.post("/snow/prematch", json={
        "conversation_id": "api-conversation",
        "run_id": "api-run",
        "transcript": "[00:00] CALLER: Ticket INC123456 password reset",
        "tickets": [{
            "Number": "INC123456",
            "Opened": "2026-11-01 14:30:00",
            "Description": "Password reset",
        }],
        "call_start": "2026-11-01T14:00:00+00:00",
        "call_end": "2026-11-01T15:00:00+00:00",
    })
    assert prematch.status_code == 200
    assert prematch.json()["prematch_engine_version"] == "azure-prematch-v1"


def test_cutover_shadow_comparison_is_metadata_only():
    service = CutoverGateService()
    result = service.compare(
        matcha_status="MATCHED",
        azure_status="MATCHED",
        matcha_top_ticket="INC123",
        azure_top_ticket="INC123",
        matcha_score=0.8,
        azure_score=0.8,
    )
    assert result["disagreement_class"] == "same"

    gate = service.evaluate([], phi_samples_checked=False, rollback_tested=False)
    assert gate["gate_passed"] is False
    assert gate["mode"] == "shadow"
    assert gate["rollback_mode"] == "matcha"
    assert all(item["eligible"] is False for item in gate["retirement"])


def test_cutover_gate_stays_closed_until_all_evidence_exists():
    service = CutoverGateService()
    result = service.evaluate(
        [{
            "disagreement_class": "different_tickets",
            "label": "INC123",
            "explained": True,
        }],
        phi_samples_checked=True,
        rollback_tested=True,
    )
    assert result["gate_passed"] is True
    assert result["mode"] == "azure"


def test_preflight_requires_service_token_only_in_production_api(tmp_path):
    environment = {
        "APP_ENV": "development",
        "REPORT_DIR": str(tmp_path),
    }
    result = RuntimePreflight(environment).run(role="api")
    token_check = next(
        check for check in result["checks"]
        if check["name"] == "service authentication"
    )
    assert token_check["passed"] is True

    environment["APP_ENV"] = "production"
    environment["CEQ_API_SERVICE_TOKEN"] = ""
    result = RuntimePreflight(environment).run(role="api")
    assert result["passed"] is False
    assert any(
        check["name"] == "service authentication" and not check["passed"]
        for check in result["checks"]
    )


def test_matcha_preflight_requires_key_and_browser_user_agent(tmp_path):
    environment = {
        "APP_ENV": "production",
        "REPORT_DIR": str(tmp_path),
        "MATCHA_BASE_URL": "https://example.invalid",
    }
    result = RuntimePreflight(environment).run(role="api")
    key_check = next(
        check for check in result["checks"]
        if check["name"] == "Matcha API key"
    )
    user_agent_check = next(
        check for check in result["checks"]
        if check["name"] == "Matcha User-Agent"
    )
    assert key_check["passed"] is False
    assert user_agent_check["passed"] is False


def test_cutover_api_reports_closed_status_and_comparison():
    status = client.get("/cutover/status")
    assert status.status_code == 200
    assert status.json()["gate_passed"] is False

    comparison = client.post("/cutover/shadow-compare", json={
        "matcha_status": "MATCHED",
        "azure_status": "NOT_FOUND",
        "matcha_top_ticket": "INC123",
        "azure_top_ticket": None,
    })
    assert comparison.status_code == 200
    assert comparison.json()["disagreement_class"] == "matcha_only"
