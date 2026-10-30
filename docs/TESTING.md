# Testing Guide

## Test Command

```powershell
pytest -q tests
```

Compile Python sources before review or release:

```powershell
python -m compileall -q api modules services components contracts providers
```

## Test Layout

Tests currently live under `tests/unit/`. The suite covers HTTP routing, services, auth, transcription stages, PHI, validation, artifact storage, dispatching, knowledge, workflow, matching, reports, and audio handling.

The recommended organization remains behavior-oriented:

```text
tests/
├── unit/
├── integration/
├── contract/
└── fixtures/
```

## Test Categories

### Unit Tests

Focused tests validate individual services, contracts, provider adapters, and route behavior without external credentials.

Examples:

```powershell
pytest -q tests/unit/test_api.py
pytest -q tests/unit/test_genesys_auth.py
pytest -q tests/unit/test_transcription_service.py
pytest -q tests/unit/test_artifact_store.py
pytest -q tests/unit/test_dispatcher_service.py
pytest -q tests/unit/test_workflow_service.py
```

### Service Boundary Tests

Add tests at provider/contract boundaries when behavior changes. Mock external HTTP and knowledge/object-store providers rather than using live credentials in normal unit CI.

### Integration Tests

Integration tests should verify:

- FastAPI startup and route contracts
- Docker image startup and health responses
- Compose-mounted source/config behavior
- Recording HTTP status and streaming edge cases
- Provider adapters against controlled services or mocks
- Artifact provider save/read/delete/download/retention behavior
- Workflow attempt and idempotency behavior

### Contract Tests

Contract tests should validate serialization, dataclass outputs, JSON/OpenAPI-compatible payloads, and provider interfaces. They are especially important for artifact, audit, dispatcher, knowledge, workflow, and job models.

## Coverage Gaps

The baseline suite should be expanded for:

- End-to-end FastAPI transcription upload behavior with a mocked Whisper engine
- Recording provider HTTP status, polling timeout, and content-length edge cases
- Readiness dependency checks
- Workflow external-provider failure/retry behavior
- Artifact lifecycle and download-link behavior
- Knowledge provider authentication and result normalization
- PHI projected content with operational identifier preservation
- Secrets/log redaction
- Langflow flow/component compatibility where flows are released
- Docker startup, model-cache, and FFmpeg smoke behavior

## External Dependencies

Tests should not require real Genesys credentials, tokens, audio, ticket exports, knowledge services, Azure storage, or production PHI. Fixtures should be synthetic and non-sensitive.

## Docker Validation

Docker validation is separate from pytest because this environment may not have Docker tooling:

```powershell
docker compose --env-file docker/.env.example -f docker/docker-compose.yml config
docker compose --env-file docker/.env.example -f docker/docker-compose.yml build
docker compose --env-file docker/.env.example -f docker/docker-compose.yml up -d
curl http://127.0.0.1:8000/health
```

Stop the stack after validation:

```powershell
docker compose -f docker/docker-compose.yml down
```

## CI

GitHub CI installs Python requirements, compiles Python sources, runs pytest, and renders Docker Compose configuration. New tests or validation stages should preserve the existing branch triggers and avoid adding live credentials or PHI to the runner.

## Before Creating a PR

- Run the smallest relevant tests first, then the full suite.
- Compile source directories.
- Check the diff for secrets, reports, audio, transcripts, caches, and generated files.
- Verify documentation matches implementation.
- Validate Docker/Compose only when Docker is available.
- List unrun validation explicitly in the PR test plan.
