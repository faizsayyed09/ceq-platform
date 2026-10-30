from __future__ import annotations

import json
import re
from typing import Any

from modules.exceptions import ValidationError


class AuditService:
    def build_payload(self, transcript: str, ticket: dict[str, Any] | None = None, knowledge: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if len(transcript) > 500_000:
            raise ValidationError("Transcript exceeds payload size limit")
        return {"transcript": transcript, "ticket": ticket or {}, "knowledge_articles": knowledge or []}

    def parse_result(self, raw: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {"findings_text": raw}
        else:
            parsed = raw
        score_match = re.search(r"(?i)\bscore\b\s*[:=]\s*(\d+(?:\.\d+)?)", str(parsed))
        score = float(score_match.group(1)) if score_match else parsed.get("score")
        return {"score": score, "parsed": parsed}
