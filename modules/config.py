from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from modules.constants import MAX_AUDIO_DURATION_SECONDS, MAX_FILE_SIZE_MB


def read_secret_file(environment_name: str) -> str | None:
    file_name = os.getenv(f"{environment_name}_FILE")
    if file_name:
        try:
            return Path(file_name).read_text(encoding="utf-8").strip() or None
        except OSError as exc:
            raise RuntimeError(f"Unable to read {environment_name}_FILE") from exc
    return os.getenv(environment_name) or None


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    api_service_token: str | None = read_secret_file("CEQ_API_SERVICE_TOKEN")
    matcha_base_url: str | None = os.getenv("MATCHA_BASE_URL") or None
    matcha_api_key: str | None = read_secret_file("MATCHA_API_KEY")
    matcha_user_agent: str | None = os.getenv("MATCHA_USER_AGENT") or None
    matchaos_base_url: str | None = os.getenv("MATCHAOS_BASE_URL") or None
    matchaos_api_key: str | None = read_secret_file("MATCHAOS_API_KEY")
    matchaos_model: str | None = os.getenv("MATCHAOS_MODEL") or None
    matchaos_rate_limit_per_minute: int = int(os.getenv("MATCHAOS_RATE_LIMIT_PER_MINUTE", "120"))
    snow_folder_id: str | None = os.getenv("SNOW_FOLDER_ID") or None
    snow_mission_id: str | None = os.getenv("SNOW_MISSION_ID") or None
    snow_file_id: str | None = os.getenv("SNOW_FILE_ID") or None
    snow_filename: str | None = os.getenv("SNOW_FILENAME") or None
    azure_storage_account_url: str | None = os.getenv("AZURE_STORAGE_ACCOUNT_URL") or None
    azure_blob_snow_container: str = os.getenv("AZURE_BLOB_SNOW_CONTAINER", "snow")
    azure_blob_kb_container: str = os.getenv("AZURE_BLOB_KB_CONTAINER", "ceq-kb")
    azure_blob_evidence_container: str = os.getenv("AZURE_BLOB_EVIDENCE_CONTAINER", "evidence")
    azure_search_endpoint: str | None = os.getenv("AZURE_SEARCH_ENDPOINT") or None
    azure_search_index: str = os.getenv("AZURE_SEARCH_INDEX", "ceq-kb")
    max_file_size_mb: int = int(os.getenv("MAX_FILE_SIZE_MB", str(MAX_FILE_SIZE_MB)))
    max_audio_duration_seconds: int = int(os.getenv("MAX_AUDIO_DURATION_SECONDS", str(MAX_AUDIO_DURATION_SECONDS)))
    report_dir: str = os.getenv("REPORT_DIR", "generated_reports")
    allow_manual_token_testing: bool = os.getenv("ALLOW_MANUAL_TOKEN_TESTING", "false").lower() == "true"
    phi_protection_mode: str = os.getenv("PHI_PROTECTION_MODE", "AUDIT_MODE")
    prematch_mode: str = os.getenv("PREMATCH_MODE", "shadow").lower()
    prematch_cache_enabled: bool = os.getenv("PREMATCH_CACHE_ENABLED", "false").lower() == "true"
    prematch_top_n: int = int(os.getenv("PREMATCH_TOP_N", "3"))

    genesys_client_id: str | None = os.getenv("GENESYS_CLIENT_ID") or None
    genesys_client_secret: str | None = os.getenv("GENESYS_CLIENT_SECRET") or None
    genesys_region: str = os.getenv("GENESYS_REGION", "mypurecloud.com")


def get_settings() -> Settings:
    return Settings()
