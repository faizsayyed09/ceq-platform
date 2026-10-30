from __future__ import annotations

import os
import tempfile
from dataclasses import asdict, is_dataclass
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from modules.config import get_settings
from modules.exceptions import CeqError, ResourceNotFoundError, SecurityError, ValidationError
from modules.logging import configure_logging
from modules.storage import LocalArtifactStore
from modules.validation import validate_safe_filename
from services.genesys_auth import GenesysAuthService
from services.recording import RecordingService
from services.transcription import TranscriptionService
from services.report import ReportService
from services.matching import FingerprintService, TicketMatchingService
from services.knowledge import KnowledgeService
from services.audit import AuditService

settings = get_settings()
configure_logging(settings.log_level)

auth_service = GenesysAuthService(
    region=settings.genesys_region,
    client_id=settings.genesys_client_id,
    client_secret=settings.genesys_client_secret,
    allow_manual_token_testing=settings.allow_manual_token_testing,
)

app = FastAPI(title="CEQ Platform v2", version="2.0.0")


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class GenesysAuthRequest(BaseModel):
    region: str = Field(default="mypurecloud.com")
    manual_token: str | None = Field(default=None)


class GenesysAuthResponse(BaseModel):
    access_token: str = Field(..., description="Bearer token")
    region: str
    source: str


class RecordingDownloadRequest(BaseModel):
    conversation_id: str = Field(..., min_length=36, max_length=36)
    access_token: str = Field(..., min_length=1)
    region: str = Field(default="mypurecloud.com")
    filename: str = Field(default="recording.mp3", max_length=255)


class ReportRequest(BaseModel):
    audit_id: str = Field(..., min_length=36, max_length=36)
    title: str = Field(default="CEQ Audit Report", max_length=200)
    body: object


class TicketMatchRequest(BaseModel):
    transcript: str = Field(..., min_length=1, max_length=500_000)
    tickets: list[dict[str, object]] = Field(default_factory=list, max_length=1000)
    threshold: float = Field(default=0.5, ge=0, le=1)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=10_000)
    articles: list[dict[str, object]] = Field(default_factory=list, max_length=1000)
    limit: int = Field(default=10, ge=1, le=100)


class AuditRequest(BaseModel):
    transcript: str = Field(..., max_length=500_000)
    ticket: dict[str, object] = Field(default_factory=dict)
    knowledge_articles: list[dict[str, object]] = Field(default_factory=list, max_length=1000)
    raw_result: str | dict[str, object] | None = None


@app.exception_handler(CeqError)
async def ceq_error_handler(request: Request, exc: CeqError) -> JSONResponse:
    status = 400
    if isinstance(exc, SecurityError):
        status = 403
    elif isinstance(exc, ResourceNotFoundError):
        status = 404
    elif isinstance(exc, ValidationError):
        status = 422
    return JSONResponse(status_code=status, content={"error": exc.__class__.__name__, "message": str(exc)})


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="healthy", service="ceq-platform", version="2.0.0")


@app.get("/health/live", include_in_schema=False)
async def liveness() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready", include_in_schema=False)
async def readiness() -> dict[str, str]:
    return {"status": "ready"}


@app.post("/auth/genesys", response_model=GenesysAuthResponse)
async def authenticate_genesys(payload: GenesysAuthRequest) -> GenesysAuthResponse:
    result = auth_service.authenticate(region=payload.region, manual_token=payload.manual_token)
    return GenesysAuthResponse(**result)


@app.post("/recording/download")
async def recording_download(payload: RecordingDownloadRequest) -> dict[str, object]:
    region = payload.region.strip().lower()
    auth_service._validate_region(region)
    store = LocalArtifactStore(settings.report_dir)
    service = RecordingService(store, max_file_size_mb=settings.max_file_size_mb)
    recordings = service.fetch_recordings(region, payload.conversation_id, payload.access_token)
    media_uris: list[str] = []
    for recording in recordings:
        for value in (recording.get("mediaUris") or {}).values():
            uri = value.get("mediaUri") if isinstance(value, dict) else None
            if uri:
                media_uris.append(uri)
    if not media_uris:
        raise ResourceNotFoundError("No downloadable Genesys recording media found")
    return await service.download_media(media_uris[0], payload.filename, payload.access_token)


@app.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    protection_mode: str = settings.phi_protection_mode,
    redact_pii: bool | None = None,
) -> dict[str, object]:
    if not audio.filename:
        raise ValidationError("Audio filename is required")
    scratch_dir = Path(tempfile.mkdtemp(prefix="ceq-transcribe-"))
    target = scratch_dir / validate_safe_filename(os.path.basename(audio.filename))
    total = 0
    try:
        with target.open("wb") as output:
            while True:
                chunk = await audio.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.max_file_size_mb * 1024 * 1024:
                    raise ValidationError(f"Audio exceeds {settings.max_file_size_mb} MB limit")
                output.write(chunk)
        service = TranscriptionService(max_audio_duration_seconds=settings.max_audio_duration_seconds, max_file_size_mb=settings.max_file_size_mb)
        return service.transcribe(target, protection_mode=protection_mode, redact=redact_pii)
    except RuntimeError as exc:
        raise CeqError(str(exc)) from exc
    finally:
        for path in target.parent.glob("*"):
            path.unlink(missing_ok=True)
        target.parent.rmdir()


@app.post("/ticket-match")
async def ticket_match(payload: TicketMatchRequest) -> dict[str, object]:
    fingerprint = FingerprintService().fingerprint(payload.transcript)
    matches = TicketMatchingService().match(payload.transcript, payload.tickets, payload.threshold)
    return {"fingerprint": fingerprint, **matches}


@app.post("/kb-search")
async def kb_search(payload: KnowledgeSearchRequest) -> dict[str, object]:
    return KnowledgeService().search(payload.query, payload.articles, payload.limit)


@app.post("/audit")
async def audit(payload: AuditRequest) -> dict[str, object]:
    service = AuditService()
    result = service.build_payload(payload.transcript, payload.ticket, payload.knowledge_articles)
    response = asdict(result) if is_dataclass(result) else dict(result)
    if payload.raw_result is not None:
        response["audit_result"] = service.parse_result(payload.raw_result)
    return response


@app.post("/generate-report")
async def generate_report(payload: ReportRequest) -> dict[str, str]:
    store = LocalArtifactStore(settings.report_dir)
    service = ReportService(store)
    return await service.generate(payload.audit_id, payload.title, payload.body)
