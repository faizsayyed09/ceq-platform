from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Mapping

import requests

from modules.exceptions import CeqError, ValidationError


class MatchaOsConfigurationError(CeqError):
    pass


class MatchaOsProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        user_agent: str,
        rate_limit_per_minute: int = 120,
        timeout_seconds: float = 60.0,
        session: requests.Session | None = None,
    ) -> None:
        if not base_url or not base_url.startswith("https://"):
            raise MatchaOsConfigurationError("MATCHAOS_BASE_URL must be an HTTPS URL")
        if not api_key:
            raise MatchaOsConfigurationError("MATCHAOS_API_KEY is required")
        if not api_key.startswith("mos_sk_live_"):
            raise MatchaOsConfigurationError("MATCHAOS_API_KEY must use the MatchaOS key family")
        if not user_agent.strip():
            raise MatchaOsConfigurationError("MATCHA_USER_AGENT is required")
        if rate_limit_per_minute < 1 or rate_limit_per_minute > 120:
            raise ValidationError("MatchaOS rate limit must be between 1 and 120")

        base_url = base_url.rstrip("/")
        self.base_url = base_url if base_url.endswith("/api") else base_url + "/api"
        self.api_key = api_key
        self.user_agent = user_agent
        self.rate_limit_per_minute = rate_limit_per_minute
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self._request_times: deque[float] = deque()
        self._lock = threading.RLock()

    def list_models(self, timeout_seconds: float | None = None) -> dict[str, Any]:
        response = self._request("GET", "/v1/models", timeout_seconds=timeout_seconds)
        return response.json()

    def complete_mission(
        self,
        *,
        mission_id: str,
        input_text: str,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        mission_id = mission_id.strip()
        if not mission_id:
            raise ValidationError("mission_id is required")
        if not input_text.strip():
            raise ValidationError("input_text is required")
        response = self._request(
            "POST",
            "/v1/completions",
            json={"mission_id": mission_id, "input": input_text},
            timeout_seconds=timeout_seconds,
        )
        return response.json()

    def list_missions(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        response = self._request(
            "GET",
            "/v1/missions",
            params={"limit": limit, "offset": offset},
            timeout_seconds=timeout_seconds,
        )
        return response.json()

    def list_folders(
        self,
        *,
        mission_id: str,
        limit: int = 100,
        offset: int = 0,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        mission_id = mission_id.strip()
        if not mission_id:
            raise ValidationError("mission_id is required")
        response = self._request(
            "GET",
            f"/v1/missions/{mission_id}/folders",
            params={"limit": limit, "offset": offset},
            timeout_seconds=timeout_seconds,
        )
        return response.json()

    def create_folder(
        self,
        *,
        mission_id: str,
        name: str,
        description: str = "",
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        mission_id = mission_id.strip()
        name = name.strip()
        if not mission_id:
            raise ValidationError("mission_id is required")
        if not name:
            raise ValidationError("folder name is required")
        response = self._request(
            "POST",
            f"/v1/missions/{mission_id}/folders",
            json={"name": name, "description": description},
            timeout_seconds=timeout_seconds,
        )
        return response.json()

    def delete_folder(
        self,
        *,
        folder_id: str,
        timeout_seconds: float | None = None,
    ) -> requests.Response:
        folder_id = folder_id.strip()
        if not folder_id:
            raise ValidationError("folder_id is required")
        return self._request(
            "DELETE",
            f"/v1/folders/{folder_id}",
            timeout_seconds=timeout_seconds,
        )

    def list_files(
        self,
        *,
        folder_id: str,
        limit: int = 100,
        offset: int = 0,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        folder_id = folder_id.strip()
        if not folder_id:
            raise ValidationError("folder_id is required")
        response = self._request(
            "GET",
            f"/v1/folders/{folder_id}/files",
            params={"limit": limit, "offset": offset},
            timeout_seconds=timeout_seconds,
        )
        return response.json()

    def upload_file(
        self,
        *,
        folder_id: str,
        file_path: str | Path,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        folder_id = folder_id.strip()
        if not folder_id:
            raise ValidationError("folder_id is required")
        path = Path(file_path)
        if not path.is_file():
            raise ValidationError("file_path must refer to an existing file")
        with path.open("rb") as file_handle:
            response = self._request(
                "POST",
                f"/v1/folders/{folder_id}/files",
                files={"file": (path.name, file_handle)},
                timeout_seconds=timeout_seconds,
            )
        return response.json()

    def delete_file(
        self,
        *,
        file_id: str,
        timeout_seconds: float | None = None,
    ) -> requests.Response:
        file_id = file_id.strip()
        if not file_id:
            raise ValidationError("file_id is required")
        return self._request(
            "DELETE",
            f"/v1/files/{file_id}",
            timeout_seconds=timeout_seconds,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        files: Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> requests.Response:
        self._wait_for_rate_slot()
        headers = {
            "User-Agent": self.user_agent,
            "matcha-api-key": self.api_key,
            "Accept": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.session.request(
                    method,
                    self.base_url + path,
                    headers=headers,
                    json=json,
                    params=params,
                    files=files,
                    timeout=timeout_seconds or self.timeout_seconds,
                )
                if response.status_code == 429:
                    retry_after = self._retry_after_seconds(response.headers.get("retry-after"))
                    if attempt < 2:
                        time.sleep(retry_after)
                        continue
                    raise MatchaOsConfigurationError("MatchaOS rate limit exceeded")
                if response.status_code >= 500:
                    last_error = MatchaOsConfigurationError("MatchaOS provider returned a server error")
                    if attempt < 2:
                        time.sleep(2**attempt)
                        continue
                    raise last_error
                if response.status_code >= 400:
                    raise MatchaOsConfigurationError(
                        f"MatchaOS provider returned HTTP {response.status_code}"
                    )
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2**attempt)
                    continue
        raise MatchaOsConfigurationError("MatchaOS request failed") from last_error

    def _wait_for_rate_slot(self) -> None:
        with self._lock:
            now = time.monotonic()
            window_start = now - 60.0
            while self._request_times and self._request_times[0] <= window_start:
                self._request_times.popleft()
            if len(self._request_times) >= self.rate_limit_per_minute:
                wait_seconds = max(0.0, 60.0 - (now - self._request_times[0]))
                time.sleep(wait_seconds)
                return self._wait_for_rate_slot()
            self._request_times.append(now)

    @staticmethod
    def _retry_after_seconds(value: str | None) -> float:
        if not value:
            return 1.0
        try:
            return max(0.0, float(value))
        except ValueError:
            pass
        try:
            parsed = parsedate_to_datetime(value)
            return max(0.0, (parsed - datetime.now(parsed.tzinfo)).total_seconds())
        except (TypeError, ValueError):
            return 1.0
