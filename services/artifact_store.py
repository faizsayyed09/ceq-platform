from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import AsyncIterable, Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from contracts.artifact import (
    ArtifactDownloadLink,
    ArtifactKey,
    ArtifactMetadata,
    ArtifactType,
    RetentionAction,
    RetentionPolicy,
)
from modules.exceptions import (
    ArtifactDownloadLinkError,
    ArtifactStorageError,
    ArtifactValidationError,
)
from providers.artifact import ArtifactProvider, LocalArtifactProvider

logger = logging.getLogger(__name__)

_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")


class ArtifactStoreService:
    """Provider-neutral artifact storage and retention service."""

    def __init__(
        self,
        provider: ArtifactProvider | None = None,
        storage_root: str | Path = "./artifacts",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.provider = provider or LocalArtifactProvider(storage_root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def root(self) -> Path | None:
        return getattr(self.provider, "root", None)

    def generate_key(
        self,
        artifact_type: ArtifactType | str,
        owner_id: str,
        filename: str,
        artifact_id: str | None = None,
    ) -> ArtifactKey:
        normalized_type = self._artifact_type(artifact_type)
        owner = str(owner_id or "")
        if not _SAFE_SEGMENT_RE.fullmatch(owner):
            raise ArtifactValidationError("Invalid artifact owner identifier")
        name = str(filename or "")
        if "\\" in name or "/" in name or ".." in name or not _SAFE_FILENAME_RE.fullmatch(name):
            raise ArtifactValidationError("Invalid artifact filename")

        if artifact_id is None:
            identity = f"{normalized_type.value}|{owner}|{name}".encode("utf-8")
            generated_id = hashlib.sha256(identity).hexdigest()[:32]
        else:
            generated_id = str(artifact_id).strip()
            if not _SAFE_SEGMENT_RE.fullmatch(generated_id):
                raise ArtifactValidationError("Invalid artifact identifier")

        return ArtifactKey(
            artifact_type=normalized_type,
            owner_id=owner,
            artifact_id=generated_id,
            filename=name,
        )

    async def save(
        self,
        artifact_type: ArtifactType | str,
        owner_id: str,
        filename: str,
        data: bytes | Iterable[bytes] | AsyncIterable[bytes],
        *,
        artifact_id: str | None = None,
        content_type: str = "application/octet-stream",
        retention: RetentionPolicy | None = None,
        provider_metadata: dict[str, Any] | None = None,
    ) -> ArtifactMetadata:
        del provider_metadata
        key = self.generate_key(artifact_type, owner_id, filename, artifact_id)
        policy = self._validate_retention(retention)
        now = self._now()
        metadata = ArtifactMetadata(
            key=key,
            content_type=self._validate_content_type(content_type),
            created_at=now,
            retention=policy,
            provider=getattr(self.provider, "provider_name", "local"),
        )
        try:
            result = await self.provider.save(key, data, metadata=metadata)
            logger.info("Artifact saved type=%s owner=%s key=%s", key.artifact_type.value, key.owner_id, key.as_posix())
            return result
        except ArtifactStorageError:
            raise
        except Exception as exc:
            raise ArtifactStorageError("Artifact could not be saved") from exc

    async def read(self, key: ArtifactKey) -> bytes:
        try:
            return await self.provider.read(key)
        except Exception:
            raise

    async def exists(self, key: ArtifactKey) -> bool:
        try:
            return await self.provider.exists(key)
        except Exception:
            raise

    async def delete(self, key: ArtifactKey) -> bool:
        try:
            removed = await self.provider.delete(key)
            if removed:
                logger.info("Artifact deleted key=%s", key.as_posix())
            return removed
        except Exception:
            raise

    async def list(
        self,
        artifact_type: ArtifactType | str | None = None,
        owner_id: str | None = None,
        artifact_id: str | None = None,
    ) -> list[ArtifactMetadata]:
        prefix_parts: list[str] = []
        if artifact_type is not None:
            prefix_parts.append(self._artifact_type(artifact_type).value)
        if owner_id is not None:
            if not _SAFE_SEGMENT_RE.fullmatch(owner_id):
                raise ArtifactValidationError("Invalid artifact owner identifier")
            prefix_parts.append(owner_id)
        if artifact_id is not None:
            if not _SAFE_SEGMENT_RE.fullmatch(artifact_id):
                raise ArtifactValidationError("Invalid artifact identifier")
            prefix_parts.append(artifact_id)
        prefix = "/".join(prefix_parts) if prefix_parts else None
        items = await self.provider.list(prefix=prefix)
        return sorted(items, key=lambda item: item.key.as_posix())

    async def create_download_link(self, key: ArtifactKey, expires_in_seconds: int = 300) -> ArtifactDownloadLink:
        if expires_in_seconds < 1:
            raise ArtifactDownloadLinkError("Download link lifetime must be positive")
        try:
            return await self.provider.create_download_link(key, expires_in_seconds=expires_in_seconds)
        except ArtifactDownloadLinkError:
            raise
        except Exception as exc:
            raise ArtifactDownloadLinkError("Artifact download link could not be created") from exc

    async def apply_retention(self, now: datetime | None = None) -> int:
        current = self._as_utc(now or self._now())
        removed = 0
        for metadata in await self.list():
            policy = metadata.retention
            if policy.action != RetentionAction.DELETE_AFTER_EXPIRY or policy.retention_days is None:
                continue
            created = self._as_utc(metadata.created_at) if metadata.created_at else current
            if current >= created + timedelta(days=policy.retention_days):
                if await self.delete(metadata.key):
                    removed += 1
        return removed

    async def delete_after_processing(self, key: ArtifactKey) -> bool:
        metadata_items = await self.list(
            artifact_type=key.artifact_type,
            owner_id=key.owner_id,
            artifact_id=key.artifact_id,
        )
        metadata = next((item for item in metadata_items if item.key == key), None)
        if metadata is None:
            return False
        if metadata.retention.action != RetentionAction.DELETE_AFTER_PROCESSING:
            raise ArtifactValidationError("Artifact is not configured for delete-after-processing")
        return await self.delete(key)

    def _artifact_type(self, value: ArtifactType | str) -> ArtifactType:
        if isinstance(value, ArtifactType):
            return value
        try:
            return ArtifactType(str(value).strip().lower())
        except ValueError as exc:
            raise ArtifactValidationError("Invalid artifact type") from exc

    def _validate_retention(self, retention: RetentionPolicy | None) -> RetentionPolicy:
        if retention is None:
            return RetentionPolicy()
        try:
            policy = RetentionPolicy(
                action=RetentionAction(retention.action.value if isinstance(retention.action, RetentionAction) else retention.action),
                retention_days=retention.retention_days,
            )
            if policy.retention_days is not None and policy.retention_days < 1:
                raise ValueError("retention_days must be positive")
            if policy.action == RetentionAction.DELETE_AFTER_EXPIRY and policy.retention_days is None:
                raise ValueError("DELETE_AFTER_EXPIRY requires retention_days")
            return policy
        except (TypeError, ValueError) as exc:
            raise ArtifactValidationError("Invalid retention policy") from exc

    def _validate_content_type(self, value: str) -> str:
        normalized = str(value or "application/octet-stream").strip()
        if len(normalized) > 255 or "\r" in normalized or "\n" in normalized:
            raise ArtifactValidationError("Invalid artifact content type")
        return normalized

    def _now(self) -> datetime:
        return self._as_utc(self.clock())

    def _as_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
