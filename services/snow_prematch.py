from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from modules.exceptions import ValidationError
from services.fingerprint_service import FingerprintService
from services.phi_protection import PhiProtectionService
from services.ticket_matching_service import (
    PENDING_EXPORT,
    TicketExportResult,
    TicketMatchingService,
    TicketRow,
)
from services.phi_protection import PHI_POLICY_VERSION


@dataclass(frozen=True)
class SnowRefreshState:
    file_id: str = ""
    updated_at: str = ""
    sha256: str = ""
    row_count: int = 0
    export_rows: int = 0
    coverage_start: str = ""
    received_at: str = ""


class SnowPrematchService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._refresh = SnowRefreshState()
        self._idempotent: dict[tuple[str, str], dict[str, object]] = {}

    def refresh(self, payload: Mapping[str, Any]) -> SnowRefreshState:
        file_id = str(payload.get("file_id") or "").strip()
        updated_at = str(payload.get("updated_at") or "").strip()
        sha256 = str(payload.get("sha256") or "").strip().lower()
        row_count = self._integer(payload.get("row_count"), "row_count", minimum=0)
        export_rows = self._integer(payload.get("export_rows"), "export_rows", minimum=0)
        coverage_start = str(payload.get("coverage_start") or "").strip()
        if sha256 and len(sha256) != 64:
            raise ValidationError("sha256 must contain exactly 64 hexadecimal characters")
        if sha256 and any(char not in "0123456789abcdef" for char in sha256):
            raise ValidationError("sha256 must contain exactly 64 hexadecimal characters")
        state = SnowRefreshState(
            file_id=file_id,
            updated_at=updated_at,
            sha256=sha256,
            row_count=row_count,
            export_rows=export_rows,
            coverage_start=coverage_start,
            received_at=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            self._refresh = state
        return state

    def status(self) -> dict[str, object]:
        with self._lock:
            state = self._refresh
        return {
            "refresh_state": "ready" if state.received_at else "empty",
            "file_id": state.file_id,
            "updated_at": state.updated_at,
            "sha256": state.sha256,
            "row_count": state.row_count,
            "export_rows": state.export_rows,
            "coverage_start": state.coverage_start,
            "received_at": state.received_at,
        }

    def prematch(
        self,
        *,
        conversation_id: str,
        run_id: str,
        transcript: str,
        tickets: list[dict[str, Any]],
        call_start: datetime | str | None = None,
        call_end: datetime | str | None = None,
        agent_names: tuple[str, ...] = (),
        agent_emails: tuple[str, ...] = (),
        top_n: int = 3,
        prematch_mode: str = "shadow",
    ) -> dict[str, object]:
        conversation_id = conversation_id.strip()
        run_id = run_id.strip()
        if not conversation_id or not run_id:
            raise ValidationError("conversation_id and run_id are required")
        if not 1 <= top_n <= 5:
            raise ValidationError("top_n must be between 1 and 5")
        key = (conversation_id, run_id)
        with self._lock:
            cached = self._idempotent.get(key)
        if cached is not None:
            return dict(cached)

        fingerprint = FingerprintService().fingerprint(
            transcript,
            channel="CALL",
            call_start=call_start,
            call_end=call_end or call_start,
            agent_names=agent_names,
            agent_emails=agent_emails,
        )
        export = TicketExportResult(
            rows=tuple(TicketRow(ticket) for ticket in tickets),
            uploaded_at=self._parse_datetime(self.status().get("updated_at")),
            newest_activity_at=self._parse_datetime(self.status().get("updated_at")),
        )
        result = TicketMatchingService().match(fingerprint, export, top_candidates=top_n)
        candidates = tuple(self._project_candidate(candidate) for candidate in result.candidates)
        response = {
            "snow_status": result.status,
            "exported_at": self.status().get("updated_at") or None,
            "export_rows": result.export_rows,
            "coverage_start": self.status().get("coverage_start") or None,
            "candidates": list(candidates),
            "prematch_engine_version": "azure-prematch-v1",
            "phi_policy_version": PHI_POLICY_VERSION,
            "cache_state": "disabled" if not self.status().get("sha256") else "metadata-only",
            "prematch_mode": prematch_mode if prematch_mode in {"matcha", "shadow", "azure"} else "shadow",
            "best_ticket": result.best_ticket,
            "confidence": result.confidence,
        }
        response["_idempotency_key"] = hashlib.sha256(
            (conversation_id + ":" + run_id).encode("utf-8")
        ).hexdigest()
        with self._lock:
            self._idempotent[key] = response
        return dict(response)

    def _project_candidate(self, candidate: Any) -> dict[str, object]:
        row = dict(candidate.row.values)
        allowed = ("Number", "Opened", "Updated", "State", "Company", "KA number", "Short description", "Description")
        projected: dict[str, object] = {}
        phi_flags: dict[str, object] = {"types": [], "counts": {}, "client_visible": False}
        for key in allowed:
            if key not in row:
                continue
            value = str(row[key] or "")
            if key in {"Short description", "Description"}:
                result = PhiProtectionService("LLM_MODE").project_role_aware(
                    value,
                    source_field=key,
                    source_track="",
                    client_visible=key == "Description",
                    mode="LLM_MODE",
                )
                projected[key] = result["text"]
                types = list(result.get("phi_categories", []))
                if types:
                    phi_flags["types"] = sorted(set(list(phi_flags["types"]) + types))
                    phi_flags["counts"][key] = len(result.get("findings", []))
            else:
                projected[key] = value
        return {
            "Number": projected.get("Number", candidate.number),
            "score": candidate.score,
            "reasons": list(candidate.reasons),
            "row": projected,
            "phi_flags": phi_flags,
        }

    @staticmethod
    def _integer(value: Any, field: str, minimum: int) -> int:
        if value is None:
            return 0
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValidationError(f"{field} must be a non-negative integer")
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{field} must be a non-negative integer") from exc
        if result < minimum:
            raise ValidationError(f"{field} must be a non-negative integer")
        return result

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
