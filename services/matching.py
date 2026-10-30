from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from typing import Any

from modules.exceptions import ValidationError


class FingerprintService:
    def fingerprint(self, transcript: str, ticket_description: str = "") -> dict[str, object]:
        normalized_transcript = re.sub(r"[^a-z0-9]+", " ", transcript.lower()).strip()
        normalized_description = re.sub(r"[^a-z0-9]+", " ", ticket_description.lower()).strip()
        phones = re.findall(r"\b(?:\d[ -]?){10,14}\b", transcript)
        words = sorted(set(normalized_transcript.split()))[:30]
        transcript_hash = hashlib.sha256(normalized_transcript.encode("utf-8")).hexdigest()
        return {"transcript_hash_fingerprint": transcript_hash, "name_tokens": words, "phone_numbers": phones, "description_tokens": normalized_description.split()[:30]}


class TicketMatchingService:
    def match(self, transcript: str, tickets: list[dict[str, Any]], threshold: float = 0.5) -> dict[str, object]:
        if not isinstance(transcript, str) or not transcript.strip():
            raise ValidationError("Transcript is required")
        if not 0 <= threshold <= 1:
            raise ValidationError("Threshold must be between 0 and 1")
        if len(transcript) > 500_000:
            raise ValidationError("Transcript exceeds payload size limit")
        normalized_transcript = " ".join(re.findall(r"[a-z0-9]+", transcript.lower()))
        matches = []
        for ticket in tickets:
            description = " ".join(re.findall(r"[a-z0-9]+", str(ticket.get("description", "")).lower()))
            score = SequenceMatcher(None, normalized_transcript, description).ratio() if normalized_transcript and description else 0.0
            if score >= threshold:
                matches.append({"ticket_id": ticket.get("ticket_id") or ticket.get("number"), "score": round(score, 4), "description": str(ticket.get("description", ""))[:500]})
        matches.sort(key=lambda match: match["score"], reverse=True)
        return {"matches": matches, "match_count": len(matches)}
