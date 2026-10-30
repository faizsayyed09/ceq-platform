from __future__ import annotations

import re
from pathlib import Path

from modules.exceptions import SecurityError, ValidationError

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")


def validate_uuid(value: str, field_name: str = "conversation_id") -> str:
    normalized = (value or "").strip().lower()
    if not _UUID_RE.fullmatch(normalized):
        raise ValidationError(f"Invalid {field_name}")
    return normalized


def validate_safe_filename(value: str) -> str:
    raw = (value or "").strip()
    if "\\" in raw or "/" in raw or raw in {".", ".."} or ".." in raw:
        raise ValidationError("Invalid filename")
    normalized = raw
    if not _SAFE_NAME_RE.fullmatch(normalized):
        raise ValidationError("Invalid filename")
    return normalized


def resolve_artifact_path(root: Path, filename: str) -> Path:
    safe_name = validate_safe_filename(filename)
    root_resolved = root.resolve()
    candidate = (root_resolved / safe_name).resolve()
    if candidate.parent != root_resolved:
        raise SecurityError("Artifact path escapes configured storage root")
    return candidate
