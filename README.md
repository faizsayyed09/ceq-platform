# CEQ Platform v2

CEQ Platform is an AI-assisted quality and compliance platform for Service Desk call audits. It combines Genesys recordings, ticket/knowledge context, transcription, audit workflows, reporting, dispatching, and provider-neutral artifact storage.

This repository contains the modernization implementation on `transcriber-rewrite` plus preserved Langflow compatibility components and flow exports. The documentation refresh does not change service behavior or replace legacy assets.

## Project Purpose

The platform supports:

- Genesys Cloud authentication and recording retrieval
- Audio validation and Whisper transcription
- PHI-aware transcript handling without changing operational audit evidence
- Ticket fingerprinting and matching
- Knowledge search and policy/citation evaluation
- Audit payload/result processing and workflow orchestration
- Dispatcher roster, cap, retry, reconciliation, and queue contracts
- Report and artifact generation
- FastAPI HTTP access and Langflow component compatibility

## Architecture

```text
Langflow or API client
          |
          v
FastAPI routes / Langflow component adapters
          |
          v
Services + contracts + modules
          |
          +--> Genesys auth/recordings
          +--> Transcription/PHI
          +--> Ticket and knowledge matching
          +--> Audit and dispatcher workflows
          +--> Reports and artifacts
          |
          v
Genesys, knowledge/ticket providers, and artifact providers
```

For detailed boundaries, routes, and service responsibilities, see:

- [Architecture](docs/ARCHITECTURE.md)
- [Services](docs/SERVICES.md)
- [Security](docs/SECURITY.md)
- [Current Status](STATUS.md)

## Repository Layout

```text
api/          FastAPI application and routes
services/     Runtime-neutral services and workflow implementation
contracts/    Typed service inputs, outputs, jobs, and state
modules/      Configuration, logging, validation, storage, PHI, exceptions
providers/    Knowledge and artifact provider implementations
components/   Preserved Langflow custom components
flows/        Preserved disaster-recovery/exported flow JSON
prompts/      Prompt assets or placeholders
docker/       Dockerfile and local Compose runtime
scripts/      Azure and deployment automation
tests/        Unit and service/API regression tests
docs/         Canonical architecture and operations documentation
```

## Quick Start

### Prerequisites

- Windows PowerShell
- Python 3.12
- Optional FFmpeg for local transcription
- Optional Docker Desktop for Compose

### Local Python Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env.local
pytest -q tests
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

The API is available at:

- Health: `http://127.0.0.1:8000/health`
- Liveness: `http://127.0.0.1:8000/health/live`
- Readiness: `http://127.0.0.1:8000/health/ready`
- OpenAPI: `http://127.0.0.1:8000/docs`

Do not commit `.env.local` or any populated credential/audio/transcript/report file.

## Development Workflow

Use `services/`, `modules/`, and `contracts/` for reusable implementation. Keep `api/main.py` and Langflow components as thin adapters. Preserve existing flow exports and legacy components unless a separate approved migration changes them.

```powershell
git switch transcriber-rewrite
git pull --ff-only origin transcriber-rewrite
git switch -c feature/<topic>
pytest -q tests
python -m compileall -q api modules services components contracts providers
```

See [Development Guide](docs/DEVELOPMENT.md) for setup, source ownership, Langflow, Docker, and Git conventions.

## Testing

```powershell
pytest -q tests
python -m compileall -q api modules services components contracts providers
```

Tests cover API routes, Genesys auth, recordings, transcription stages, PHI modes, matching, knowledge, audit/workflow, dispatcher, artifact storage, reports, and validation. Use synthetic fixtures only; never place live credentials or PHI in tests.

See [Testing Guide](docs/TESTING.md).

## Docker Usage

```powershell
Copy-Item docker/.env.example docker/.env.local
docker compose --env-file docker/.env.local -f docker/docker-compose.yml up --build
```

- FastAPI: `http://127.0.0.1:8000`
- Langflow: `http://127.0.0.1:7860`

The Compose stack mounts source components/modules/services, host reports, Whisper/Hugging Face caches, and Langflow state volumes. Validate without starting:

```powershell
docker compose --env-file docker/.env.example -f docker/docker-compose.yml config
```

See [Deployment Guide](docs/DEPLOYMENT.md).

## FastAPI Usage

The HTTP API exposes auth, recording, transcription, ticket matching, knowledge search, audit payload/result, and report endpoints. Request models and the OpenAPI schema are defined in `api/main.py`.

Example health check:

```powershell
curl http://127.0.0.1:8000/health
```

Application errors use structured JSON:

```json
{"error":"ValidationError","message":"Human-readable safe message"}
```

## Environment Configuration

Supported variables include Genesys region/credentials, manual-token gating, PHI mode, file/duration limits, report/storage paths, and model/cache paths. Langflow and Docker-specific variables are documented separately.

See [Environment Reference](docs/ENVIRONMENT.md) and start with [`.env.example`](.env.example).

## Azure Roadmap

`transcriber-rewrite` includes Azure Container Apps deployment automation and Azure Blob/S3-compatible artifact provider implementations. The current deployment target is development-oriented and should be completed with:

1. Key Vault or managed-identity secret access
2. External durable artifact storage
3. External workflow/dispatcher state
4. Production ingress, authentication, and authorization
5. Model/cache and replica sizing validation
6. Structured observability, retention, backup, and recovery
7. Image security scans and reproducible release promotion

See [Deployment Guide](docs/DEPLOYMENT.md) and [Current Status](STATUS.md).

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Development](docs/DEVELOPMENT.md)
- [Services](docs/SERVICES.md)
- [Security and PHI](docs/SECURITY.md)
- [Testing](docs/TESTING.md)
- [Environment Variables](docs/ENVIRONMENT.md)
- [Current Status](STATUS.md)

## Safety Notes

- Audio, transcripts, reports, tickets, knowledge data, and logs may contain sensitive or PHI information.
- Use approved synthetic fixtures for tests.
- Use mode-aware PHI protection and secret stores in production.
- Preserve existing business logic, ticket matching, CEQ rules, audit outcomes, legacy components, and flow exports unless a separate approved change explicitly requests otherwise.
