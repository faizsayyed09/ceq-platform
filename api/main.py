from __future__ import annotations

import os
import tempfile
from dataclasses import asdict, is_dataclass
from pathlib import Path
import hmac

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from modules.config import get_settings
from modules.exceptions import CeqError, ResourceNotFoundError, SecurityError, ValidationError
from modules.logging import configure_logging
from modules.storage import LocalArtifactStore
from modules.validation import validate_safe_filename
from services.genesys_auth import (
    GenesysAuthConfiguration,
    GenesysAuthService,
    TokenOptions,
    normalize_region,
)
from services.recording import RecordingService
from services.transcription import TranscriptionService
from services.report import ReportService
from services.matching import FingerprintService, TicketMatchingService
from services.knowledge import KnowledgeService
from services.audit import AuditService
from services.snow_prematch import SnowPrematchService
from services.mcp_tools import ReadOnlyMcpTools

settings = get_settings()
configure_logging(settings.log_level)

genesys_configuration = GenesysAuthConfiguration.from_environment()
genesys_configuration = GenesysAuthConfiguration(
    region=normalize_region(settings.genesys_region),
    client_id=settings.genesys_client_id,
    client_secret=settings.genesys_client_secret,
    manual_token=genesys_configuration.manual_token if settings.allow_manual_token_testing else None,
    verify_org=genesys_configuration.verify_org,
    timeout_seconds=genesys_configuration.timeout_seconds,
    cache_refresh_margin_seconds=genesys_configuration.cache_refresh_margin_seconds,
)
auth_service = GenesysAuthService(genesys_configuration)

VALID_GENESYS_REGIONS = {
    "mypurecloud.com",
    "mypurecloud.ie",
    "mypurecloud.com.au",
    "mypurecloud.jp",
    "mypurecloud.de",
    "usw2.pure.cloud",
    "cac1.pure.cloud",
    "euw2.pure.cloud",
    "apne2.pure.cloud",
    "apne3.pure.cloud",
    "apse2.pure.cloud",
    "sae1.pure.cloud",
    "mec1.pure.cloud",
}


def validate_genesys_region(region: str) -> str:
    normalized = normalize_region(region)
    if normalized not in VALID_GENESYS_REGIONS:
        raise ValidationError(
            f"Invalid Genesys region. Must be one of: {', '.join(sorted(VALID_GENESYS_REGIONS))}"
        )
    return normalized

app = FastAPI(title="CEQ Platform v2", version="2.0.0")


@app.middleware("http")
async def require_service_authentication(request: Request, call_next):
    public_paths = {
        "/health",
        "/health/live",
        "/health/ready",
        "/docs",
        "/openapi.json",
        "/redoc",
    }
    if request.url.path in public_paths or settings.app_env.lower() not in {"production", "prod"}:
        return await call_next(request)

    if not settings.api_service_token:
        return JSONResponse(
            status_code=503,
            content={"error": "ServiceAuthenticationError", "message": "Service authentication is not configured"},
        )

    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if (
        separator != " "
        or scheme.lower() != "bearer"
        or not hmac.compare_digest(token.strip(), settings.api_service_token)
    ):
        return JSONResponse(
            status_code=401,
            content={"error": "ServiceAuthenticationError", "message": "Invalid service credentials"},
        )

    return await call_next(request)


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


class KnowledgeLookupV2Request(BaseModel):
    ticket: dict[str, object] = Field(default_factory=dict)
    sanitized_description: str = Field(default="", max_length=10_000)
    issue_terms: list[str] = Field(default_factory=list, max_length=100)
    product: str = Field(default="", max_length=500)


class McpToolCallRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    arguments: dict[str, object] = Field(default_factory=dict, max_length=1000)


class McpJsonRpcRequest(BaseModel):
    jsonrpc: str = Field(default="2.0")
    id: object | None = None
    method: str = Field(..., min_length=1, max_length=100)
    params: dict[str, object] = Field(default_factory=dict, max_length=1000)


class AuditRequest(BaseModel):
    transcript: str = Field(..., max_length=500_000)
    ticket: dict[str, object] = Field(default_factory=dict)
    knowledge_articles: list[dict[str, object]] = Field(default_factory=list, max_length=1000)
    raw_result: str | dict[str, object] | None = None


class SnowRefreshRequest(BaseModel):
    file_id: str = Field(default="", max_length=255)
    updated_at: str | None = Field(default=None, max_length=100)
    sha256: str = Field(default="", max_length=64)
    row_count: int = Field(default=0, ge=0)
    export_rows: int = Field(default=0, ge=0)
    coverage_start: str | None = Field(default=None, max_length=100)


class SnowPrematchRequest(BaseModel):
    conversation_id: str = Field(..., min_length=1, max_length=255)
    run_id: str = Field(..., min_length=1, max_length=255)
    transcript: str = Field(..., max_length=500_000)
    tickets: list[dict[str, object]] = Field(default_factory=list, max_length=1000)
    call_start: str | None = Field(default=None, max_length=100)
    call_end: str | None = Field(default=None, max_length=100)
    agent_names: list[str] = Field(default_factory=list, max_length=100)
    agent_emails: list[str] = Field(default_factory=list, max_length=100)
    top_n: int = Field(default=3, ge=1, le=5)


snow_prematch_service = SnowPrematchService()
mcp_tools = ReadOnlyMcpTools()


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
    if settings.app_env.lower() in {"production", "prod"}:
        if not settings.api_service_token:
            return JSONResponse(
                status_code=503,
                content={"status": "not-ready", "reason": "service authentication is not configured"},
            )
        try:
            report_path = Path(settings.report_dir)
            report_path.mkdir(parents=True, exist_ok=True)
            if not os.access(report_path, os.W_OK):
                raise OSError("report directory is not writable")
        except OSError:
            return JSONResponse(
                status_code=503,
                content={"status": "not-ready", "reason": "artifact directory is not writable"},
            )
    return {"status": "ready"}


@app.post("/auth/genesys", response_model=GenesysAuthResponse)
async def authenticate_genesys(payload: GenesysAuthRequest) -> GenesysAuthResponse:
    region = validate_genesys_region(payload.region)
    manual_token = payload.manual_token.strip() if payload.manual_token else None
    if manual_token and not settings.allow_manual_token_testing:
        raise ValidationError("Manual token testing is disabled in this environment.")

    result = auth_service.get_access_token(
        TokenOptions(region=region, manual_token=manual_token)
    )
    return GenesysAuthResponse(**result.to_dict(include_token=True))

@app.post("/recording/download")
async def recording_download(payload: RecordingDownloadRequest) -> dict[str, object]:
    region = validate_genesys_region(payload.region)
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


@app.post("/kb/lookup-v2")
async def kb_lookup_v2(payload: KnowledgeLookupV2Request) -> dict[str, object]:
    return KnowledgeService().lookup_v2(
        payload.ticket,
        sanitized_description=payload.sanitized_description,
        issue_terms=payload.issue_terms,
        product=payload.product,
    )


@app.get("/mcp/tools")
async def mcp_tools_list() -> dict[str, object]:
    return mcp_tools.list_tools()


@app.post("/mcp/tools/call")
async def mcp_tools_call(payload: McpToolCallRequest) -> dict[str, object]:
    return mcp_tools.call(payload.name, payload.arguments)


@app.post("/mcp")
async def mcp_json_rpc(payload: McpJsonRpcRequest) -> dict[str, object]:
    result: dict[str, object]
    if payload.method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ceq-readonly-tools", "version": "1.0.0"},
        }
    elif payload.method in {"tools/list", "tools.list"}:
        result = mcp_tools.list_tools()
    elif payload.method in {"tools/call", "tools.call"}:
        name = str(payload.params.get("name") or "")
        arguments = payload.params.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        result = mcp_tools.call(name, arguments)
    else:
        return {
            "jsonrpc": "2.0",
            "id": payload.id,
            "error": {"code": -32601, "message": "Method not found"},
        }
    return {"jsonrpc": "2.0", "id": payload.id, "result": result}


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


@app.post("/snow/refresh")
async def snow_refresh(payload: SnowRefreshRequest) -> dict[str, object]:
    state = snow_prematch_service.refresh(payload.model_dump())
    return snow_prematch_service.status()


@app.get("/snow/status")
async def snow_status() -> dict[str, object]:
    return snow_prematch_service.status()


@app.post("/snow/prematch")
async def snow_prematch(payload: SnowPrematchRequest) -> dict[str, object]:
    return snow_prematch_service.prematch(
        conversation_id=payload.conversation_id,
        run_id=payload.run_id,
        transcript=payload.transcript,
        tickets=payload.tickets,
        call_start=payload.call_start,
        call_end=payload.call_end,
        agent_names=tuple(payload.agent_names),
        agent_emails=tuple(payload.agent_emails),
        top_n=payload.top_n,
        prematch_mode=settings.prematch_mode,
    )
