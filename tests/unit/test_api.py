from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


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
