from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import AsyncIterable, Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from contracts.artifact import ArtifactDownloadLink, ArtifactKey, ArtifactMetadata
from modules.exceptions import (
    ArtifactDownloadLinkError,
    ArtifactNotFoundError,
    ArtifactStorageError,
    ArtifactValidationError,
)

_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")


def validate_artifact_key(key: ArtifactKey) -> None:
    if not isinstance(key.artifact_type, __import__("contracts.artifact", fromlist=["ArtifactType"]).ArtifactType):
        raise ArtifactValidationError("Invalid artifact type")
    if not _SAFE_SEGMENT_RE.fullmatch(key.owner_id or ""):
        raise ArtifactValidationError("Invalid artifact owner identifier")
    if not _SAFE_SEGMENT_RE.fullmatch(key.artifact_id or ""):
        raise ArtifactValidationError("Invalid artifact identifier")
    filename = key.filename or ""
    if "\\" in filename or "/" in filename or ".." in filename or not _SAFE_FILENAME_RE.fullmatch(filename):
        raise ArtifactValidationError("Invalid artifact filename")


class ArtifactProvider(Protocol):
    async def save(self, key: ArtifactKey, data: bytes | Iterable[bytes] | AsyncIterable[bytes], *, metadata: ArtifactMetadata) -> ArtifactMetadata: ...
    async def read(self, key: ArtifactKey) -> bytes: ...
    async def exists(self, key: ArtifactKey) -> bool: ...
    async def delete(self, key: ArtifactKey) -> bool: ...
    async def list(self, prefix: str | None = None) -> list[ArtifactMetadata]: ...
    async def create_download_link(self, key: ArtifactKey, expires_in_seconds: int = 300) -> ArtifactDownloadLink: ...


class LocalArtifactProvider:
    provider_name = "local"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self.root = self.root.resolve()
        except Exception as exc:
            raise ArtifactStorageError("Artifact storage root could not be initialized") from exc

    def _path(self, key: ArtifactKey) -> Path:
        validate_artifact_key(key)
        try:
            candidate = (self.root / key.as_posix()).resolve(strict=False)
            candidate.relative_to(self.root)
        except (ValueError, RuntimeError, OSError) as exc:
            raise ArtifactStorageError("Artifact key escapes configured storage root") from exc
        return candidate

    def _metadata_path(self, key: ArtifactKey) -> Path:
        return Path(str(self._path(key)) + ".artifact.json")

    async def save(self, key: ArtifactKey, data: bytes | Iterable[bytes] | AsyncIterable[bytes], *, metadata: ArtifactMetadata) -> ArtifactMetadata:
        path = self._path(key)
        metadata_path = self._metadata_path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".tmp")
            checksum = hashlib.sha256()
            size = 0
            with temporary.open("wb") as stream:
                if isinstance(data, (bytes, bytearray, memoryview)):
                    chunk = bytes(data)
                    stream.write(chunk)
                    checksum.update(chunk)
                    size += len(chunk)
                elif hasattr(data, "read"):
                    while True:
                        chunk = data.read(1024 * 1024)
                        if not chunk:
                            break
                        chunk = bytes(chunk)
                        stream.write(chunk)
                        checksum.update(chunk)
                        size += len(chunk)
                elif hasattr(data, "__aiter__"):
                    async for chunk in data:
                        chunk = bytes(chunk)
                        stream.write(chunk)
                        checksum.update(chunk)
                        size += len(chunk)
                else:
                    for chunk in data:
                        chunk = bytes(chunk)
                        stream.write(chunk)
                        checksum.update(chunk)
                        size += len(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)

            result = ArtifactMetadata(
                key=key,
                content_type=metadata.content_type,
                size_bytes=size,
                created_at=metadata.created_at or datetime.now(timezone.utc),
                checksum=checksum.hexdigest(),
                retention=metadata.retention,
                provider="local",
            )
            temporary_metadata = metadata_path.with_name(metadata_path.name + ".tmp")
            temporary_metadata.write_text(json.dumps(_metadata_to_dict(result), sort_keys=True), encoding="utf-8")
            os.replace(temporary_metadata, metadata_path)
            return result
        except ArtifactValidationError:
            raise
        except Exception as exc:
            raise ArtifactStorageError("Artifact could not be saved safely") from exc

    async def read(self, key: ArtifactKey) -> bytes:
        path = self._path(key)
        if not path.is_file() or path.is_symlink():
            raise ArtifactNotFoundError("Artifact was not found")
        try:
            return path.read_bytes()
        except Exception as exc:
            raise ArtifactStorageError("Artifact could not be read") from exc

    async def exists(self, key: ArtifactKey) -> bool:
        path = self._path(key)
        return path.is_file() and not path.is_symlink()

    async def delete(self, key: ArtifactKey) -> bool:
        path = self._path(key)
        metadata_path = self._metadata_path(key)
        try:
            removed = False
            if path.is_file() and not path.is_symlink():
                path.unlink()
                removed = True
            if metadata_path.is_file() and not metadata_path.is_symlink():
                metadata_path.unlink()
            return removed
        except Exception as exc:
            raise ArtifactStorageError("Artifact could not be deleted safely") from exc

    async def list(self, prefix: str | None = None) -> list[ArtifactMetadata]:
        results: list[ArtifactMetadata] = []
        try:
            if not self.root.exists():
                return results
            for path in sorted(self.root.rglob("*.artifact.json")):
                if path.is_symlink():
                    continue
                payload = json.loads(path.read_text(encoding="utf-8"))
                metadata = _metadata_from_dict(payload)
                if prefix and not metadata.key.as_posix().startswith(prefix.rstrip("/")):
                    continue
                results.append(metadata)
            return results
        except Exception as exc:
            raise ArtifactStorageError("Artifacts could not be listed") from exc

    async def create_download_link(self, key: ArtifactKey, expires_in_seconds: int = 300) -> ArtifactDownloadLink:
        if expires_in_seconds < 1:
            raise ArtifactDownloadLinkError("Download link lifetime must be positive")
        if not await self.exists(key):
            raise ArtifactNotFoundError("Artifact was not found")
        from urllib.parse import quote
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(1, expires_in_seconds))
        return ArtifactDownloadLink(
            url=f"local://artifact/{quote(key.as_posix(), safe='/')}",
            expires_at=expires_at,
            provider="local",
        )


def _metadata_to_dict(metadata: ArtifactMetadata) -> dict[str, Any]:
    return {
        "artifact_type": metadata.key.artifact_type.value,
        "owner_id": metadata.key.owner_id,
        "artifact_id": metadata.key.artifact_id,
        "filename": metadata.key.filename,
        "content_type": metadata.content_type,
        "size_bytes": metadata.size_bytes,
        "created_at": metadata.created_at.isoformat() if metadata.created_at else None,
        "checksum": metadata.checksum,
        "retention_action": metadata.retention.action.value,
        "retention_days": metadata.retention.retention_days,
        "provider": metadata.provider,
    }


def _metadata_from_dict(payload: dict[str, Any]) -> ArtifactMetadata:
    from contracts.artifact import ArtifactType, RetentionAction, RetentionPolicy
    key = ArtifactKey(
        artifact_type=ArtifactType(payload["artifact_type"]),
        owner_id=payload["owner_id"],
        artifact_id=payload["artifact_id"],
        filename=payload["filename"],
    )
    validate_artifact_key(key)
    created_at = datetime.fromisoformat(payload["created_at"]) if payload.get("created_at") else None
    retention = RetentionPolicy(
        action=RetentionAction(payload["retention_action"]),
        retention_days=payload.get("retention_days"),
    )
    return ArtifactMetadata(
        key=key,
        content_type=payload.get("content_type", "application/octet-stream"),
        size_bytes=int(payload.get("size_bytes", 0)),
        created_at=created_at,
        checksum=payload.get("checksum", ""),
        retention=retention,
        provider=payload.get("provider", "local"),
    )


class AzureBlobArtifactProvider:
    """Interface-only Azure Blob provider; SDK integration is intentionally deferred."""

    provider_name = "azure_blob"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.configuration = dict(kwargs)

    async def save(self, key: ArtifactKey, data: bytes | Iterable[bytes] | AsyncIterable[bytes], *, metadata: ArtifactMetadata) -> ArtifactMetadata:
        raise NotImplementedError("Azure Blob artifact storage is not implemented")

    async def read(self, key: ArtifactKey) -> bytes:
        raise NotImplementedError("Azure Blob artifact storage is not implemented")

    async def exists(self, key: ArtifactKey) -> bool:
        raise NotImplementedError("Azure Blob artifact storage is not implemented")

    async def delete(self, key: ArtifactKey) -> bool:
        raise NotImplementedError("Azure Blob artifact storage is not implemented")

    async def list(self, prefix: str | None = None) -> list[ArtifactMetadata]:
        raise NotImplementedError("Azure Blob artifact storage is not implemented")

    async def create_download_link(self, key: ArtifactKey, expires_in_seconds: int = 300) -> ArtifactDownloadLink:
        raise NotImplementedError("Azure Blob artifact storage is not implemented")


class S3CompatibleArtifactProvider:
    """Interface-only S3-compatible provider; SDK integration is intentionally deferred."""

    provider_name = "s3"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.configuration = dict(kwargs)

    async def save(self, key: ArtifactKey, data: bytes | Iterable[bytes] | AsyncIterable[bytes], *, metadata: ArtifactMetadata) -> ArtifactMetadata:
        raise NotImplementedError("S3-compatible artifact storage is not implemented")

    async def read(self, key: ArtifactKey) -> bytes:
        raise NotImplementedError("S3-compatible artifact storage is not implemented")

    async def exists(self, key: ArtifactKey) -> bool:
        raise NotImplementedError("S3-compatible artifact storage is not implemented")

    async def delete(self, key: ArtifactKey) -> bool:
        raise NotImplementedError("S3-compatible artifact storage is not implemented")

    async def list(self, prefix: str | None = None) -> list[ArtifactMetadata]:
        raise NotImplementedError("S3-compatible artifact storage is not implemented")

    async def create_download_link(self, key: ArtifactKey, expires_in_seconds: int = 300) -> ArtifactDownloadLink:
        raise NotImplementedError("S3-compatible artifact storage is not implemented")
