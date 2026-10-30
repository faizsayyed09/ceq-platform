from __future__ import annotations

import re
from typing import Any

from modules.exceptions import ValidationError


class KnowledgeService:
    def search(self, query: str, articles: list[dict[str, Any]], limit: int = 10) -> dict[str, object]:
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
        return {"results": ranked[: max(1, min(limit, 100))], "result_count": len(ranked[: max(1, min(limit, 100))])}
