from dataclasses import replace

import pytest

import api.main as main
from api.main import app
from fastapi.testclient import TestClient

from modules.exceptions import ValidationError
from services.mcp_tools import ReadOnlyMcpTools


client = TestClient(app, headers={"Authorization": "Bearer test-service-token"})


@pytest.fixture(autouse=True)
def configure_test_service_token(monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, api_service_token="test-service-token"))


def test_mcp_tool_registry_has_only_read_only_allowlist():
    tools = ReadOnlyMcpTools().list_tools()["tools"]
    names = {tool["name"] for tool in tools}
    assert names == {"kb_search", "kb_get_article", "snow_find_ticket", "ceq_audit"}


def test_kb_search_and_get_article_are_read_only():
    service = ReadOnlyMcpTools()
    articles = [
        {"article_id": "KB-1", "title": "Password reset", "body": "Reset the account password"},
        {"article_id": "KB-2", "title": "Network guide", "body": "Network diagnostics"},
    ]
    search = service.call("kb_search", {"query": "password reset", "articles": articles, "limit": 10})
    assert search["result_count"] == 1
    article = service.call("kb_get_article", {"article_id": "KB-1", "articles": articles})
    assert article["article_id"] == "KB-1"
    assert article["title"] == "Password reset"


def test_snow_ticket_lookup_returns_ids_not_ticket_text():
    result = ReadOnlyMcpTools().call("snow_find_ticket", {
        "transcript": "Patient John Smith needs reset for INC123456",
        "tickets": [{"ticket_id": "INC123456", "description": "Patient John Smith reset"}],
        "threshold": 0.0,
    })
    assert result["match_count"] >= 1
    rendered = str(result)
    assert "John Smith" not in rendered
    assert "INC123456" in rendered


def test_unknown_mcp_tool_is_rejected():
    try:
        ReadOnlyMcpTools().call("delete_ticket", {})
    except ValidationError:
        return
    raise AssertionError("Unknown tool was accepted")


def test_mcp_api_list_call_and_json_rpc():
    listed = client.get("/mcp/tools")
    assert listed.status_code == 200
    assert "kb_search" in str(listed.json())

    called = client.post("/mcp/tools/call", json={
        "name": "kb_search",
        "arguments": {
            "query": "password reset",
            "articles": [{"article_id": "KB-1", "title": "Password reset", "body": "Reset password"}],
        },
    })
    assert called.status_code == 200
    assert called.json()["result_count"] == 1

    rpc = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    })
    assert rpc.status_code == 200
    assert rpc.json()["id"] == 1
    assert "tools" in rpc.json()["result"]
