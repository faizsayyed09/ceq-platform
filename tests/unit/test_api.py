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
