# Development Guide

## Prerequisites

- Windows PowerShell
- Python 3.12
- Git
- Docker Desktop for container workflows
- Optional Langflow Desktop or Docker runtime
- FFmpeg for transcription/media validation in local environments

## Initial Setup

```powershell
git switch transcriber-rewrite
git pull --ff-only origin transcriber-rewrite
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env.local
pytest -q tests
```

Use `.env.local` or a tool-provided environment for local secrets. The repository excludes `.env`, `.env.*`, local output, caches, models, and generated reports except for approved example files.

## Source Ownership

- Put reusable implementation in `services/`, `modules/`, and `contracts/`.
- Put FastAPI concerns in `api/`.
- Put external provider implementations in `providers/`.
- Put Langflow runtime adapters under `components/`.
- Preserve `flows/*.json` unless an explicit separate migration/replacement change approves their update or removal.
- Do not duplicate service logic inside Langflow components.

## FastAPI Development

```powershell
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Use `/docs` for interactive OpenAPI exploration and `/health` for basic availability checks.

## VS Code

The repository tracks team settings, launch profiles, and extension recommendations under `.vscode/`. Launch configuration should point at local environment files and avoid embedding credentials.

## Langflow Development

For desktop Langflow, configure the custom-components directory as the repository's `components/` directory and provide a Python path containing the repository root and components path. Reload components after source changes.

For Compose Langflow, the repository mounts components, modules, services, flows, reports, and model caches into the container. Read-only mounts protect source files from runtime mutation.

## Adding a Feature

1. Start from `transcriber-rewrite` or an approved feature branch.
2. Add or update contracts before changing adapters when an API boundary changes.
3. Implement reusable behavior in the service/provider layer.
4. Keep route/component changes thin.
5. Add focused unit tests.
6. Run compile, tests, and Compose validation where available.
7. Review documentation and environment variables affected by the change.

## Testing Workflow

```powershell
pytest -q tests
python -m compileall -q api modules services components contracts providers
```

Use focused test selection while iterating:

```powershell
pytest -q tests/unit/test_transcription_service.py
pytest -q tests/unit/test_api.py
```

See [TESTING.md](TESTING.md).

## Docker Workflow

```powershell
docker compose --env-file docker/.env.example -f docker/docker-compose.yml config
docker compose --env-file docker/.env.example -f docker/docker-compose.yml up --build
```

Stop and remove the local stack:

```powershell
docker compose -f docker/docker-compose.yml down
```

## Git Workflow

Use short-lived `feature/*`, `fix/*`, or `security/*` branches. Keep documentation-only cleanup commits separate where practical.

```powershell
git switch transcriber-rewrite
git pull --ff-only origin transcriber-rewrite
git switch -c docs/<topic>
pytest -q tests
git add README.md STATUS.md docs
# Commit through the repository's approved workflow.
```

## Generated Files

Do not commit:

- `__pycache__/` and `*.pyc`
- `.pytest_cache/`
- `.venv/`, virtual environments
- Audio, transcripts, model caches, credentials
- Reports and artifact output
- Local database or Langflow runtime state

## Documentation Maintenance

Update `README.md`, `STATUS.md`, service documentation, environment documentation, and deployment status whenever behavior or infrastructure readiness materially changes. Treat diagrams as high-level views, not substitutes for implementation and tests.
