from __future__ import annotations

from collections.abc import Iterable


def build_transcript(segments: Iterable[dict]) -> dict:
    rows = list(segments)
    text = " ".join(row["text"].strip() for row in rows if row.get("text", "").strip()).strip()
    return {"text": text, "segments": rows, "segment_count": len(rows)}
