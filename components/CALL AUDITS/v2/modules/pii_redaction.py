from __future__ import annotations

import re

_PATTERNS = (
    (re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"), "[REDACTED_SSN]"),
    (re.compile(r"(?<!\d)\d{16}(?!\d)"), "[REDACTED_CARD]"),
    (re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"), "[REDACTED_EMAIL]"),
)


def redact_pii(text: str) -> str:
    redacted = text
    for pattern, replacement in _PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted
