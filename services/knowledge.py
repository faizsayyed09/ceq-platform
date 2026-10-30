from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from contracts.knowledge import (
    KnowledgeArticle,
    KnowledgeCitation,
    KnowledgeConfidence,
    KnowledgePolicyResult,
    KnowledgeProvider,
    KnowledgeQuery,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
)
from modules.exceptions import ValidationError


class KnowledgeService:
    """Provider-neutral knowledge search and policy evaluation."""

    def __init__(self, provider: KnowledgeProvider | None = None) -> None:
        self.provider = provider

    def search(self, query: str, articles: list[dict[str, Any]], limit: int = 10) -> dict[str, object]:
        """Backward-compatible ranked search used by existing callers."""
        if not isinstance(query, str) or not query.strip():
            raise ValidationError("Knowledge query is required")
        if len(query) > 10_000:
            raise ValidationError("Knowledge query exceeds size limit")
        if not 1 <= limit <= 100:
            raise ValidationError("Knowledge result limit must be between 1 and 100")
        terms = {term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) >= 3}
        ranked = []
        for article in articles:
            text = (str(article.get("title", "")) + " " + str(article.get("body", ""))).lower()
            score = sum(1 for term in terms if term in text)
            if terms and score:
                ranked.append({"article_id": article.get("article_id"), "title": article.get("title"), "score": score})
        ranked.sort(key=lambda item: item["score"], reverse=True)
        ranked = ranked[:limit]
        return {"results": ranked, "result_count": len(ranked)}

    def search_provider(self, query: KnowledgeQuery, limit: int = 10) -> KnowledgeSearchResult:
        if self.provider is None:
            raise ValidationError("Knowledge provider is required")
        if not query.issue_summary.strip():
            raise ValidationError("Knowledge query is required")
        if not 1 <= limit <= 100:
            raise ValidationError("Knowledge result limit must be between 1 and 100")
        return self.provider.search(KnowledgeSearchRequest(query=query, limit=limit))

    def calculate_confidence(
        self,
        query: KnowledgeQuery,
        articles: Iterable[KnowledgeArticle] | Sequence[Mapping[str, Any]],
    ) -> KnowledgeConfidence:
        normalized = self._normalize_articles(articles)
        if not normalized:
            return KnowledgeConfidence.LOW
        query_terms = {term for term in re.findall(r"[a-z0-9]+", query.issue_summary.lower()) if len(term) >= 3}
        if not query_terms:
            return KnowledgeConfidence.MEDIUM
        best_ratio = 0.0
        for article in normalized:
            text = (article.title + " " + article.body).lower()
            hits = sum(1 for term in query_terms if term in text)
            best_ratio = max(best_ratio, hits / len(query_terms))
        if best_ratio >= 0.75:
            return KnowledgeConfidence.HIGH
        if best_ratio >= 0.40:
            return KnowledgeConfidence.MEDIUM
        return KnowledgeConfidence.LOW

    def evaluate_policy(
        self,
        result: KnowledgeSearchResult,
        cited_article_ids: Iterable[str] = (),
    ) -> KnowledgePolicyResult:
        confidence = KnowledgeConfidence(result.confidence)
        citations = tuple(result.citations or self._citations(result.articles))
        if result.kb_gap:
            return KnowledgePolicyResult(
                articles=result.articles,
                citations=citations,
                confidence=confidence,
                enforceable=False,
                advisory_only={"reason": "Knowledge base gap"},
                kb_gap=True,
                kb_gap_note=result.kb_gap_note,
            )

        enforceable = confidence == KnowledgeConfidence.HIGH
        if enforceable:
            return KnowledgePolicyResult(
                articles=result.articles,
                citations=citations,
                confidence=confidence,
                enforceable=True,
                advisory_only=None,
                kb_gap=False,
                kb_gap_note="",
                enforceable_reason="High confidence KB match",
            )

        returned_ids = {article.article_id.upper() for article in result.articles if article.article_id}
        returned_ids.update(citation.article_id.upper() for citation in citations if citation.article_id)
        attached_ids = {str(article_id).strip().upper() for article_id in cited_article_ids if str(article_id).strip()}
        promoted_ids = sorted(attached_ids.intersection(returned_ids))
        if promoted_ids:
            return KnowledgePolicyResult(
                articles=result.articles,
                citations=citations,
                confidence=confidence,
                enforceable=True,
                advisory_only=None,
                kb_gap=False,
                kb_gap_note="",
                enforceable_reason="agent cited " + ", ".join(promoted_ids) + " in the ticket",
            )

        return KnowledgePolicyResult(
            articles=result.articles,
            citations=citations,
            confidence=confidence,
            enforceable=False,
            advisory_only={"confidence": confidence.value.lower(), "reason": "KB guidance is advisory only"},
            kb_gap=False,
            kb_gap_note="",
        )

    def extract_citations(self, article_ids: Iterable[str]) -> tuple[KnowledgeCitation, ...]:
        return tuple(KnowledgeCitation(article_id=str(article_id).strip()) for article_id in article_ids if str(article_id).strip())

    def _normalize_articles(self, articles: Iterable[KnowledgeArticle] | Sequence[Mapping[str, Any]]) -> tuple[KnowledgeArticle, ...]:
        normalized = []
        for article in articles:
            if isinstance(article, KnowledgeArticle):
                normalized.append(article)
            elif isinstance(article, Mapping):
                normalized.append(KnowledgeArticle(
                    article_id=str(article.get("article_id") or article.get("id") or ""),
                    title=str(article.get("title") or ""),
                    body=str(article.get("body") or article.get("text") or article.get("content") or ""),
                    url=str(article.get("url") or ""),
                    provider=str(article.get("provider") or ""),
                ))
        return tuple(normalized)

    def _citations(self, articles: Iterable[KnowledgeArticle]) -> tuple[KnowledgeCitation, ...]:
        return tuple(KnowledgeCitation(article_id=article.article_id, title=article.title, url=article.url) for article in articles if article.article_id)
