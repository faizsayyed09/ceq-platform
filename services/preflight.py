from __future__ import annotations

import os
import shutil
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path


class RuntimePreflight:
    def __init__(self, environment: dict[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else dict(os.environ)

    def check_secret(self, name: str, *, required: bool) -> tuple[bool, str]:
        value = self.environment.get(name)
        file_name = self.environment.get(f"{name}_FILE")
        if file_name:
            path = Path(file_name)
            if path.is_file():
                return True, f"{name}_FILE readable"
            return False, f"{name}_FILE unreadable" if required else f"optional {name}_FILE not set"
        if value:
            return True, f"{name} set"
        return (False, f"{name} missing") if required else (True, f"{name} not configured")

    def check_url(self, name: str, url: str | None) -> tuple[bool, str]:
        if not url:
            return True, f"{name} optional"
        try:
            parsed = urllib.parse.urlparse(url)
        except Exception:
            return False, f"{name} invalid"
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False, f"{name} invalid"
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status >= 500:
                    return False, f"{name} unhealthy"
        except (OSError, urllib.error.URLError):
            return False, f"{name} host unreachable"
        return True, f"{name} host reachable"

    def run(self, *, role: str = "api") -> dict[str, object]:
        checks: list[dict[str, object]] = []
        if role not in {"api", "worker", "preflight"}:
            checks.append({"name": "role", "passed": False, "detail": "unsupported role"})
        else:
            checks.append({"name": "role", "passed": True, "detail": role})

        production = self.environment.get("APP_ENV", "development").lower() in {"production", "prod"}
        passed, detail = self.check_secret("CEQ_API_SERVICE_TOKEN", required=production and role == "api")
        checks.append({"name": "service authentication", "passed": passed, "detail": detail})

        for command in ("ffmpeg", "ffprobe"):
            available = shutil.which(command) is not None
            checks.append({"name": command, "passed": available, "detail": "available" if available else "missing"})

        report_dir = Path(self.environment.get("REPORT_DIR", "generated_reports"))
        try:
            report_dir.mkdir(parents=True, exist_ok=True)
            writable = os.access(report_dir, os.W_OK)
        except OSError:
            writable = False
        checks.append({"name": "report storage", "passed": writable, "detail": "writable" if writable else "not writable"})

        matcha_url = self.environment.get("MATCHA_BASE_URL")
        if matcha_url:
            passed, detail = self.check_url("Matcha host", matcha_url)
            checks.append({"name": "Matcha host", "passed": passed, "detail": detail})
            key_passed, key_detail = self.check_secret("MATCHA_API_KEY", required=production)
            checks.append({"name": "Matcha API key", "passed": key_passed, "detail": key_detail})
            user_agent = self.environment.get("MATCHA_USER_AGENT")
            checks.append({
                "name": "Matcha User-Agent",
                "passed": bool(user_agent and user_agent.strip()) or not production,
                "detail": "configured" if user_agent and user_agent.strip() else "missing browser-style User-Agent",
            })

        matchaos_url = self.environment.get("MATCHAOS_BASE_URL")
        if matchaos_url:
            passed, detail = self.check_url("MatchaOS host", matchaos_url)
            checks.append({"name": "MatchaOS host", "passed": passed, "detail": detail})
            key_passed, key_detail = self.check_secret("MATCHAOS_API_KEY", required=production)
            if key_passed:
                key_value = self.environment.get("MATCHAOS_API_KEY")
                file_name = self.environment.get("MATCHAOS_API_KEY_FILE")
                if file_name and Path(file_name).is_file():
                    key_value = Path(file_name).read_text(encoding="utf-8").strip()
                key_passed = bool(key_value and key_value.startswith("mos_sk_live_"))
                key_detail = "MatchaOS key family accepted" if key_passed else "legacy or unrecognized key family"
            checks.append({"name": "MatchaOS API key", "passed": key_passed, "detail": key_detail})

        passed = all(bool(check["passed"]) for check in checks)
        return {
            "role": role,
            "passed": passed,
            "checks": checks,
        }
