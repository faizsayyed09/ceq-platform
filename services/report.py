from __future__ import annotations

import html

from modules.exceptions import ValidationError
from modules.storage import ArtifactStore
from modules.validation import validate_safe_filename, validate_uuid


class ReportService:
    def __init__(self, artifact_store: ArtifactStore) -> None:
        self.artifact_store = artifact_store

    async def generate(self, audit_id: str, title: str, body: object) -> dict[str, str]:
        audit_id = validate_uuid(audit_id, "audit_id")
        filename = validate_safe_filename(f"report_{audit_id}.html")
        safe_title = html.escape(title[:200] or "CEQ Audit Report")
        safe_body = html.escape(str(body)[:500_000])
        document = (
            "<!doctype html><html><head><meta charset='utf-8'><title>"
            + safe_title
            + "</title></head><body><h1>"
            + safe_title
            + "</h1><pre>"
            + safe_body
            + "</pre></body></html>"
        ).encode("utf-8")
        if len(document) > 500 * 1024 * 1024:
            raise ValidationError("Generated report exceeds file size limit")
        location = await self.artifact_store.save(filename, document, content_type="text/html")
        return {"audit_id": audit_id, "filename": filename, "location": location}
