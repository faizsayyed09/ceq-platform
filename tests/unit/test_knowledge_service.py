import pytest

from contracts.knowledge import (
    KnowledgeArticle,
    KnowledgeConfidence,
    KnowledgeQuery,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
)
from modules.exceptions import ValidationError
from services.knowledge import KnowledgeService


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


def test_invalid_search_inputs_are_rejected():
    service = KnowledgeService()
    with pytest.raises(ValidationError):
        service.search("", [])
    with pytest.raises(ValidationError):
        service.search("reset", [], limit=101)
