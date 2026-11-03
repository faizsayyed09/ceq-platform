from fastapi.testclient import TestClient
from dataclasses import replace
import pytest

import api.main as main
from api.main import app

client = TestClient(app, headers={"Authorization": "Bearer test-service-token"})


@pytest.fixture(autouse=True)
def configure_test_service_token(monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, api_service_token="test-service-token"))


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_development_still_requires_service_auth():
    response = TestClient(app).post("/ticket-match", json={
        "transcript": "password reset",
        "tickets": [{"ticket_id": "INC001"}],
        "threshold": 0.2,
    })
    assert response.status_code == 401


def test_api_documentation_is_disabled():
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_reject_invalid_region():
    response = client.post("/auth/genesys", json={"region": "example.com"})
    assert response.status_code == 422
    assert response.json()["error"] == "ValidationError"


def test_ticket_match_route():
    response = client.post("/ticket-match", json={
        "transcript": "password reset for employee account",
        "tickets": [{"ticket_id": "INC001", "description": "Employee password reset"}],
        "threshold": 0.2,
    })
    assert response.status_code == 200
    assert response.json()["match_count"] == 1


def test_knowledge_search_route():
    response = client.post("/kb-search", json={
        "query": "password reset",
        "articles": [{"article_id": "KB1", "title": "Password Reset", "body": "Reset employee password"}],
    })
    assert response.status_code == 200
    assert response.json()["result_count"] == 1


def test_audit_route_with_parsed_result():
    response = client.post("/audit", json={
        "transcript": "customer called about account access",
        "ticket": {"ticket_id": "INC001"},
        "knowledge_articles": [{"article_id": "KB1"}],
        "raw_result": '{"score": 96, "findings": []}',
    })
    assert response.status_code == 200
    assert response.json()["audit_result"]["score"] == 96


def test_production_requires_service_auth(monkeypatch, tmp_path):
    monkeypatch.setattr(
        main,
        "settings",
        replace(main.settings, app_env="production", api_service_token="test-service-token", report_dir=str(tmp_path)),
    )

    response = TestClient(app).post("/ticket-match", json={
        "transcript": "password reset for employee account",
        "tickets": [{"ticket_id": "INC001", "description": "Employee password reset"}],
        "threshold": 0.2,
    })
    assert response.status_code == 401


def test_production_accepts_valid_service_auth(monkeypatch, tmp_path):
    monkeypatch.setattr(
        main,
        "settings",
        replace(main.settings, app_env="production", api_service_token="test-service-token", report_dir=str(tmp_path)),
    )

    response = client.post(
        "/ticket-match",
        headers={"Authorization": "Bearer test-service-token"},
        json={
            "transcript": "password reset for employee account",
            "tickets": [{"ticket_id": "INC001", "description": "Employee password reset"}],
            "threshold": 0.2,
        },
    )
    assert response.status_code == 200


def test_ready_reports_missing_production_auth(monkeypatch, tmp_path):
    monkeypatch.setattr(
        main,
        "settings",
        replace(main.settings, app_env="production", api_service_token=None, report_dir=str(tmp_path)),
    )

    response = client.get("/health/ready")
    assert response.status_code == 503
