from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Iterable, Mapping


def normalize_client(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def strip_html_and_decode(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"<img\b[^>]*\balt=[\"']([^\"']*)[\"'][^>]*>", r"\1\n", text, flags=re.I)
    text = re.sub(r"</li\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).replace("\r\n", "\n").strip()


def load_client_map(path: str | Path) -> dict[str, object]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    shards = data.get("shards")
    if not isinstance(shards, list):
        raise ValueError("Client map must contain a shards list")
    return data


def resolve_shard(client: object, client_map: Mapping[str, object]) -> dict[str, object]:
    normalized = normalize_client(client)
    for shard in client_map.get("shards", []):
        if not isinstance(shard, dict):
            continue
        keys = {normalize_client(key) for key in shard.get("client_keys", [])}
        aliases = {normalize_client(alias) for alias in shard.get("aliases", [])}
        if normalized in keys or normalized in aliases:
            return shard
    default_id = client_map.get("default_shard")
    for shard in client_map.get("shards", []):
        if isinstance(shard, dict) and shard.get("shard_id") == default_id:
            return dict(shard, fallback=True)
    return {"shard_id": "", "fallback": False, "unmapped": True}


def validate_actions(actions: Iterable[Mapping[str, object]], client_map: Mapping[str, object], refuse_upload_at: int | None = None) -> dict[str, object]:
    planned: list[dict[str, object]] = []
    errors: list[str] = []
    limit = refuse_upload_at
    if limit is None:
        raw_limit = client_map.get("refuse_upload_at")
        limit = int(raw_limit) if isinstance(raw_limit, (int, float)) else 195

    for action in actions:
        if not isinstance(action, Mapping):
            errors.append("Invalid action")
            continue
        kind = str(action.get("action") or "").strip().lower()
        if kind not in {"upload", "replace", "delete"}:
            errors.append("Unknown delta action")
            continue
        old_client = action.get("old_client_key")
        new_client = action.get("client_key")
        old_shard = resolve_shard(old_client, client_map) if old_client else None
        new_shard = resolve_shard(new_client, client_map)

        if kind in {"upload", "replace"} and new_shard.get("unmapped"):
            errors.append("Unmapped client")
            continue
        if old_shard is not None and old_shard.get("unmapped"):
            errors.append("Unmapped old client")
            continue
        if kind == "upload":
            count = int(new_shard.get("article_count") or 0)
            if count >= limit:
                errors.append("Shard refuses upload at configured capacity")
                continue

        planned.append({
            "action": "upload" if kind == "upload" and action.get("was_retired") else kind,
            "shard_id": new_shard.get("shard_id"),
            "old_shard_id": old_shard.get("shard_id") if old_shard else None,
            "folder_id": new_shard.get("folder_id"),
        })

    return {"ok": not errors, "planned": planned, "errors": errors}
