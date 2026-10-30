from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable
from dataclasses import dataclass

from .constants import MAX_AUDIO_DURATION_SECONDS, MAX_FILE_SIZE_MB
from .exceptions import ValidationError


_LOGGER = logging.getLogger("ceq.transcription.audio_validation")
_ALLOWED_EXTENSIONS = frozenset({"wav", "mp3", "m4a", "flac", "ogg"})
_MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024


class AudioValidationError(ValidationError):
    """Structured validation failure for callers and logs."""

    def __init__(self, code: str, message: str, path: str | Path | None = None, **details: Any) -> None:
        self.code = code
        self.message = message
        self.path = str(path) if path is not None else None
        self.details = details
        super().__init__(message)


@dataclass(frozen=True)
class AudioPathResult:
    path: str


@dataclass(frozen=True)
class FileExtensionResult:
    extension: str


@dataclass(frozen=True)
class FileSizeResult:
    size_bytes: int
    max_size_bytes: int


@dataclass(frozen=True)
class AudioDurationResult:
    duration_seconds: float
    max_duration_seconds: int
    format_name: str | None = None
    codec_name: str | None = None
    channels: int = 0
    sample_rate: int = 0


@dataclass(frozen=True)
class AudioValidationResult:
    path: str
    extension: str
    size_bytes: int
    duration_seconds: float
    max_size_bytes: int
    max_duration_seconds: int
    format_name: str | None = None
    codec_name: str | None = None
    channels: int = 0
    sample_rate: int = 0


def _raise_validation(code: str, message: str, path: str | Path | None = None, **details: Any) -> None:
    _LOGGER.warning("Audio validation rejected: %s (%s)", code, message, extra={"audio_path": str(path) if path else None})
    raise AudioValidationError(code, message, path, **details)


def _contains_parent_traversal(path: Path | str) -> bool:
    raw = str(path)
    if "\x00" in raw:
        return True
    normalized = raw.replace("\\", "/")
    return any(part == ".." for part in normalized.split("/"))


def _is_symlink_component(path: Path) -> bool:
    candidate = path.absolute()
    for part in [candidate, *candidate.parents]:
        try:
            if part.is_symlink():
                return True
        except (OSError, RuntimeError):
            return True
    return False


def _canonical_roots(allowed_roots: Iterable[str | Path]) -> list[Path]:
    roots: list[Path] = []
    for root in allowed_roots:
        try:
            roots.append(Path(root).resolve(strict=True))
        except (FileNotFoundError, OSError, RuntimeError) as exc:
            _LOGGER.warning("Approved audio root could not be resolved", extra={"root": str(root)})
            raise AudioValidationError("invalid_allowed_root", "Approved directory does not exist", root) from exc
    return roots


def validate_audio_path(
    path: str | Path,
    allowed_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
) -> AudioPathResult:
    """Validate an audio path without following symlinks or escaping approved roots."""

    candidate = Path(path)
    if not str(candidate).strip() or _contains_parent_traversal(candidate):
        _raise_validation("path_traversal", "Path traversal is not allowed", candidate)

    if candidate.is_symlink() or _is_symlink_component(candidate):
        _raise_validation("symlink_not_allowed", "Symbolic-link audio paths are not allowed", candidate)

    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        _raise_validation("file_missing", "Audio file does not exist", candidate)
        raise AssertionError from exc

    if not resolved.is_file():
        _raise_validation("not_a_file", "Audio path is not a regular file", candidate)

    if allowed_roots:
        roots = _canonical_roots(allowed_roots)
        if not any(resolved.is_relative_to(root) for root in roots):
            _raise_validation("outside_allowed_root", "Audio path is outside the allowed directory", candidate)

    return AudioPathResult(path=str(resolved))


def validate_file_extension(path: str | Path) -> FileExtensionResult:
    extension = Path(path).suffix.lower().removeprefix(".")
    if extension not in _ALLOWED_EXTENSIONS:
        _raise_validation("unsupported_extension", "Unsupported audio file type", path, extension=extension)
    return FileExtensionResult(extension=extension)


def validate_file_size(
    path: str | Path,
    max_size_bytes: int = _MAX_FILE_SIZE_BYTES,
) -> FileSizeResult:
    if max_size_bytes < 1:
        _raise_validation("invalid_size_limit", "Maximum size limit must be positive", path)

    try:
        size_bytes = Path(path).stat().st_size
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        _raise_validation("file_missing", "Audio file does not exist", path)
        raise AssertionError from exc

    if size_bytes <= 0:
        _raise_validation("empty_file", "Audio file is empty", path)
    if size_bytes > max_size_bytes:
        _raise_validation("file_too_large", "Audio file exceeds the maximum size", path, size_bytes=size_bytes, max_size_bytes=max_size_bytes)
    return FileSizeResult(size_bytes=size_bytes, max_size_bytes=max_size_bytes)


def _get_duration_metadata(path: str | Path) -> tuple[float, dict[str, Any], list[dict[str, Any]]]:
    """Invoke ffprobe once and return duration plus validated audio metadata."""

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        _raise_validation("ffprobe_unavailable", "ffprobe is unavailable in the runtime", path)

    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-show_entries", "format=duration,format_name:stream=codec_name,codec_type,channels,sample_rate",
                "-of", "json",
                str(Path(path)),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        metadata = json.loads(result.stdout)
        duration = float(metadata["format"]["duration"])
        streams = metadata.get("streams", [])
        audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
        return duration, metadata, audio_streams
    except (subprocess.SubprocessError, json.JSONDecodeError, KeyError, ValueError, TypeError, OSError) as exc:
        _raise_validation("duration_metadata_error", "Audio duration could not be validated", path)
        raise AssertionError from exc


def validate_audio_duration(
    path: str | Path,
    max_duration_seconds: int = MAX_AUDIO_DURATION_SECONDS,
) -> AudioDurationResult:
    if max_duration_seconds < 1:
        _raise_validation("invalid_duration_limit", "Maximum duration limit must be positive", path)

    duration, metadata, audio_streams = _get_duration_metadata(path)
    if duration <= 0:
        _raise_validation("invalid_duration", "Audio duration is invalid", path, duration_seconds=duration)
    if not audio_streams:
        _raise_validation("no_audio_stream", "File contains no audio stream", path)
    if duration > max_duration_seconds:
        _raise_validation("duration_too_long", "Audio duration exceeds the maximum duration", path, duration_seconds=duration, max_duration_seconds=max_duration_seconds)

    first_audio_stream = audio_streams[0]
    return AudioDurationResult(
        duration_seconds=round(duration, 3),
        max_duration_seconds=max_duration_seconds,
        format_name=metadata.get("format", {}).get("format_name"),
        codec_name=first_audio_stream.get("codec_name"),
        channels=int(first_audio_stream.get("channels", 0) or 0),
        sample_rate=int(first_audio_stream.get("sample_rate", 0) or 0),
    )


def validate_audio(
    path: str | Path,
    max_file_size_mb: int = MAX_FILE_SIZE_MB,
    max_duration_seconds: int = MAX_AUDIO_DURATION_SECONDS,
    allowed_roots: list[str | Path] | None = None,
) -> dict:
    """Compatibility wrapper returning the dictionary shape used by TranscriptionService."""

    path_result = validate_audio_path(path, allowed_roots=allowed_roots)
    extension_result = validate_file_extension(path_result.path)
    size_result = validate_file_size(path_result.path, max_size_bytes=max_file_size_mb * 1024 * 1024)
    duration_result = validate_audio_duration(path_result.path, max_duration_seconds=max_duration_seconds)

    return {
        "path": path_result.path,
        "extension": extension_result.extension,
        "duration_seconds": duration_result.duration_seconds,
        "size_bytes": size_result.size_bytes,
        "format_name": duration_result.format_name,
        "codec_name": duration_result.codec_name,
        "channels": duration_result.channels,
        "sample_rate": duration_result.sample_rate,
    }


def safe_delete(
    path: str | Path,
    allowed_root: str | Path | None = None,
    allow_delete: bool = True,
) -> bool:
    """Delete a regular non-symlink file only with explicit permission and an approved root."""

    if not allow_delete:
        _LOGGER.warning("Safe deletion denied because explicit deletion permission was not provided", extra={"audio_path": str(path)})
        return False
    if allowed_root is None:
        _LOGGER.warning("Safe deletion denied because no approved root was provided", extra={"audio_path": str(path)})
        return False

    try:
        root = Path(allowed_root).resolve(strict=True)
        target = Path(path)
        if target.is_symlink() or _is_symlink_component(target):
            _LOGGER.warning("Safe deletion denied for symlink path", extra={"audio_path": str(path)})
            return False
        resolved = target.resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError):
        _LOGGER.warning("Safe deletion denied because target or root is missing", extra={"audio_path": str(path), "allowed_root": str(allowed_root)})
        return False

    if not root.is_dir() or not resolved.is_relative_to(root) or not resolved.is_file():
        _LOGGER.warning("Safe deletion denied by root or file validation", extra={"audio_path": str(path), "allowed_root": str(allowed_root)})
        return False

    try:
        if resolved.is_symlink() or _is_symlink_component(resolved):
            return False
        resolved.unlink()
        _LOGGER.info("Safely deleted audio file", extra={"audio_path": str(resolved)})
        return True
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        _LOGGER.warning("Safe deletion failed", extra={"audio_path": str(path)}, exc_info=(type(exc), exc, exc.__traceback__))
        return False
