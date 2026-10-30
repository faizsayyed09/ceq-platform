from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol


class KnowledgeConfidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True)
class KnowledgeQuery:
    issue_summary: str
    client: str = ""
    product: str = ""
    location: str = ""
    scope_rule: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "issueSummary": self.issue_summary[:400],
            "client": self.client,
            "product": self.product,
            "location": self.location,
            "scopeRule": self.scope_rule,
        }


@dataclass(frozen=True)
class KnowledgeArticle:
    article_id: str
    title: str = ""
    body: str = ""
    url: str = ""
    provider: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeCitation:
    article_id: str
    title: str = ""
    url: str = ""


@dataclass(frozen=True)
class KnowledgeSearchRequest:
    query: KnowledgeQuery
    limit: int = 10


@dataclass(frozen=True)
class KnowledgeSearchResult:
    articles: tuple[KnowledgeArticle, ...] = ()
    citations: tuple[KnowledgeCitation, ...] = ()
    confidence: KnowledgeConfidence = KnowledgeConfidence.LOW
    kb_gap: bool = False
    kb_gap_note: str = ""
    provider: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgePolicyResult:
    articles: tuple[KnowledgeArticle, ...]
    citations: tuple[KnowledgeCitation, ...]
    confidence: KnowledgeConfidence
    enforceable: bool
    advisory_only: Mapping[str, Any] | None
    kb_gap: bool
    kb_gap_note: str
    enforceable_reason: str = ""


class KnowledgeProvider(Protocol):
    @property
    def name(self) -> str:
        ...

    def search(self, request: KnowledgeSearchRequest) -> KnowledgeSearchResult:
        ...
