# CEQ Services

## Auth Service

**Implementation:** `services/genesys_auth.py`  
**Responsibilities:** Validate Genesys regions, obtain OAuth credentials, cache bounded tokens, gate manual bearer-token testing, and sanitize auth failures.  
**Inputs:** Region, optional client credentials, optional manual token.  
**Outputs:** Access-token result and source/region metadata.  
**Dependencies:** Genesys OAuth API, environment/secret configuration.  
**Status:** Implemented and unit-tested; production Key Vault/managed identity integration should be validated.

## Recording Service

**Implementation:** `services/recording.py`  
**Responsibilities:** Validate conversation IDs and tokens, poll Genesys recordings, select/download media by HTTPS URI, enforce size limits, and persist through artifact storage.  
**Inputs:** Conversation UUID, region, access token, filename, size limit.  
**Outputs:** Filename, byte count, and artifact location.  
**Dependencies:** Genesys APIs, artifact provider, Requests.  
**Status:** Implemented with focused tests; external durable object storage remains deployment-specific.

## Transcription Service

**Implementation:** `services/transcription.py` and transcriber v2 modules  
**Responsibilities:** Validate audio path/size/format/duration, load the pinned Whisper runtime, produce canonical text and timestamped segments, detect silence, and apply PHI policy.  
**Inputs:** Audio file and `OFF`, `AUDIT_MODE`, `LLM_MODE`, or `STRICT` protection mode.  
**Outputs:** Transcript text, segments, metrics, silence data, and PHI projection/findings.  
**Dependencies:** FFprobe/FFmpeg, faster-whisper, Av/CTranslate2 stack, model cache, artifact/input filesystem.  
**Status:** Implemented with decomposition and focused unit coverage; production model/cache and scale configuration require validation.

## Ticket Matching Service

**Implementation:** `services/matching.py` and `services/ticket_matching_service.py`  
**Responsibilities:** Fingerprint transcripts and match them against supplied/exported ticket data while preserving existing status/confidence logic.  
**Inputs:** Transcript, tickets/export rows, thresholds, and interaction/ticket identifiers.  
**Outputs:** Fingerprint, matched/ambiguous/not-found status, confidence, candidates, and facts.  
**Dependencies:** Standard library matching/parsing implementation; optional ticket export provider integration.  
**Status:** Implemented and unit-tested. Existing scoring logic is retained.

## Knowledge Service

**Implementation:** `services/knowledge.py`; providers in `providers/knowledge.py`  
**Responsibilities:** Search supplied articles or provider-backed knowledge, rank/calculate confidence, return citations, and apply KB policy.  
**Inputs:** Knowledge query, issue context, article/provider data, result limit.  
**Outputs:** Ranked articles, confidence, citations, policy evaluation, and KB-gap indication.  
**Dependencies:** Supplied data, Matcha, ServiceNow, or Azure AI Search providers when configured.  
**Status:** Implemented with provider-neutral contracts and unit coverage; provider credentials and network integration need environment validation.

## Audit Service

**Implementation:** `services/audit.py`  
**Responsibilities:** Build canonical audit payloads and parse structured/raw audit results into typed evidence.  
**Inputs:** Transcript, ticket context, knowledge articles, and optional raw result.  
**Outputs:** Audit payload and parsed audit result.  
**Dependencies:** Contracts and validation modules.  
**Status:** Implemented and unit-tested. External LLM/provider execution remains adapter/workflow-specific.

## Audit Workflow Service

**Implementation:** `services/audit_workflow.py`  
**Responsibilities:** Coordinate auth, recording, transcription, fingerprinting, ticket matching, knowledge, audit, report, and artifacts as one audit run with retries/idempotency.  
**Inputs:** Typed audit run request.  
**Outputs:** Typed run state/result and service evidence.  
**Dependencies:** All core services, contracts, artifact providers.  
**Status:** Implemented with unit coverage; production queue/persistence integration is pending.

## Dispatcher Service

**Implementation:** `services/dispatcher.py`  
**Responsibilities:** Normalize roster data, dispatch calls/emails, apply daily limits/exclusions/grace windows, retry states, reconcile jobs, and create queue delivery records.  
**Inputs:** Roster, conversation records, dispatcher state/configuration.  
**Outputs:** Audit jobs, queue messages, reconciliation results, and state.  
**Dependencies:** Genesys conversation provider when configured, typed contracts, clock/state abstractions.  
**Status:** Implemented as service with unit coverage; external queue/state provider deployment remains partial.

## Artifact Store

**Implementation:** `services/artifact_store.py`; providers in `providers/artifact.py`  
**Responsibilities:** Generate safe keys, save/read/delete/list artifacts, create download links, and apply retention policies.  
**Inputs:** Artifact type, owner, filename/id, bytes/data stream, retention policy.  
**Outputs:** Typed artifact metadata and operations.  
**Dependencies:** Local filesystem, Azure Blob, or S3-compatible provider implementation.  
**Status:** Implemented with providers and tests; production identity, lifecycle, network, and persistence configuration need validation.

## Report Service

**Implementation:** `services/report.py`  
**Responsibilities:** Generate escaped HTML reports and persist them through an artifact store interface.  
**Inputs:** Audit UUID, title, report body, artifact store.  
**Outputs:** Report filename/location and metadata adapted by callers.  
**Dependencies:** HTML escaping, local/provider artifact storage.  
**Status:** Implemented; production templates/object lifecycle are deployment-specific.

## PHI Protection Service

**Implementation:** `services/phi_protection.py`  
**Responsibilities:** Apply destination-specific PHI policies while preserving operational audit identifiers in canonical evidence.  
**Inputs:** Text and protection mode.  
**Outputs:** Canonical/projection text and PHI findings.  
**Dependencies:** Service/transcription callers.  
**Status:** Implemented with unit coverage. Provider-specific/legal controls require operational policy review.

## Langflow and Workflow Adapters

**Implementation:** `components/`, `flows/`  
**Responsibilities:** Provide desktop/server component adapters and retain flow exports for compatibility and recovery.  
**Inputs/Outputs:** Component-specific Langflow messages and service calls.  
**Dependencies:** Langflow/LFX runtime plus Python service modules.  
**Status:** Preserved and not moved or removed in the cleanup. Runtime parity should be tested before legacy assets are retired.

## API Error Contract

Application errors use structured JSON responses:

```json
{"error":"ValidationError","message":"Human-readable safe message"}
```

Status mappings include validation, security, resource-not-found, and general CEQ errors. Messages must avoid credentials, tokens, secrets, and unnecessary PHI.
