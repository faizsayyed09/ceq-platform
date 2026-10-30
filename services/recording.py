from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import requests

from modules.constants import MAX_FILE_SIZE_MB
from modules.exceptions import ExternalServiceError, ResourceNotFoundError, ValidationError
from modules.storage import ArtifactStore
from modules.validation import validate_uuid

logger = logging.getLogger("recording_service")


class RecordingService:
    def __init__(
        self,
        artifact_store: ArtifactStore,
        max_file_size_mb: int = MAX_FILE_SIZE_MB,
        poll_attempts: int = 6,
        poll_interval_seconds: float = 5.0,
        http_timeout_seconds: float = 60.0,
    ) -> None:
        self.artifact_store = artifact_store
        self.max_file_size_mb = max_file_size_mb
        self.poll_attempts = poll_attempts
        self.poll_interval_seconds = poll_interval_seconds
        self.http_timeout_seconds = http_timeout_seconds

    def _headers(self, access_token: str) -> dict[str, str]:
        if not access_token or not access_token.strip():
            raise ValidationError("Access token is required")
        return {"Authorization": "Bearer " + access_token.strip(), "Accept": "application/json"}

    def fetch_recordings(self, region: str, conversation_id: str, access_token: str, *, session: requests.Session | None = None) -> list[dict[str, Any]]:
        conversation_id = validate_uuid(conversation_id)
        http = session or requests.Session()
        url = f"https://api.{region}/api/v2/conversations/{conversation_id}/recordings"
        for attempt in range(self.poll_attempts):
            try:
                response = http.get(url, headers=self._headers(access_token), timeout=self.http_timeout_seconds)
            except requests.RequestException as exc:
                raise ExternalServiceError("Genesys recording request failed") from exc
            if response.status_code == 404:
                raise ResourceNotFoundError("Genesys recording not found")
            if response.status_code == 401:
                raise ExternalServiceError("Genesys recording authorization failed")
            if response.status_code == 403:
                raise ExternalServiceError("Genesys recording permission denied")
            if response.status_code == 202 or response.status_code == 200 and not response.content.strip():
                if attempt + 1 < self.poll_attempts:
                    time.sleep(self.poll_interval_seconds)
                    continue
                raise ExternalServiceError("Genesys recording remained processing")
            if response.status_code >= 400:
                raise ExternalServiceError("Genesys recording service returned an error")
            try:
                payload = response.json()
            except ValueError as exc:
                raise ExternalServiceError("Genesys recording response was invalid") from exc
            return payload.get("entities", [payload]) if isinstance(payload, dict) else payload
        raise ExternalServiceError("Genesys recording polling exhausted")

    async def download_media(self, media_uri: str, filename: str, access_token: str, *, session: requests.Session | None = None) -> dict[str, Any]:
        if not media_uri.startswith("https://"):
            raise ValidationError("Recording media URI must use HTTPS")
        http = session or requests.Session()
        try:
            with http.get(media_uri, headers={"Authorization": "Bearer " + access_token.strip()}, timeout=self.http_timeout_seconds, stream=True) as response:
                response.raise_for_status()
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > self.max_file_size_mb * 1024 * 1024:
                    raise ValidationError(f"Recording exceeds {self.max_file_size_mb} MB limit")
                chunks = []
                total = 0
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > self.max_file_size_mb * 1024 * 1024:
                        raise ValidationError(f"Recording exceeds {self.max_file_size_mb} MB limit")
                    chunks.append(chunk)
        except requests.RequestException as exc:
            raise ExternalServiceError("Genesys recording download failed") from exc

        data = b"".join(chunks)
        location = await self.artifact_store.save(filename, data, content_type="audio/mpeg")
        logger.info("Recording downloaded bytes=%d filename=%s", total, filename)
        return {"filename": filename, "size_bytes": total, "location": location}
