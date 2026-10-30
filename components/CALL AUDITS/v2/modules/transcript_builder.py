from __future__ import annotations

from collections.abc import Iterable


def build_transcript(segments: Iterable[dict]) -> dict:
    rows: list[dict] = []
    for index, source in enumerate(segments):
        text = str(source.get("text", "")).strip()
        if not text:
            continue
        row = {
            "id": source.get("id", index + 1),
            "start": float(source.get("start", 0.0)),
            "end": float(source.get("end", source.get("start", 0.0))),
            "text": text,
            "speaker": source.get("speaker"),
        }
        for key in ("confidence", "words", "language", "uncertain", "hold_marker"):
            if key in source:
                row[key] = source[key]
        rows.append(row)

    utterances: list[dict] = []
    current: dict | None = None
    for row in rows:
        if current and current["speaker"] == row["speaker"]:
            current["end"] = row["end"]
            current["text"] = f'{current["text"].rstrip()} {row["text"]}'.strip()
            current["segments"].append(row["id"])
        else:
            if current:
                utterances.append(current)
            current = {
                "start": row["start"],
                "end": row["end"],
                "speaker": row["speaker"],
                "text": row["text"],
                "segments": [row["id"]],
            }
    if current:
        utterances.append(current)

    text = " ".join(row["text"] for row in rows).strip()
    return {
        "text": text,
        "segments": rows,
        "utterances": utterances,
        "segment_count": len(rows),
        "utterance_count": len(utterances),
    }
