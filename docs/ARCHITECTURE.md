# CEQ Platform Architecture

CEQ v3 is the authority for maintained architecture. `docs/ceq-v3/00_INDEX.md` lists D1-D12 decisions; this document summarizes the implemented repository boundary.

## Runtime architecture

```text
Maintained HTTP/API clients and compatibility adapters
            |
            v
FastAPI api/main.py
            |
            v
Runtime-neutral services (services/, modules/, contracts/)
            |
      +-----+-----+-------------------------+
      |           |                         |
      v           v                         v
Genesys/auth  Recording/transcription  Ticket/knowledge/audit
      |           |                         |
      v           v                         v
External providers             Local/provider-neutral artifact storage
      |
      v
Reports, records, workflow state, audit evidence
```

## Source-of-Truth Boundaries

- `api/main.py`: HTTP route and request/response adapters.
- `services/`: runtime-neutral implementation and orchestration services.
- `modules/`: configuration, exceptions, logging, validation, PHI, storage, and constants.
- `contracts/`: typed service inputs, outputs, and state models.
- `providers/`: knowledge and artifact provider integrations.
- `components/`: Langflow custom-component adapters. These remain for compatibility and are not replaced by this documentation.
- `flows/`: preserved Langflow JSON exports for disaster recovery and historical use.
- `docker/`: FastAPI/Langflow local container runtime.
- `infra/`: Azure Container Apps and supporting Bicep deployment definitions.

## Core Services

### Auth and Provider Access

`GenesysAuthService` validates supported regions, obtains tokens, and bounds manual-token access. Provider credentials must come from environment variables, secret stores, or managed identity integration rather than source code.

### Recording

`RecordingService` validates conversation identifiers, polls Genesys recording APIs, bounds downloads by size, streams media, and writes through an artifact abstraction.

### Transcription

`TranscriptionService` validates audio, ffprobe metadata, duration, and size, then uses the configured Whisper runtime to produce canonical text, timestamped segments, and metrics. PHI policy is applied explicitly and separately from operational identifiers.

### Matching and Knowledge

`FingerprintService`, `TicketMatchingService`, and `KnowledgeService` use transcripts, ticket context, and knowledge providers to identify matches, confidence, citations, and policy outcomes without changing CEQ scoring logic.

### Audit and Workflow

`AuditService` and `AuditWorkflowService` assemble payloads, parse audit results, coordinate service evidence, enforce attempt limits, and return typed workflow outcomes.

### Dispatcher

`DispatcherService` normalizes roster and conversation data, applies channels, limits, exclusions, timing, retries, reconciliation, and queue delivery contracts.

### Artifacts and Reports

`ArtifactStoreService` provides a provider-neutral artifact contract. `LocalArtifactProvider` supports development; Azure Blob and S3-compatible providers are implementation adapters that require deployment-specific configuration and validation. `ReportService` produces report artifacts through the service boundary.

## HTTP API

| Route | Purpose |
|---|---|
| `GET /health` | General health response |
| `GET /health/live` | Liveness probe |
| `GET /health/ready` | Readiness response |
| `POST /auth/genesys` | Obtain a Genesys access token |
| `POST /recording/download` | Locate and download Genesys recording media |
| `POST /transcribe` | Upload audio and return transcription output |
| `POST /ticket-match` | Match transcript evidence against tickets |
| `POST /kb-search` | Search supplied articles or a configured knowledge provider |
| `POST /audit` | Build an audit payload and optionally parse a result |
| `POST /generate-report` | Generate a report artifact |

Application errors are returned through a JSON error contract containing `error` and `message`, with validation/security/not-found mappings appropriate to the route.

## Data and Security Boundaries

- Audio, transcripts, tickets, and reports may contain sensitive or PHI data.
- Canonical audit evidence must remain distinguishable from provider-safe projections.
- Secrets and credentials must never be committed or logged.
- Local filesystem storage is not suitable as durable production state.
- External providers, object stores, queues, and managed secrets require explicit authentication and authorization boundaries.

## Deployment Model

```text
Client/Langflow
      |
FastAPI container or Langflow container
      |
Service/provider abstractions
      |
Genesys | Ticket/Knowledge APIs | Artifact storage | optional queue/state providers
```

For local use, Docker Compose runs the FastAPI image with host/Compose mounts and named model caches. For Azure, the maintained Bicep path provisions infrastructure; the former manual deployment script is archived. Production replicas require external state, artifact storage, and provider configuration.

## Legacy Isolation Note

Existing `components/` and `flows/` assets remain in place. This architecture documents them as compatibility/runtime assets and explicitly does not describe them as deleted, moved, or deprecated by the cleanup pass.
