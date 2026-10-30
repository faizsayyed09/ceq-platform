from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping


class ArtifactType(str, Enum):
    REPORT = "report"
    RECORDING = "recording"
    TRANSCRIPT = "transcript"


class RetentionAction(str, Enum):
    RETAIN = "retain"
    DELETE_AFTER_PROCESSING = "delete_after_processing"
    DELETE_AFTER_EXPIRY = "delete_after_expiry"


@dataclass(frozen=True)
class RetentionPolicy:
    action: RetentionAction = RetentionAction.RETAIN
    retention_days: int | None = None

    def __post_init__(self) -> None:
        if self.retention_days is not None and self.retention_days < 1:
            raise ValueError("retention_days must be at least 1")
        if self.action == RetentionAction.DELETE_AFTER_EXPIRY and self.retention_days is None:
            raise ValueError("DELETE_AFTER_EXPIRY requires retention_days")


@dataclass(frozen=True)
class ArtifactKey:
    artifact_type: ArtifactType
    owner_id: str
    artifact_id: str
    filename: str

    def as_posix(self) -> str:
        return "/".join((self.artifact_type.value, self.owner_id, self.artifact_id, self.filename))


@dataclass(frozen=True)
class ArtifactMetadata:
    key: ArtifactKey
    content_type: str = "application/octet-stream"
    size_bytes: int = 0
    created_at: datetime | None = None
    checksum: str = ""
    retention: RetentionPolicy = field(default_factory=RetentionPolicy)
    provider: str = "local"


@dataclass(frozen=True)
class ArtifactDownloadLink:
    url: str
    expires_at: datetime | None = None
    provider: str = "local"
