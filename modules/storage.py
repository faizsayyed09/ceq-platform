from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Protocol

from modules.validation import resolve_artifact_path


class ArtifactStore(Protocol):
    async def save(self, filename: str, data: bytes, *, content_type: str = "application/octet-stream") -> str: ...
    async def read(self, filename: str) -> bytes: ...
    async def delete(self, filename: str) -> bool: ...


class LocalArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    async def save(self, filename: str, data: bytes, *, content_type: str = "application/octet-stream") -> str:
        path = resolve_artifact_path(self.root, filename)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return str(path)

    async def read(self, filename: str) -> bytes:
        return resolve_artifact_path(self.root, filename).read_bytes()

    async def delete(self, filename: str) -> bool:
        path = resolve_artifact_path(self.root, filename)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def purge_older_than(self, filename_prefix: str, cutoff_epoch: float) -> int:
        removed = 0
        for path in self.root.iterdir():
            if not path.is_file() or not path.name.startswith(filename_prefix):
                continue
            if path.stat().st_mtime < cutoff_epoch:
                path.unlink()
                removed += 1
        return removed
