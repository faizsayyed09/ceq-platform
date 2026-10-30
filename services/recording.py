from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from modules.constants import MAX_FILE_SIZE_MB
from modules.exceptions import CeqError, ValidationError
from modules.validation import resolve_artifact_path, validate_safe_filename, validate_uuid
from services.genesys_auth import GenesysAuthService

logger = logging.getLogger(__name__)

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
_SAFE_TRACK_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ALLOWED_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".webm"}


class RecordingDownloadError(CeqError):
    """A recording download failed."""
    code = "RECORDING_DOWNLOAD_ERROR"


class RecordingNotFoundError(CeqError):
    """A recording was not found or is unavailable."""
    code = "RECORDING_NOT_FOUND"


class RecordingAuthorizationError(CeqError):
    """Genesys rejected recording access."""
    code = "RECORDING_AUTHORIZATION_ERROR"


class RecordingStorageError(CeqError):
    """Recording storage could not be accessed or written safely."""
    code = "RECORDING_STORAGE_ERROR"


class RecordingService:
    def __init__(
        self,
        auth_service: GenesysAuthService | None = None,
        storage_path: str | Path | None = None,
        max_file_size_mb: int = MAX_FILE_SIZE_MB,
        poll_attempts: int = 6,
        poll_interval_seconds: float = 5.0,
        http_timeout_seconds: float = 60.0,
        chunk_size_bytes: int = 1024 * 1024,
        retention_hours: float | None = None,
        session: requests.Session | None = None,
        region: str | None = None,
        artifact_store: Any | None = None,
    ) -> None:
        if artifact_store is not None:
            storage_path = getattr(artifact_store, "root", storage_path)
        elif auth_service is not None and hasattr(auth_service, "root") and storage_path is None:
            storage_path = auth_service.root
        if storage_path is None:
            storage_path = os.getenv("RECORDING_STORAGE_PATH", "./recordings")
        if retention_hours is None:
            env_retention = os.getenv("RECORDING_RETENTION_HOURS")
            if env_retention:
                try:
                    retention_hours = float(env_retention)
                except ValueError:
                    logger.warning("Invalid recording retention configuration; retention disabled")
        self.auth_service = auth_service if auth_service is not None and hasattr(auth_service, "authenticate") else GenesysAuthService()
        self.storage_path = Path(storage_path)
        self.max_file_size_mb = max(max_file_size_mb, 1)
        self.poll_attempts = max(poll_attempts, 1)
        self.poll_interval_seconds = max(poll_interval_seconds, 0.0)
        self.http_timeout_seconds = http_timeout_seconds
        self.chunk_size_bytes = max(chunk_size_bytes, 1024)
        self.retention_hours = retention_hours
        self.region = region
        self.session = session or requests.Session()

    def _credentials(self) -> tuple[str, str, dict[str, str]]:
        try:
            if hasattr(self.auth_service, "authenticate"):
                token_result = self.auth_service.authenticate(self.region)
                if hasattr(token_result, "access_token"):
                    token_result = {"access_token": token_result.access_token, "region": getattr(token_result, "region", self.region or "mypurecloud.com")}
            else:
                token_result = self.auth_service.get_access_token()
                if hasattr(token_result, "access_token"):
                    token_result = {"access_token": token_result.access_token, "region": getattr(token_result, "region", self.region or "mypurecloud.com")}
        except Exception as exc:
            raise RecordingAuthorizationError("Genesys authorization failed") from exc
        token = str((token_result or {}).get("access_token", "")).strip()
        region = str((token_result or {}).get("region", self.region or "mypurecloud.com")).strip().lower()
        if not token:
            raise RecordingAuthorizationError("Genesys access token was not available")
        return token, region, {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def _storage_root(self) -> Path:
        try:
            if self.storage_path.exists() and self.storage_path.is_symlink():
                raise RecordingStorageError("Recording storage path is symbolic")
            self.storage_path.mkdir(parents=True, exist_ok=True)
            if self.storage_path.is_symlink():
                raise RecordingStorageError("Recording storage path is symbolic")
            return self.storage_path.resolve(strict=True)
        except RecordingStorageError:
            raise
        except OSError as exc:
            raise RecordingStorageError("Recording storage root could not be created") from exc

    def _get(self, url: str, *, stream: bool = False, params: dict[str, Any] | None = None) -> requests.Response:
        token, _, headers = self._credentials()
        try:
            return self.session.get(url, headers=headers, params=params, timeout=self.http_timeout_seconds, stream=stream)
        except requests.RequestException as exc:
            raise RecordingDownloadError("Genesys recording request failed") from exc

    def fetch_recordings(self, conversation_id: str, format_id: str = "DEFAULT", max_wait_ms: int = 5000, *legacy: Any) -> list[dict[str, Any]]:
        if _UUID_RE.fullmatch(str(format_id or "")) and not isinstance(max_wait_ms, int):
            legacy_region = conversation_id
            conversation_id = str(format_id)
            legacy_token = str(max_wait_ms)
            token, region = legacy_token.strip(), str(legacy_region).strip().lower()
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            format_id, max_wait_ms = "DEFAULT", 5000
        else:
            conversation_id = validate_uuid(conversation_id)
            token, region, headers = self._credentials()
        url = f"https://api.{region}/api/v2/conversations/{conversation_id}/recordings"
        params: dict[str, Any] = {"maxWaitMs": max(0, int(max_wait_ms))}
        if format_id and format_id.upper() != "DEFAULT":
            params["formatId"] = format_id.upper()
        for attempt in range(self.poll_attempts):
            try:
                response = self.session.get(url, headers=headers, params=params, timeout=self.http_timeout_seconds)
            except requests.RequestException as exc:
                raise RecordingDownloadError("Genesys recording request failed") from exc
            status = response.status_code
            if status == 401 or status == 403:
                raise RecordingAuthorizationError("Genesys recording access was denied")
            if status == 404:
                raise RecordingNotFoundError("Genesys recording was not found")
            if status == 202 or (status == 200 and not (response.text or "").strip()):
                if attempt + 1 < self.poll_attempts:
                    time.sleep(self.poll_interval_seconds)
                    continue
                raise RecordingNotFoundError("Genesys recording is still processing")
            if status >= 400:
                raise RecordingDownloadError("Genesys recording service returned an error")
            try:
                payload = response.json()
            except ValueError as exc:
                raise RecordingDownloadError("Genesys recording response was invalid") from exc
            if isinstance(payload, dict):
                return payload.get("entities") or ([payload] if payload else [])
            if isinstance(payload, list):
                return payload
            raise RecordingDownloadError("Genesys recording response was invalid")
        raise RecordingNotFoundError("Genesys recording remained unavailable")

    def get_recording_metadata(self, conversation_id: str) -> dict[str, Any]:
        conversation_id = validate_uuid(conversation_id)
        recordings = self.fetch_recordings(conversation_id)
        audio = next((row for row in recordings if row.get("media") == "audio" and row.get("fileState", "AVAILABLE") == "AVAILABLE"), None)
        if not audio:
            raise RecordingNotFoundError("No available audio recording was found")
        queue_ids: list[str] = []
        wrapup_ids: list[str] = []
        for key, target in (("queueIds", queue_ids), ("queue_id", queue_ids), ("wrapupCodeIds", wrapup_ids), ("wrapup_codes", wrapup_ids)):
            value = audio.get(key)
            values = value if isinstance(value, list) else ([value] if value else [])
            for item in values:
                item_value = str(item)
                if item_value and item_value not in target:
                    target.append(item_value)
        return {
            "conversation_id": conversation_id,
            "recording_id": str(audio.get("id") or ""),
            "start_time": audio.get("startTime") or "",
            "end_time": audio.get("endTime") or "",
            "queue_ids": queue_ids,
            "wrapup_code_ids": wrapup_ids,
        }

    def discover_recordings(self, conversation_id: str, format_id: str = "DEFAULT") -> dict[str, Any]:
        conversation_id = validate_uuid(conversation_id)
        recordings = self.fetch_recordings(conversation_id, format_id=format_id)
        audio = next((row for row in recordings if row.get("media") == "audio"), None)
        if not audio:
            raise RecordingNotFoundError("No audio recording was found")
        if audio.get("fileState", "AVAILABLE") != "AVAILABLE":
            raise RecordingNotFoundError("Audio recording is not available")
        tracks: list[dict[str, Any]] = []
        for key, block in sorted((audio.get("mediaUris") or {}).items(), key=lambda item: str(item[0])):
            if not isinstance(block, dict):
                continue
            uri = block.get("mediaUri")
            track_key = str(key)
            if uri and str(uri).startswith("https://") and _SAFE_TRACK_RE.fullmatch(track_key):
                tracks.append({"track": track_key, "media_uri": str(uri), "content_type": block.get("contentType")})
        if not tracks:
            raise RecordingNotFoundError("No downloadable recording tracks were found")
        return {"tracks": tracks, "dual_channel": len(tracks) == 2}

    def _canonical_filename(self, conversation_id: str, recording_id: str, track: str, suffix: str = ".webm") -> str:
        safe_track = re.sub(r"[^A-Za-z0-9_-]", "_", str(track or "track"))[:64]
        safe_recording = re.sub(r"[^A-Za-z0-9_-]", "_", str(recording_id or "recording"))[:64]
        return validate_safe_filename(f"{conversation_id}_{safe_recording}_track{safe_track}{suffix}")

    def download_recording(self, conversation_id: str, track: str | None = None, recording_id: str | None = None, filename: str | None = None, force_redownload: bool = False, format_id: str = "DEFAULT", delete_after_processing: bool = False) -> dict[str, Any]:
        conversation_id = validate_uuid(conversation_id)
        discovery = self.discover_recordings(conversation_id, format_id=format_id)
        tracks = discovery["tracks"]
        selected = next((row for row in tracks if row["track"] == str(track)), tracks[0]) if track is not None else tracks[0]
        if not recording_id:
            metadata = self.get_recording_metadata(conversation_id)
            recording_id = metadata["recording_id"] or "recording"
        suffix = ".webm"
        content_type = str(selected.get("content_type") or "")
        if "mpeg" in content_type or "mp3" in content_type:
            suffix = ".mp3"
        elif "wav" in content_type:
            suffix = ".wav"
        elif "ogg" in content_type:
            suffix = ".ogg"
        canonical = self._canonical_filename(conversation_id, recording_id, selected["track"], suffix)
        root = self._storage_root()
        final_path = resolve_artifact_path(root, canonical)
        if final_path.is_symlink():
            raise RecordingStorageError("Refusing to overwrite a symbolic-link recording")
        if final_path.is_file() and final_path.stat().st_size > 0 and not force_redownload:
            final_path.touch()
            result = {"file_path": str(final_path), "filename": canonical, "size_bytes": final_path.stat().st_size, "track": selected["track"], "reused": True}
            if delete_after_processing:
                result["deleted_after_processing"] = self.delete_recording(final_path)
            return result

        part_path = final_path.with_name(final_path.name + f".{os.getpid()}.part")
        if part_path.is_symlink():
            raise RecordingStorageError("Refusing to write a symbolic-link partial file")
        try:
            token, _, headers = self._credentials()
            response = self.session.get(selected["media_uri"], headers=headers, timeout=self.http_timeout_seconds, stream=True)
            status = response.status_code
            if status == 401 or status == 403:
                raise RecordingAuthorizationError("Genesys recording download was denied")
            if status == 404:
                raise RecordingNotFoundError("Recording media was not found")
            if status >= 400:
                raise RecordingDownloadError("Genesys recording download failed")
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > self.max_file_size_mb * 1024 * 1024:
                        raise RecordingDownloadError("Recording exceeds configured size limit")
                except ValueError as exc:
                    raise RecordingDownloadError("Recording content length was invalid") from exc
            total = 0
            with part_path.open("wb") as output:
                for chunk in response.iter_content(chunk_size=self.chunk_size_bytes):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > self.max_file_size_mb * 1024 * 1024:
                        raise RecordingDownloadError("Recording exceeds configured size limit")
                    output.write(chunk)
            if total <= 0:
                raise RecordingDownloadError("Downloaded recording was empty")
            os.replace(part_path, final_path)
        except RecordingAuthorizationError:
            raise
        except RecordingNotFoundError:
            raise
        except RecordingDownloadError:
            raise
        except requests.RequestException as exc:
            raise RecordingDownloadError("Recording download failed") from exc
        except OSError as exc:
            raise RecordingStorageError("Recording could not be written to safe storage") from exc
        finally:
            try:
                if part_path.exists() and not part_path.is_symlink():
                    part_path.unlink()
            except OSError:
                logger.warning("Partial recording cleanup failed")
        result = {"file_path": str(final_path), "filename": canonical, "size_bytes": total, "track": selected["track"], "reused": False}
        if delete_after_processing:
            result["deleted_after_processing"] = self.delete_recording(final_path)
        return result

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None

    def get_hold_events(self, conversation_id: str, recording_start: str | None = None) -> dict[str, Any]:
        conversation_id = validate_uuid(conversation_id)
        token, region, headers = self._credentials()
        url = f"https://api.{region}/api/v2/analytics/conversations/{conversation_id}/details"
        try:
            response = self.session.get(url, headers=headers, timeout=self.http_timeout_seconds)
        except requests.RequestException as exc:
            raise RecordingDownloadError("Genesys hold-event request failed") from exc
        if response.status_code == 401 or response.status_code == 403:
            raise RecordingAuthorizationError("Genesys hold-event access was denied")
        if response.status_code == 404:
            raise RecordingNotFoundError("Genesys hold-event details were not found")
        if response.status_code >= 400:
            raise RecordingDownloadError("Genesys hold-event request failed")
        try:
            data = response.json()
        except ValueError as exc:
            raise RecordingDownloadError("Genesys hold-event response was invalid") from exc
        origin = self._parse_timestamp(recording_start) or self._parse_timestamp(data.get("conversationStart"))
        if origin is None:
            raise RecordingDownloadError("Recording start time is unavailable for hold alignment")
        holds: list[list[float]] = []
        for participant in data.get("participants", []) or []:
            if participant.get("purpose") not in ("agent", "user"):
                continue
            for session in participant.get("sessions", []) or []:
                if session.get("mediaType") and session.get("mediaType") != "voice":
                    continue
                for segment in session.get("segments", []) or []:
                    if segment.get("segmentType") != "hold":
                        continue
                    start = self._parse_timestamp(segment.get("segmentStart"))
                    end = self._parse_timestamp(segment.get("segmentEnd"))
                    if start and end:
                        a, b = (start - origin).total_seconds(), (end - origin).total_seconds()
                        if b > a:
                            holds.append([a, b])
        holds.sort()
        merged: list[list[float]] = []
        for start, end in holds:
            if merged and start <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        events = [{"start": round(a, 1), "end": round(b, 1), "duration": round(b - a, 1)} for a, b in merged]
        return {"hold_events": events, "source": "genesys"}

    def purge_expired(self, retention_hours: float | None = None) -> int:
        hours = self.retention_hours if retention_hours is None else retention_hours
        if hours is None:
            return 0
        if hours <= 0:
            raise ValidationError("Retention hours must be positive")
        root = self._storage_root()
        cutoff = time.time() - float(hours) * 3600
        removed = 0
        for path in root.iterdir():
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                if path.stat().st_mtime < cutoff:
                    if self.safe_delete(path):
                        removed += 1
            except OSError:
                logger.warning("Expired recording cleanup failed for filename=%s", path.name)
        return removed

    def safe_delete(self, path: str | Path) -> bool:
        root = self._storage_root()
        target = Path(path)
        if target.is_symlink():
            return False
        try:
            resolved = target.resolve(strict=True)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise RecordingStorageError("Recording deletion path could not be resolved") from exc
        try:
            resolved.relative_to(root)
        except ValueError:
            return False
        if not resolved.is_file():
            return False
        try:
            resolved.unlink()
            return True
        except OSError as exc:
            raise RecordingStorageError("Recording file could not be deleted safely") from exc

    def delete_recording(self, path: str | Path) -> bool:
        return self.safe_delete(path)

    async def download_media(self, media_uri: str, filename: str, access_token: str | None = None, *, session: requests.Session | None = None) -> dict[str, Any]:
        """Backward-compatible adapter; canonical downloads use download_recording()."""
        from modules.validation import validate_safe_filename

        if not str(media_uri).startswith("https://"):
            raise ValidationError("Recording media URI must use HTTPS")
        canonical = validate_safe_filename(filename)
        root = self._storage_root()
        final_path = resolve_artifact_path(root, canonical)
        if final_path.is_symlink():
            raise RecordingStorageError("Refusing to overwrite a symbolic-link recording")
        http = session or self.session
        if access_token:
            headers = {"Authorization": f"Bearer {access_token.strip()}", "Accept": "audio/*"}
        else:
            _, _, headers = self._credentials()
        part_path = final_path.with_name(final_path.name + f".{os.getpid()}.part")
        total = 0
        try:
            response = http.get(media_uri, headers=headers, timeout=self.http_timeout_seconds, stream=True)
            if response.status_code == 401 or response.status_code == 403:
                raise RecordingAuthorizationError("Genesys recording download was denied")
            if response.status_code == 404:
                raise RecordingNotFoundError("Recording media was not found")
            if response.status_code >= 400:
                raise RecordingDownloadError("Genesys recording download failed")
            with part_path.open("wb") as output:
                for chunk in response.iter_content(chunk_size=self.chunk_size_bytes):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > self.max_file_size_mb * 1024 * 1024:
                        raise RecordingDownloadError("Recording exceeds configured size limit")
                    output.write(chunk)
            if total <= 0:
                raise RecordingDownloadError("Downloaded recording was empty")
            os.replace(part_path, final_path)
        except RecordingAuthorizationError:
            raise
        except RecordingNotFoundError:
            raise
        except RecordingDownloadError:
            raise
        except requests.RequestException as exc:
            raise RecordingDownloadError("Genesys recording download failed") from exc
        except OSError as exc:
            raise RecordingStorageError("Recording could not be written to safe storage") from exc
        finally:
            try:
                if part_path.exists() and not part_path.is_symlink():
                    part_path.unlink()
            except OSError:
                logger.warning("Partial recording cleanup failed")
        return {"filename": canonical, "size_bytes": total, "location": str(final_path)}
