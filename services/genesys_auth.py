from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Any

import requests

from modules.exceptions import ExternalServiceError, SecurityError, ValidationError


VALID_GENESYS_REGIONS = frozenset({
    "mypurecloud.com", "mypurecloud.ie", "mypurecloud.com.au", "mypurecloud.jp",
    "mypurecloud.de", "usw2.pure.cloud", "cac1.pure.cloud", "euw2.pure.cloud",
    "apne2.pure.cloud", "apne3.pure.cloud", "apse2.pure.cloud", "sae1.pure.cloud",
    "mec1.pure.cloud",
})

logger = logging.getLogger("genesys_auth")


class GenesysAuthService:
    def __init__(
        self,
        region: str = "mypurecloud.com",
        client_id: str | None = None,
        client_secret: str | None = None,
        allow_manual_token_testing: bool = False,
        http_timeout_seconds: float = 15.0,
        max_cache_entries: int = 50,
    ) -> None:
        self.region = region.strip().lower()
        self.client_id = client_id
        self.client_secret = client_secret
        self.allow_manual_token_testing = allow_manual_token_testing
        self.http_timeout_seconds = http_timeout_seconds
        self.max_cache_entries = max_cache_entries
        self._cache: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def _validate_region(self, region: str) -> str:
        normalized = (region or "mypurecloud.com").strip().lower()
        if normalized not in VALID_GENESYS_REGIONS:
            raise ValidationError("Invalid Genesys region")
        return normalized

    def authenticate(self, region: str | None = None, manual_token: str | None = None) -> dict[str, str]:
        normalized_region = self._validate_region(region or self.region)
        manual = (manual_token or "").strip()

        if manual:
            if not self.allow_manual_token_testing:
                logger.warning("Manual Genesys token rejected because testing mode is disabled")
                raise SecurityError("Manual token testing is disabled")
            if manual.lower().startswith("bearer "):
                manual = manual[7:].strip()
            logger.warning("Manual Genesys token accepted in testing mode; token value excluded from logs")
            return {"access_token": manual, "region": normalized_region, "source": "manual"}

        if not self.client_id or not self.client_secret:
            raise ValidationError("Genesys client credentials are not configured")

        with self._lock:
            cached = self._cache.get(normalized_region + ":" + self.client_id)
            if cached and cached["expires_at"] > time.time() + 30:
                return {"access_token": cached["token"], "region": normalized_region, "source": "client_credentials_cached"}

        token_url = f"https://login.{normalized_region}/oauth/token"
        try:
            response = requests.post(
                token_url,
                data={"grant_type": "client_credentials"},
                auth=(self.client_id, self.client_secret),
                timeout=self.http_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            access_token = payload["access_token"]
            expires_in = max(60, min(int(payload.get("expires_in", 3600)), 86400))
        except requests.RequestException as exc:
            logger.error("Genesys OAuth request failed type=%s", exc.__class__.__name__)
            raise ExternalServiceError("Genesys authentication request failed") from exc
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("Genesys OAuth response was invalid")
            raise ExternalServiceError("Genesys authentication response was invalid") from exc

        cache_key = normalized_region + ":" + self.client_id
        with self._lock:
            now = time.time()
            for key, entry in list(self._cache.items()):
                if entry["expires_at"] <= now:
                    self._cache.pop(key, None)
            if len(self._cache) >= self.max_cache_entries:
                oldest_key = min(self._cache, key=lambda key: self._cache[key]["expires_at"])
                self._cache.pop(oldest_key, None)
            self._cache[cache_key] = {"token": access_token, "expires_at": now + expires_in}

        logger.info("Genesys OAuth token acquired for client_id ending=%s", self.client_id[-4:].replace(" ", "*"))
        return {"access_token": access_token, "region": normalized_region, "source": "client_credentials"}
