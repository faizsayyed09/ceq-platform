from __future__ import annotations

import json
from typing import Any, Mapping

import requests

from contracts.knowledge import (
    KnowledgeArticle,
    KnowledgeConfidence,
    KnowledgeCitation,
    KnowledgeQuery,
    KnowledgeSearchRequest,
    KnowledgeSearchResult,
)


class MatchaProvider:
    """Provider-neutral HTTP adapter; no mission or flow IDs are used."""

    name = "matcha"

    def __init__(self, base_url: str, api_key: str, timeout_seconds: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def search(self, request: KnowledgeSearchRequest) -> KnowledgeSearchResult:
        response = requests.post(
            self.base_url + "/knowledge/search",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.api_key},
            json=request.query.to_dict(),
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return _parse_provider_payload(response.json(), self.name, request.limit)


class ServiceNowProvider:
    name = "servicenow"

    def __init__(self, instance_url: str, username: str = "", password: str = "", api_token: str = "", timeout_seconds: float = 30.0) -> None:
        self.instance_url = instance_url.rstrip("/")
        self.username = username
        self.password = password
        self.api_token = api_token
        self.timeout_seconds = timeout_seconds

    def search(self, request: KnowledgeSearchRequest) -> KnowledgeSearchResult:
        params = {"sysparm_limit": request.limit, "sysparm_query": "textLIKE" + request.query.issue_summary[:300], "sysparm_fields": "number,short_description,text,url"}
        auth = (self.username, self.password) if self.username and not self.api_token else None
        headers = {"Accept": "application/json"}
        if self.api_token:
            headers["Authorization"] = "Bearer " + self.api_token
        response = requests.get(self.instance_url + "/api/now/table/kb_knowledge", params=params, headers=headers, auth=auth, timeout=self.timeout_seconds)
        response.raise_for_status()
        data = response.json().get("result", []) if isinstance(response.json(), dict) else []
        articles = tuple(KnowledgeArticle(
            article_id=str(item.get("number") or item.get("sys_id") or ""),
            title=str(item.get("short_description") or ""),
            body=str(item.get("text") or ""),
            url=str(item.get("url") or ""),
            provider=self.name,
            metadata={"sys_id": item.get("sys_id")},
        ) for item in data if isinstance(item, dict))
        return KnowledgeSearchResult(articles=articles, citations=_citations(articles), provider=self.name, confidence=_confidence_from_articles(request.query, articles))


class AzureAISearchProvider:
    name = "azure_ai_search"

    def __init__(self, endpoint: str, api_key: str, index_name: str, api_version: str = "2024-07-01", timeout_seconds: float = 30.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.index_name = index_name
        self.api_version = api_version
        self.timeout_seconds = timeout_seconds

    def search(self, request: KnowledgeSearchRequest) -> KnowledgeSearchResult:
        url = self.endpoint + "/indexes/" + self.index_name + "/docs/search"
        response = requests.post(
            url,
            params={"api-version": self.api_version},
            headers={"Content-Type": "application/json", "api-key": self.api_key},
            json={"search": request.query.issue_summary, "top": request.limit},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        values = response.json().get("value", []) if isinstance(response.json(), dict) else []
        articles: list[KnowledgeArticle] = []
        for item in values:
            if not isinstance(item, dict):
                continue
            article_id = str(item.get("id") or item.get("article_id") or item.get("number") or "")
            articles.append(KnowledgeArticle(
                article_id=article_id,
                title=str(item.get("title") or item.get("short_description") or ""),
                body=str(item.get("content") or item.get("body") or item.get("text") or ""),
                url=str(item.get("url") or ""),
                provider=self.name,
                metadata={key: value for key, value in item.items() if key.startswith("@search")},
            ))
        result_articles = tuple(articles)
        return KnowledgeSearchResult(articles=result_articles, citations=_citations(result_articles), provider=self.name, confidence=_confidence_from_articles(request.query, result_articles))


def _citations(articles: tuple[KnowledgeArticle, ...]) -> tuple[KnowledgeCitation, ...]:
    return tuple(KnowledgeCitation(article.article_id, article.title, article.url) for article in articles if article.article_id)


def _confidence_from_articles(query: KnowledgeQuery, articles: tuple[KnowledgeArticle, ...]) -> KnowledgeConfidence:
    if not articles:
        return KnowledgeConfidence.LOW
    terms = {term for term in query.issue_summary.lower().replace("_", " ").split() if len(term) >= 4}
    if not terms:
        return KnowledgeConfidence.MEDIUM
    best = 0.0
    for article in articles:
        text = (article.title + " " + article.body).lower()
        hits = sum(1 for term in terms if term in text)
        best = max(best, hits / len(terms))
    if best >= 0.75 and len(articles) >= 1:
        return KnowledgeConfidence.HIGH
    if best >= 0.40:
        return KnowledgeConfidence.MEDIUM
    return KnowledgeConfidence.LOW


def _parse_provider_payload(payload: Mapping[str, Any] | Any, provider: str, limit: int) -> KnowledgeSearchResult:
    if not isinstance(payload, dict):
        payload = {}
    articles_data = payload.get("articles") or payload.get("relevantArticles") or []
    articles: list[KnowledgeArticle] = []
    if isinstance(articles_data, list):
        for item in articles_data[:limit]:
            if isinstance(item, str):
                articles.append(KnowledgeArticle(article_id=item, provider=provider))
            elif isinstance(item, dict):
                articles.append(KnowledgeArticle(
                    article_id=str(item.get("id") or item.get("article_id") or item.get("number") or ""),
                    title=str(item.get("title") or item.get("short_description") or ""),
                    body=str(item.get("body") or item.get("text") or item.get("content") or ""),
                    url=str(item.get("url") or ""),
                    provider=provider,
                ))
    articles_tuple = tuple(articles)
    confidence = KnowledgeConfidence(payload.get("confidence", "LOW").strip().upper()) if str(payload.get("confidence", "LOW")).strip().upper() in {"LOW", "MEDIUM", "HIGH"} else KnowledgeConfidence.LOW
    return KnowledgeSearchResult(
        articles=articles_tuple,
        citations=_citations(articles_tuple),
        confidence=confidence,
        kb_gap=bool(payload.get("kb_gap", False)),
        kb_gap_note=str(payload.get("kb_gap_note") or ""),
        provider=provider,
        raw=dict(payload),
    )
