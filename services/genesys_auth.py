"""Framework-independent Genesys Cloud authentication service."""

from __future__ import annotations

from dataclasses import dataclass
import os
import threading
import time
from typing import Any, Mapping, MutableMapping, Optional

import requests


DEFAULT_REGION = "mypurecloud.com"


class GenesysAuthError(RuntimeError):
    """Base exception for Genesys authentication failures."""

    def __init__(self, code: str, message: str, *, status_code: int | None = None, detail: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.status_code is not None:
            result["status_code"] = self.status_code
        if self.detail:
            result["detail"] = self.detail
        return result


class GenesysConfigurationError(GenesysAuthError):
    def __init__(self, message: str) -> None:
        super().__init__("GENESYS_CONFIGURATION_ERROR", message)


class GenesysAuthenticationError(GenesysAuthError):
    def __init__(self, message: str, *, status_code: int | None = None, detail: str | None = None) -> None:
        super().__init__("GENESYS_AUTHENTICATION_ERROR", message, status_code=status_code, detail=detail)


class GenesysOrganizationError(GenesysAuthError):
    def __init__(self, message: str, *, status_code: int | None = None, detail: str | None = None) -> None:
        super().__init__("GENESYS_ORGANIZATION_ERROR", message, status_code=status_code, detail=detail)


@dataclass(frozen=True)
class GenesysAuthConfiguration:
    region: str = DEFAULT_REGION
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    manual_token: Optional[str] = None
    verify_org: bool = True
    timeout_seconds: float = 15.0
    cache_refresh_margin_seconds: float = 60.0

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "GenesysAuthConfiguration":
        env = os.environ if environ is None else environ
        return cls(
            region=normalize_region(env.get("GENESYS_REGION", DEFAULT_REGION)),
            client_id=_optional_secret(env.get("GENESYS_CLIENT_ID")),
            client_secret=_optional_secret(env.get("GENESYS_CLIENT_SECRET")),
            manual_token=_optional_secret(env.get("GENESYS_MANUAL_TOKEN")),
            verify_org=_parse_bool(env.get("GENESYS_VERIFY_ORGANIZATION", "true")),
            timeout_seconds=_parse_float(env.get("GENESYS_HTTP_TIMEOUT_SECONDS", "15"), 15.0, "GENESYS_HTTP_TIMEOUT_SECONDS"),
            cache_refresh_margin_seconds=_parse_float(env.get("GENESYS_TOKEN_CACHE_MARGIN_SECONDS", "60"), 60.0, "GENESYS_TOKEN_CACHE_MARGIN_SECONDS"),
        )


@dataclass(frozen=True)
class TokenOptions:
    region: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    manual_token: Optional[str] = None
    force_refresh: bool = False
    verify_org: Optional[bool] = None


@dataclass(frozen=True)
class OrganizationInfo:
    id: Optional[str] = None
    name: Optional[str] = None


@dataclass(frozen=True)
class TokenResult:
    access_token: str
    region: str
    source: str
    expires_in: Optional[int] = None
    organization: Optional[OrganizationInfo] = None

    def to_dict(self, *, include_token: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {"region": self.region, "source": self.source}
        if include_token:
            result["access_token"] = self.access_token
        if self.expires_in is not None:
            result["expires_in"] = self.expires_in
        if self.organization is not None:
            result["organization"] = {"id": self.organization.id, "name": self.organization.name}
        return result


@dataclass(frozen=True)
class _CacheEntry:
    token: str
    expires_at: float
    expires_in: Optional[int]


def normalize_region(region: str | None) -> str:
    """Normalize a Genesys region to a DNS/API domain without a scheme or prefix."""
    value = (region or DEFAULT_REGION).strip().lower()
    for prefix in ("https://", "http://"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    value = value.split("/", 1)[0].strip(".")
    for prefix in ("apps.", "login.", "api."):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    return value or DEFAULT_REGION


def _optional_secret(value: str | None) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_float(value: str, default: float, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise GenesysConfigurationError(f"{name} must be a non-negative number") from exc
    if parsed < 0:
        raise GenesysConfigurationError(f"{name} must be a non-negative number")
    return parsed


class GenesysAuthService:
    """OAuth and organization operations for Genesys Cloud."""

    def __init__(
        self,
        configuration: GenesysAuthConfiguration | None = None,
        *,
        session: Any | None = None,
        clock: Any | None = None,
    ) -> None:
        self.configuration = configuration or GenesysAuthConfiguration.from_environment()
        self._session = session or requests.Session()
        self._clock = clock or time.time
        self._cache: MutableMapping[tuple[str, str], _CacheEntry] = {}
        self._cache_lock = threading.Lock()

    def get_access_token(self, options: TokenOptions | None = None) -> TokenResult:
        opts = options or TokenOptions()
        region = normalize_region(opts.region or self.configuration.region)
        manual = _optional_secret(opts.manual_token if opts.manual_token is not None else self.configuration.manual_token)

        if manual:
            manual = manual[7:].strip() if manual.lower().startswith("bearer ") else manual
            result = TokenResult(access_token=manual, region=region, source="manual")
            return self._possibly_verify_org(result, opts)

        client_id = _optional_secret(opts.client_id if opts.client_id is not None else self.configuration.client_id)
        client_secret = _optional_secret(opts.client_secret if opts.client_secret is not None else self.configuration.client_secret)
        if not client_id or not client_secret:
            raise GenesysConfigurationError("Provide manual_token or both client_id and client_secret")

        cache_key = (region, client_id)
        if opts.force_refresh:
            with self._cache_lock:
                self._cache.pop(cache_key, None)

        cached = self._get_cached(cache_key)
        if cached is not None:
            remaining = max(0, int(cached.expires_at - self._clock()))
            result = TokenResult(
                access_token=cached.token,
                region=region,
                source="client_credentials_cached",
                expires_in=remaining,
            )
            return self._possibly_verify_org(result, opts)

        login_url = f"https://login.{region}/oauth/token"
        try:
            response = self._session.post(
                login_url,
                data={"grant_type": "client_credentials"},
                auth=(client_id, client_secret),
                timeout=self.configuration.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise GenesysAuthenticationError("Token request failed", detail=str(exc)) from exc
        except Exception as exc:
            raise GenesysAuthenticationError("Token request failed", detail=str(exc)) from exc

        status_code = getattr(response, "status_code", 0)
        if status_code != 200:
            detail = self._response_text(response)
            raise GenesysAuthenticationError(
                f"Token request failed with HTTP {status_code}",
                status_code=status_code,
                detail=detail[:300] or None,
            )

        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise GenesysAuthenticationError("Token response was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise GenesysAuthenticationError("Token response was not a JSON object")

        access_token = _optional_secret(payload.get("access_token"))
        if not access_token:
            raise GenesysAuthenticationError("Token response did not contain access_token")

        try:
            expires_in = int(payload.get("expires_in", 3600))
        except (TypeError, ValueError):
            expires_in = 3600
        expires_in = max(0, expires_in)

        entry = _CacheEntry(token=access_token, expires_at=self._clock() + expires_in, expires_in=expires_in)
        with self._cache_lock:
            self._cache[cache_key] = entry

        result = TokenResult(
            access_token=access_token,
            region=region,
            source="client_credentials",
            expires_in=expires_in,
        )
        return self._possibly_verify_org(result, opts)

    def invalidate(self, region: str | None = None, client_id: str | None = None) -> int:
        """Invalidate matching cache entries and return the number removed."""
        with self._cache_lock:
            if region is None and client_id is None:
                removed = len(self._cache)
                self._cache.clear()
                return removed
            normalized_region = normalize_region(region) if region is not None else None
            keys_to_remove = [
                key for key in self._cache
                if (normalized_region is None or key[0] == normalized_region)
                and (client_id is None or key[1] == client_id)
            ]
            for key in keys_to_remove:
                self._cache.pop(key, None)
            return len(keys_to_remove)

    def verify_organization(self, token: TokenResult | str) -> OrganizationInfo:
        access_token = token.access_token if isinstance(token, TokenResult) else token.strip()
        region = token.region if isinstance(token, TokenResult) else normalize_region(self.configuration.region)
        if not access_token:
            raise GenesysOrganizationError("Access token is empty")

        url = f"https://api.{region}/api/v2/organizations/me"
        try:
            response = self._session.get(
                url,
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                timeout=self.configuration.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise GenesysOrganizationError("Organization verification failed", detail=str(exc)) from exc
        except Exception as exc:
            raise GenesysOrganizationError("Organization verification failed", detail=str(exc)) from exc

        status_code = getattr(response, "status_code", 0)
        if status_code != 200:
            raise GenesysOrganizationError(
                f"Organization verification failed with HTTP {status_code}",
                status_code=status_code,
                detail=self._response_text(response)[:300] or None,
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise GenesysOrganizationError("Organization response was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise GenesysOrganizationError("Organization response was not a JSON object")
        return OrganizationInfo(id=_optional_string(payload.get("id")), name=_optional_string(payload.get("name")))

    def _possibly_verify_org(self, result: TokenResult, options: TokenOptions) -> TokenResult:
        verify_org = options.verify_org if options.verify_org is not None else self.configuration.verify_org
        if not verify_org:
            return result
        organization = self.verify_organization(result)
        return TokenResult(
            access_token=result.access_token,
            region=result.region,
            source=result.source,
            expires_in=result.expires_in,
            organization=organization,
        )

    def _get_cached(self, cache_key: tuple[str, str]) -> _CacheEntry | None:
        with self._cache_lock:
            entry = self._cache.get(cache_key)
            if entry is None:
                return None
            margin = self.configuration.cache_refresh_margin_seconds
            if entry.expires_at <= self._clock() + margin:
                self._cache.pop(cache_key, None)
                return None
            return entry

    @staticmethod
    def _response_text(response: Any) -> str:
        text = getattr(response, "text", "")
        return text if isinstance(text, str) else ""


def _optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None
