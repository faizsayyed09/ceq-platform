from __future__ import annotations

import re
import json
import hashlib
from pathlib import Path
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
        self._lookup_cache: dict[str, dict[str, object]] = {}

    def route_shard(self, company: object, client_map: Mapping[str, object] | None = None) -> dict[str, object]:
        resolved_map = client_map or self._load_default_client_map()
        normalized = re.sub(r"[^a-z0-9]+", "_", str(company or "").lower()).strip("_")
        for shard in resolved_map.get("shards", []):
            if not isinstance(shard, Mapping):
                continue
            keys = {re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_") for value in shard.get("client_keys", [])}
            aliases = {re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_") for value in shard.get("aliases", [])}
            if normalized in keys or normalized in aliases:
                return dict(shard)
        default_id = resolved_map.get("default_shard")
        for shard in resolved_map.get("shards", []):
            if isinstance(shard, Mapping) and shard.get("shard_id") == default_id:
                return dict(shard, fallback=True)
        return {"shard_id": "", "fallback": False, "unmapped": True}

    def build_query(
        self,
        ticket: Mapping[str, object] | None = None,
        *,
        issue_terms: Iterable[str] = (),
        product: str = "",
        sanitized_description: str = "",
    ) -> str:
        ticket = ticket or {}
        parts = [
            str(ticket.get("Short description") or ticket.get("short_description") or "").strip(),
            sanitized_description.strip(),
            product.strip(),
            " ".join(str(value).strip() for value in issue_terms if str(value).strip()),
        ]
        query = " ".join(part for part in parts if part)
        if len(query) > 10000:
            raise ValidationError("Knowledge query exceeds size limit")
        if not query:
            raise ValidationError("Knowledge query is required")
        return query[:10000]

    def validate_citations(
        self,
        cited_ids: Iterable[str],
        retrieved_ids: Iterable[str],
        *,
        shard_id: str,
        allowed_shards: Iterable[str] = (),
    ) -> dict[str, object]:
        retrieved = {str(value).strip().upper() for value in retrieved_ids if str(value).strip()}
        valid_shards = {str(value).strip() for value in allowed_shards if str(value).strip()} or {shard_id}
        valid = []
        dropped = []
        cross_client = []
        for article_id in cited_ids:
            normalized = str(article_id).strip().upper()
            if not normalized:
                continue
            if normalized not in retrieved:
                dropped.append(normalized)
            elif shard_id not in valid_shards:
                cross_client.append(normalized)
            else:
                valid.append(normalized)
        return {
            "valid_ids": valid,
            "dropped_ids": dropped,
            "cross_client_ids": cross_client,
        }

    def lookup_v2(
        self,
        ticket: Mapping[str, object],
        *,
        sanitized_description: str = "",
        client_map: Mapping[str, object] | None = None,
        issue_terms: Iterable[str] = (),
        product: str = "",
    ) -> dict[str, object]:
        company = ticket.get("Company") or ticket.get("company") or ""
        shard = self.route_shard(company, client_map)
        shard_id = str(shard.get("shard_id") or "")
        fallback_used = bool(shard.get("fallback"))
        query = self.build_query(ticket, sanitized_description=sanitized_description, issue_terms=issue_terms, product=product)
        cache_key = f"{shard_id}:{hashlib.sha256(query.encode('utf-8')).hexdigest()}"
        if cache_key in self._lookup_cache:
            cached = dict(self._lookup_cache[cache_key])
            cached["fallback_used"] = fallback_used
            return cached

        if self.provider is None:
            result = {"kb_status": "ERROR", "confidence": "LOW", "articles": [], "kb_gap": True, "cited_by_agent": [], "reasons": ["Knowledge provider is required"], "shard_used": shard_id, "fallback_used": fallback_used}
            return result
        search_result = self.search_provider(KnowledgeQuery(issue_summary=query, client=str(company)), limit=20)
        articles = tuple(article for article in search_result.articles[:3])
        cited_ids = self._extract_agent_citations(ticket)
        retrieved_ids = tuple(article.article_id for article in search_result.articles)
        validation = self.validate_citations(
            tuple(item.article_id for item in search_result.citations) + tuple(cited_ids),
            retrieved_ids,
            shard_id=shard_id,
        )
        if search_result.kb_gap:
            kb_status = "NONE"
        elif articles and search_result.confidence == KnowledgeConfidence.HIGH and not validation["cross_client_ids"]:
            kb_status = "FOUND"
        elif articles:
            kb_status = "WEAK"
        else:
            kb_status = "NONE"
        confidence = self._code_confidence(search_result, validation, cited_ids, fallback_used)
        result = {
            "kb_status": kb_status if kb_status != "NONE" else ("ERROR" if search_result.kb_gap else "NONE"),
            "confidence": confidence.value,
            "articles": [
                {"article_id": article.article_id, "title": article.title, "score": article.metadata.get("score", 0)}
                for article in articles
            ],
            "kb_gap": bool(search_result.kb_gap or kb_status == "NONE"),
            "cited_by_agent": sorted({article_id for article_id in cited_ids if article_id in retrieved_ids}),
            "reasons": {
                "retrieval": kb_status,
                "validation": validation,
                "mission_confidence_ignored": True,
            },
            "shard_used": shard_id,
            "fallback_used": fallback_used,
        }
        self._lookup_cache[cache_key] = result
        return result

    def _code_confidence(
        self,
        result: KnowledgeSearchResult,
        validation: Mapping[str, object],
        cited_ids: Iterable[str],
        fallback_used: bool,
    ) -> KnowledgeConfidence:
        if fallback_used or validation["cross_client_ids"]:
            return KnowledgeConfidence.LOW
        normalized_cited = {str(value).strip().upper() for value in cited_ids}
        retrieved = {article.article_id.upper() for article in result.articles if article.article_id}
        if normalized_cited.intersection(retrieved):
            return KnowledgeConfidence.HIGH
        if validation["dropped_ids"]:
            return KnowledgeConfidence.MEDIUM
        if result.articles:
            return KnowledgeConfidence.HIGH if result.confidence == KnowledgeConfidence.HIGH else KnowledgeConfidence.MEDIUM
        return KnowledgeConfidence.LOW

    @staticmethod
    def _extract_agent_citations(ticket: Mapping[str, object]) -> tuple[str, ...]:
        value = ticket.get("KA number") or ticket.get("ka_number") or ticket.get("cited_article_id") or ""
        if isinstance(value, (list, tuple)):
            return tuple(str(item).strip().upper() for item in value if str(item).strip())
        normalized = str(value).strip()
        return (normalized.upper(),) if normalized else ()

    def _load_default_client_map(self) -> Mapping[str, object]:
        path = Path(__file__).resolve().parents[1] / "flows" / "power-automate" / "kb-sync" / "client-map.json"
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

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
