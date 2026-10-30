from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from contracts.artifact import ArtifactMetadata, ArtifactType, RetentionPolicy
from contracts.audit import AuditVerdict
from contracts.audit_payload import AuditRequest, AuditPayload
from contracts.knowledge import KnowledgeArticle, KnowledgeQuery, KnowledgeSearchResult
from contracts.workflow import (
    AuditRunRequest,
    AuditRunResult,
    AuditWorkflowState,
    ServiceEvidenceBundle,
    WorkflowError,
)
from modules.exceptions import CeqError, ValidationError
from modules.validation import validate_uuid
from providers.artifact import ArtifactProvider
from services.artifact_store import ArtifactStoreService
from services.audit import AuditService
from services.genesys_auth import GenesysAuthService
from services.knowledge import KnowledgeService
from services.matching import FingerprintService, TicketMatchingService
from services.recording import RecordingService
from services.report import ReportService
from services.transcription import TranscriptionService

logger = logging.getLogger(__name__)


class _ReportArtifactAdapter:
    """Adapts ReportService's filename contract to ArtifactStoreService."""

    def __init__(self, store: ArtifactStoreService, audit_id: str) -> None:
        self.store = store
        self.audit_id = audit_id
        self.last_metadata: ArtifactMetadata | None = None

    async def save(self, filename: str, data: bytes, *, content_type: str = "application/octet-stream") -> str:
        metadata = await self.store.save(
            ArtifactType.REPORT,
            self.audit_id,
            filename,
            data,
            content_type=content_type,
        )
        self.last_metadata = metadata
        return metadata.key.as_posix()

    async def read(self, filename: str) -> bytes:
        key = self.store.generate_key(ArtifactType.REPORT, self.audit_id, filename)
        return await self.store.read(key)

    async def delete(self, filename: str) -> bool:
        key = self.store.generate_key(ArtifactType.REPORT, self.audit_id, filename)
        return await self.store.delete(key)


class AuditWorkflowService:
    """Canonical CEQ call-audit workflow built only from existing services."""

    def __init__(
        self,
        auth_service: GenesysAuthService | None = None,
        recording_service: RecordingService | None = None,
        transcription_service: TranscriptionService | None = None,
        fingerprint_service: FingerprintService | None = None,
        ticket_service: TicketMatchingService | None = None,
        knowledge_service: KnowledgeService | None = None,
        audit_service: AuditService | None = None,
        report_service: ReportService | None = None,
        artifact_store: ArtifactStoreService | None = None,
        artifact_provider: ArtifactProvider | None = None,
        artifact_root: str | os.PathLike[str] = "./artifacts",
        max_attempts: int = 3,
    ) -> None:
        self.auth = auth_service or GenesysAuthService()
        self.recording = recording_service
        self.transcription = transcription_service or TranscriptionService()
        self.fingerprint = fingerprint_service or FingerprintService()
        self.ticket_matching = ticket_service or TicketMatchingService()
        self.knowledge = knowledge_service or KnowledgeService()
        self.audit = audit_service or AuditService(pass_threshold=96.0)
        self.report_service = report_service
        self.artifacts = artifact_store or ArtifactStoreService(provider=artifact_provider, storage_root=artifact_root)
        self.max_attempts = max(1, int(max_attempts))
        self._runs: dict[str, AuditRunResult] = {}
        self._attempts: dict[str, int] = {}

    async def execute(self, request: AuditRunRequest | Mapping[str, Any]) -> AuditRunResult:
        normalized = self._normalize_request(request)
        run_id = normalized.idempotency_key or self._idempotency_key(normalized)
        completed = self._runs.get(run_id)
        if completed is not None and completed.status == AuditWorkflowState.COMPLETED:
            return completed

        initial = AuditRunResult(
            run_id=run_id,
            conversation_id=normalized.conversation_id,
            audit_id=normalized.audit_id,
            status=AuditWorkflowState.RUNNING,
            evidence=ServiceEvidenceBundle(),
        )
        self._attempts[run_id] = self._attempts.get(run_id, 0) + 1
        self._runs[run_id] = initial

        scratch_path: Path | None = None
        try:
            # Authentication is explicit, even when the recording service owns token refresh/cache.
            self.auth.authenticate(region=normalized.region)

            recording = self.recording or RecordingService(auth_service=self.auth, region=normalized.region)
            recording_info = recording.download_recording(normalized.conversation_id)
            recording_path = self._recording_path(recording_info, scratch_path)
            if recording_path is None:
                raise WorkflowError("Recording download did not provide a readable audio path")
            if recording_info.get("data") or recording_info.get("bytes"):
                scratch_path = recording_path

            with recording_path.open("rb") as recording_stream:
                recording_metadata = await self.artifacts.save(
                    ArtifactType.RECORDING,
                    normalized.conversation_id,
                    str(recording_info.get("filename") or recording_path.name),
                    recording_stream,
                    artifact_id=self._artifact_id(normalized.conversation_id, "recording"),
                    content_type=self._content_type(recording_path.suffix),
                )

            metadata = recording.get_recording_metadata(normalized.conversation_id) if hasattr(recording, "get_recording_metadata") else {}
            transcription = self.transcription.transcribe(
                recording_path,
                protection_mode=normalized.protection_mode,
            )
            transcript_text = str(transcription.get("transcript") or transcription.get("text") or "")
            if not transcript_text.strip():
                raise WorkflowError("Transcription produced empty text")

            transcript_metadata = await self.artifacts.save(
                ArtifactType.TRANSCRIPT,
                normalized.conversation_id,
                f"{normalized.conversation_id}_transcript.txt",
                transcript_text.encode("utf-8"),
                artifact_id=self._artifact_id(normalized.conversation_id, "transcript"),
                content_type="text/plain; charset=utf-8",
            )

            fingerprint = self.fingerprint.fingerprint(transcript_text)
            ticket_match = self.ticket_matching.match(transcript_text, [dict(ticket) for ticket in normalized.tickets], normalized.threshold)
            ticket = self._ticket_context(ticket_match)

            kb_policy, kb_mapping = self._knowledge_context(normalized, transcript_text, ticket)

            audit_request = AuditRequest(
                interaction_text=transcript_text,
                ticket=ticket,
                kb=kb_mapping,
                prematch={"tickets_mentioned": [], "caller_requested_pauses": []},
                call_data={"transcription": transcription, "recording": dict(metadata)},
                ceq_response=normalized.ceq_response,
                pass_threshold=96.0,
            )
            audit_payload = self.audit.build_payload(audit_request)
            if isinstance(audit_payload, Mapping):
                audit_payload_obj = None
            else:
                audit_payload_obj = audit_payload
            audit_result = self.audit.execute_audit(audit_request)

            report_adapter = _ReportArtifactAdapter(self.artifacts, normalized.audit_id)
            report_service = self.report_service or ReportService(report_adapter)
            report_result = await report_service.generate(
                normalized.audit_id,
                normalized.report_title,
                {
                    "workflow_run_id": run_id,
                    "conversation_id": normalized.conversation_id,
                    "audit_result": audit_result.to_dict() if hasattr(audit_result, "to_dict") else dict(audit_result),
                    "evidence": audit_payload_obj.to_dict() if hasattr(audit_payload_obj, "to_dict") else {},
                },
            )

            evidence = ServiceEvidenceBundle(
                recording_metadata=dict(metadata),
                recording_artifact=recording_metadata,
                transcript_artifact=transcript_metadata,
                transcription={
                    "metrics": transcription.get("metrics", {}),
                    "hold_events": transcription.get("hold_events", []),
                    "phi_protection": transcription.get("phi_protection", {}),
                },
                fingerprint=fingerprint,
                ticket_match=ticket_match,
                knowledge=kb_policy,
                audit_payload=audit_payload_obj,
                audit_result=audit_result,
                report_artifact=report_adapter.last_metadata,
            )
            result = AuditRunResult(
                run_id=run_id,
                conversation_id=normalized.conversation_id,
                audit_id=normalized.audit_id,
                status=AuditWorkflowState.COMPLETED,
                evidence=evidence,
                verdict=audit_result.verdict if hasattr(audit_result, "verdict") else None,
                report_location=str(report_result.get("location") or ""),
            )
            self._runs[run_id] = result
            logger.info("Audit workflow completed run_id=%s conversation=%s verdict=%s", run_id, normalized.conversation_id, result.verdict)
            return result
        except WorkflowError as exc:
            return self._workflow_error_result(initial, str(exc))
        except CeqError as exc:
            return self._workflow_error_result(initial, str(exc))
        except Exception as exc:
            logger.exception("Audit workflow failed run_id=%s conversation=%s", run_id, normalized.conversation_id)
            return self._workflow_error_result(initial, str(exc) or exc.__class__.__name__)
        finally:
            if scratch_path is not None:
                try:
                    scratch_path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Temporary workflow recording cleanup failed")

    def _failed_result(self, initial: AuditRunResult, error: str) -> AuditRunResult:
        result = initial.with_status(AuditWorkflowState.FAILED, error=error)
        self._runs[result.run_id] = result
        return result

    def _workflow_error_result(self, initial: AuditRunResult, error: str) -> AuditRunResult:
        attempt = self._attempts.get(initial.run_id, 1)
        status = AuditWorkflowState.RETRY_SCHEDULED if attempt < self.max_attempts else AuditWorkflowState.FAILED
        result = initial.with_status(status, error=error)
        self._runs[result.run_id] = result
        return result

    def _normalize_request(self, request: AuditRunRequest | Mapping[str, Any]) -> AuditRunRequest:
        if isinstance(request, Mapping):
            request = AuditRunRequest(
                conversation_id=str(request.get("conversation_id") or ""),
                audit_id=str(request.get("audit_id") or ""),
                region=str(request.get("region") or "mypurecloud.com"),
                protection_mode=str(request.get("protection_mode") or "AUDIT_MODE"),
                threshold=float(request.get("threshold", 0.5)),
                tickets=tuple(dict(row) for row in request.get("tickets") or () if isinstance(row, Mapping)),
                articles=tuple(dict(row) for row in request.get("articles") or () if isinstance(row, Mapping)),
                knowledge_query=str(request.get("knowledge_query") or ""),
                ceq_response=request.get("ceq_response", ""),
                report_title=str(request.get("report_title") or "CEQ Audit Report"),
                retention_days=request.get("retention_days"),
                idempotency_key=str(request.get("idempotency_key") or ""),
            )
        if not isinstance(request, AuditRunRequest):
            raise WorkflowError("Invalid audit workflow request")
        conversation_id = validate_uuid(str(request.conversation_id), "conversation_id")
        audit_id = validate_uuid(str(request.audit_id or conversation_id), "audit_id")
        if request.threshold < 0 or request.threshold > 1:
            raise WorkflowError("Ticket matching threshold must be between 0 and 1")
        if request.retention_days is not None and request.retention_days < 1:
            raise WorkflowError("Retention days must be positive")
        return AuditRunRequest(
            conversation_id=conversation_id,
            audit_id=audit_id,
            region=request.region,
            protection_mode=request.protection_mode,
            threshold=request.threshold,
            tickets=request.tickets,
            articles=request.articles,
            knowledge_query=request.knowledge_query,
            ceq_response=request.ceq_response,
            report_title=request.report_title,
            retention_days=request.retention_days,
            idempotency_key=request.idempotency_key,
        )

    def _idempotency_key(self, request: AuditRunRequest) -> str:
        identity = "|".join((request.conversation_id.lower(), request.audit_id.lower(), request.region.lower())).encode("utf-8")
        return hashlib.sha256(identity).hexdigest()

    def _artifact_id(self, owner_id: str, kind: str) -> str:
        return hashlib.sha256(f"{kind}|{owner_id}".encode("utf-8")).hexdigest()[:32]

    def _recording_path(self, recording_info: Mapping[str, Any], scratch_path: Path | None) -> Path | None:
        value = recording_info.get("file_path") or recording_info.get("path")
        if value:
            path = Path(str(value))
            if path.is_file() and not path.is_symlink():
                return path
        data = recording_info.get("data") or recording_info.get("bytes")
        if data:
            directory = Path(tempfile.mkdtemp(prefix="ceq-workflow-"))
            path = directory / str(recording_info.get("filename") or "recording.wav")
            path.write_bytes(bytes(data))
            return path
        if scratch_path is not None and scratch_path.is_file():
            return scratch_path
        return None

    def _content_type(self, suffix: str) -> str:
        return {
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".ogg": "audio/ogg",
            ".webm": "audio/webm",
        }.get(suffix.lower(), "audio/octet-stream")

    def _ticket_context(self, ticket_match: Mapping[str, Any]) -> dict[str, Any]:
        matches = ticket_match.get("matches") if isinstance(ticket_match.get("matches"), list) else []
        if matches:
            best = dict(matches[0])
            return {
                "matched_ticket": best.get("ticket_id") or best.get("number") or "",
                "match_confidence": best.get("score", 0.0),
                "prematch_status": "MATCHED",
                "verification": {"prematch_status": "MATCHED", "facts": {}},
                "matches": matches,
            }
        return {
            "matched_ticket": "",
            "match_confidence": 0.0,
            "prematch_status": "NOT_FOUND",
            "verification": {"prematch_status": "NOT_FOUND", "facts": {}},
            "matches": [],
        }

    def _knowledge_context(self, request: AuditRunRequest, transcript_text: str, ticket: Mapping[str, Any]):
        if self.knowledge.provider is not None and request.knowledge_query:
            result = self.knowledge.search_provider(
                KnowledgeQuery(issue_summary=request.knowledge_query),
                limit=10,
            )
            policy = self.knowledge.evaluate_policy(result, self._cited_article_ids(ticket))
        else:
            articles = tuple(
                KnowledgeArticle(
                    article_id=str(row.get("article_id") or row.get("id") or ""),
                    title=str(row.get("title") or ""),
                    body=str(row.get("body") or row.get("text") or row.get("content") or ""),
                    url=str(row.get("url") or ""),
                    provider=str(row.get("provider") or ""),
                )
                for row in request.articles
            )
            if request.knowledge_query:
                articles = tuple(article for article in articles if self._article_matches_query(article, request.knowledge_query))
            confidence = self.knowledge.calculate_confidence(
                KnowledgeQuery(issue_summary=request.knowledge_query or transcript_text[:10000]),
                articles,
            )
            result = KnowledgeSearchResult(
                articles=articles,
                confidence=confidence,
                kb_gap=not articles,
                kb_gap_note="No applicable knowledge articles were found" if not articles else "",
                provider="workflow",
            )
            policy = self.knowledge.evaluate_policy(result, self._cited_article_ids(ticket))

        mapping = {
            "confidence": policy.confidence.value,
            "enforceable": policy.enforceable,
            "advisory_only": policy.advisory_only,
            "kb_gap": policy.kb_gap,
            "kb_gap_note": policy.kb_gap_note,
            "enforceable_reason": policy.enforceable_reason,
            "articles": [article.__dict__ for article in policy.articles],
            "citations": [citation.__dict__ for citation in policy.citations],
        }
        return policy, mapping

    def _article_matches_query(self, article: KnowledgeArticle, query: str) -> bool:
        terms = [term.lower() for term in query.split() if len(term) >= 3]
        text = (article.title + " " + article.body).lower()
        return bool(terms) and any(term in text for term in terms)

    def _cited_article_ids(self, ticket: Mapping[str, Any]) -> tuple[str, ...]:
        verification = ticket.get("verification") if isinstance(ticket.get("verification"), Mapping) else {}
        ids = verification.get("kb_articles_in_ticket") or ticket.get("kb_articles_in_ticket") or ()
        if isinstance(ids, str):
            return (ids,) if ids.strip() else ()
        return tuple(str(item) for item in ids if str(item).strip())
