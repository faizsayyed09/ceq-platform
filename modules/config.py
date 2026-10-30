from __future__ import annotations

import os
from dataclasses import dataclass

from modules.constants import MAX_AUDIO_DURATION_SECONDS, MAX_FILE_SIZE_MB


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    max_file_size_mb: int = int(os.getenv("MAX_FILE_SIZE_MB", str(MAX_FILE_SIZE_MB)))
    max_audio_duration_seconds: int = int(os.getenv("MAX_AUDIO_DURATION_SECONDS", str(MAX_AUDIO_DURATION_SECONDS)))
    report_dir: str = os.getenv("REPORT_DIR", "generated_reports")
    allow_manual_token_testing: bool = os.getenv("ALLOW_MANUAL_TOKEN_TESTING", "false").lower() == "true"
    phi_protection_mode: str = os.getenv("PHI_PROTECTION_MODE", "AUDIT_MODE")

    genesys_client_id: str | None = os.getenv("GENESYS_CLIENT_ID") or None
    genesys_client_secret: str | None = os.getenv("GENESYS_CLIENT_SECRET") or None
    genesys_region: str = os.getenv("GENESYS_REGION", "mypurecloud.com")


def get_settings() -> Settings:
    return Settings()
