from __future__ import annotations

from collections.abc import Mapping

from modules.exceptions import ValidationError
from services.audit import AuditService
from services.knowledge import KnowledgeService
from services.matching import TicketMatchingService
from services.phi_protection import PhiProtectionService


class ReadOnlyMcpTools:
    """Read-only MCP tool adapter for analysts and agents; never used by the batch pipeline."""

    TOOL_DEFINITIONS: tuple[dict[str, object], ...] = (
        {
            "name": "kb_search",
            "description": "Search supplied knowledge articles through the v2 KB policy service.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "articles": {"type": "array"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
                },
                "required": ["query"],
            },
        },
        {
            "name": "kb_get_article",
            "description": "Read one supplied article by ID.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "article_id": {"type": "string", "minLength": 1},
                    "articles": {"type": "array"},
                },
                "required": ["article_id", "articles"],
            },
        },
        {
            "name": "snow_find_ticket",
            "description": "Find ticket candidates from supplied, projected text and tickets.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "transcript": {"type": "string", "minLength": 1},
                    "tickets": {"type": "array"},
                    "threshold": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
                },
                "required": ["transcript", "tickets"],
            },
        },
        {
            "name": "ceq_audit",
            "description": "Parse and explain an existing CEQ audit result without accepting writes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "raw_result": {},
                    "ticket": {"type": "object"},
                    "knowledge": {"type": "array"},
                },
                "required": ["raw_result"],
            },
        },
    )

    def list_tools(self) -> dict[str, object]:
        return {"tools": [dict(tool) for tool in self.TOOL_DEFINITIONS]}

    def call(self, name: str, arguments: Mapping[str, object] | None = None) -> dict[str, object]:
        args = dict(arguments or {})
        allowed = {str(tool["name"]) for tool in self.TOOL_DEFINITIONS}
        if name not in allowed:
            raise ValidationError("Unknown read-only MCP tool")
        if name == "kb_search":
            return self._kb_search(args)
        if name == "kb_get_article":
            return self._kb_get_article(args)
        if name == "snow_find_ticket":
            return self._snow_find_ticket(args)
        return self._ceq_audit(args)

    @staticmethod
    def _kb_search(arguments: Mapping[str, object]) -> dict[str, object]:
        query = str(arguments.get("query") or "")
        articles = arguments.get("articles")
        if not isinstance(articles, list):
            articles = []
        limit = int(arguments.get("limit", 10))
        return KnowledgeService().search(query, articles, limit)

    @staticmethod
    def _kb_get_article(arguments: Mapping[str, object]) -> dict[str, object]:
        article_id = str(arguments.get("article_id") or "").strip().upper()
        articles = arguments.get("articles")
        if not article_id:
            raise ValidationError("Article ID is required")
        if not isinstance(articles, list):
            raise ValidationError("Articles are required")
        for article in articles:
            if not isinstance(article, Mapping):
                continue
            candidate = str(article.get("article_id") or article.get("id") or "").strip().upper()
            if candidate == article_id:
                return {
                    "article_id": candidate,
                    "title": str(article.get("title") or ""),
                    "body": str(article.get("body") or article.get("text") or article.get("content") or ""),
                    "active": bool(article.get("active", True)),
                }
        return {"article_id": article_id, "found": False}

    @staticmethod
    def _snow_find_ticket(arguments: Mapping[str, object]) -> dict[str, object]:
        transcript = str(arguments.get("transcript") or "")
        tickets = arguments.get("tickets")
        if not isinstance(tickets, list):
            raise ValidationError("Tickets are required")
        threshold = float(arguments.get("threshold", 0.5))
        projected = PhiProtectionService("LLM_MODE").project_role_aware(
            transcript,
            source_track="caller",
            mode="LLM_MODE",
        )
        matches = TicketMatchingService().match(projected["text"], tickets, threshold)
        candidates = []
        for match in matches.get("matches", []):
            if not isinstance(match, Mapping):
                continue
            candidates.append({
                "ticket_id": str(match.get("ticket_id") or ""),
                "score": match.get("score"),
            })
        return {"matches": candidates, "match_count": len(candidates)}

    @staticmethod
    def _ceq_audit(arguments: Mapping[str, object]) -> dict[str, object]:
        raw_result = arguments.get("raw_result")
        if raw_result is None:
            raise ValidationError("Raw CEQ audit result is required")
        return AuditService().parse_result(raw_result)  # type: ignore[arg-type]
