from __future__ import annotations

from services.phi_protection import PhiProtectionService


def redact_pii(text: str) -> str:
    """Deprecated compatibility name; redacts patient PHI, not operational identifiers."""
    return PhiProtectionService("LLM_MODE").project(text, "LLM_MODE")["text"]
