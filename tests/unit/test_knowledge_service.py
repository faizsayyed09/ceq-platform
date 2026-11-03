import pytest

from contracts.knowledge import (
    KnowledgeArticle,
    KnowledgeConfidence,
    KnowledgeCitation,
    KnowledgeQuery,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
)
from modules.exceptions import ValidationError
from services.knowledge import KnowledgeService
from providers.knowledge import AzureAISearchProvider


class MockKnowledgeProvider:
    name = "mock"

    def __init__(self) -> None:
        self.request = None

    def search(self, request: KnowledgeSearchRequest) -> KnowledgeSearchResult:
        self.request = request
        return KnowledgeSearchResult(
            articles=(KnowledgeArticle(article_id="KB-1", title="Password reset", body="Reset the account password"),),
            confidence=KnowledgeConfidence.HIGH,
            provider="mock",
        )


def test_backward_compatible_search():
    result = KnowledgeService().search(
        "password reset",
        [{"article_id": "KB1", "title": "Password Reset", "body": "Reset an account password"}],
    )
    assert result["result_count"] == 1
    assert result["results"][0]["article_id"] == "KB1"


def test_confidence_high_medium_low():
    service = KnowledgeService()
    query = KnowledgeQuery(issue_summary="reset employee password account")
    high = KnowledgeArticle(article_id="KB1", title="Password reset", body="reset employee password account")
    medium = KnowledgeArticle(article_id="KB2", title="Support guide", body="reset password")
    low = KnowledgeArticle(article_id="KB3", title="Network guide", body="cables and routers")
    assert service.calculate_confidence(query, [high]) == KnowledgeConfidence.HIGH
    assert service.calculate_confidence(query, [medium]) == KnowledgeConfidence.MEDIUM
    assert service.calculate_confidence(query, [low]) == KnowledgeConfidence.LOW


def test_high_confidence_is_enforceable():
    article = KnowledgeArticle(article_id="KB-1", title="Password reset")
    result = KnowledgeSearchResult(articles=(article,), confidence=KnowledgeConfidence.HIGH)
    policy = KnowledgeService().evaluate_policy(result)
    assert policy.enforceable is True
    assert policy.advisory_only is None


def test_low_confidence_is_advisory():
    result = KnowledgeSearchResult(articles=(KnowledgeArticle(article_id="KB-1"),), confidence=KnowledgeConfidence.LOW)
    policy = KnowledgeService().evaluate_policy(result)
    assert policy.enforceable is False
    assert policy.advisory_only is not None


def test_kb_gap_never_promotes_cited_article():
    article = KnowledgeArticle(article_id="KB-1", title="Password reset")
    result = KnowledgeSearchResult(articles=(article,), confidence=KnowledgeConfidence.HIGH, kb_gap=True, kb_gap_note="No verified procedure")
    policy = KnowledgeService().evaluate_policy(result, cited_article_ids=["KB-1"])
    assert policy.enforceable is False
    assert policy.kb_gap is True
    assert policy.advisory_only is not None


def test_ticket_citation_promotes_advisory_article():
    article = KnowledgeArticle(article_id="KB-42", title="Password reset")
    result = KnowledgeSearchResult(articles=(article,), confidence=KnowledgeConfidence.MEDIUM)
    policy = KnowledgeService().evaluate_policy(result, cited_article_ids=["KB-42"])
    assert policy.enforceable is True
    assert "KB-42" in policy.enforceable_reason


def test_provider_abstraction_and_search_request():
    provider = MockKnowledgeProvider()
    service = KnowledgeService(provider=provider)
    result = service.search_provider(KnowledgeQuery(issue_summary="password reset"), limit=5)
    assert result.provider == "mock"
    assert provider.request.limit == 5
    assert provider.request.query.issue_summary == "password reset"


def test_azure_search_provider_managed_identity_header():
    class Token:
        token = "search-token"

    class Credential:
        def get_token(self, scope):
            assert scope == "https://search.azure.com/.default"
            return Token()

    provider = AzureAISearchProvider(
        "https://search.search.windows.net",
        api_key=None,
        index_name="ceq-kb",
        credential=Credential(),
    )
    headers = provider._headers()
    assert headers["Authorization"] == "Bearer search-token"


def test_invalid_search_inputs_are_rejected():
    service = KnowledgeService()
    with pytest.raises(ValidationError):
        service.search("", [])
    with pytest.raises(ValidationError):
        service.search("reset", [], limit=101)


def test_phase5_router_builds_query_and_unknown_client_falls_back():
    service = KnowledgeService()
    mapped = {
        "default_shard": "generic_other",
        "shards": [
            {"shard_id": "comanche", "client_keys": ["comanche"], "aliases": ["Comanche"]},
            {"shard_id": "generic_other", "client_keys": ["generic_other"], "aliases": ["Managed Services"]},
        ],
    }
    assert service.route_shard("Comanche", mapped)["shard_id"] == "comanche"
    fallback = service.route_shard("Unknown Health", mapped)
    assert fallback["shard_id"] == "generic_other"
    assert fallback["fallback"] is True
    assert service.build_query(
        {"Short description": "Password reset"},
        sanitized_description="Account access is locked",
        issue_terms=["Active Directory"],
        product="Windows",
    ).startswith("Password reset")


def test_phase5_lookup_drops_unretrieved_citations():
    provider = MockKnowledgeProvider()
    provider.search = lambda request: KnowledgeSearchResult(
        articles=(KnowledgeArticle(article_id="KB-1", title="Password reset", metadata={"score": 42}),),
        citations=(KnowledgeCitation(article_id="NOT-RETRIEVED"),),
        confidence=KnowledgeConfidence.HIGH,
        provider="mock",
    )
    service = KnowledgeService(provider=provider)
    result = service.lookup_v2(
        {"Company": "Comanche", "Short description": "Password reset", "KA number": "KB-1"},
        sanitized_description="Reset password",
        client_map={
            "default_shard": "generic_other",
            "shards": [{"shard_id": "comanche", "client_keys": ["comanche"], "aliases": ["Comanche"]}],
        },
    )
    assert result["kb_status"] == "FOUND"
    assert result["confidence"] == "HIGH"
    assert result["shard_used"] == "comanche"
    assert result["cited_by_agent"] == ["KB-1"]
    assert result["reasons"]["validation"]["dropped_ids"] == ["NOT-RETRIEVED"]
