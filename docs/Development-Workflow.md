# CEQ Platform Development Workflow

## Source of truth

- `services/` and `modules/` contain reusable, framework-neutral implementation.
- `components/` contains Langflow adapters and is the canonical custom-component directory.
- `api/main.py` is a FastAPI adapter over the same services.
- `flows/*.json` are exports for disaster recovery and should not be edited as the normal implementation source.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env.local
pytest -q tests
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Use `.env.local` for credentials. It must never be committed.

## VS Code

Tracked team configuration lives in `.vscode/`. Recommended extensions are listed in `.vscode/extensions.json`. Launch profiles start FastAPI or pytest and load `.env.local`.

## Langflow custom components

### Desktop

1. Open Langflow Desktop settings.
2. Set the custom-components directory to:

```text
C:\Projects\CEQ-Platform\components
```

3. In the Langflow environment, set:

```text
PYTHONPATH=C:\Projects\CEQ-Platform;C:\Projects\CEQ-Platform\components
```

4. Set the same CEQ environment variables used by FastAPI in the Langflow environment or start script.
5. Save component files in VS Code, use Langflow's **Reload Components** action, and refresh the open flow.

### Docker

The compose stack mounts `components/` read-only into Langflow at `/app/ceq-components`. It also mounts `services/` and `modules/` read-only. Set the Langflow custom component folder to `/app/ceq-components` when supported by the selected Langflow version. If the pinned image exposes a different setting name, configure that setting in the Langflow UI; the path remains the same. `PYTHONPATH=/app/ceq-components:/app` is provided automatically.

Generated reports are mounted at `/app/generated_reports`; faster-whisper/Hugging Face caches persist in named volumes. Langflow state persists in `langflow_data`.

```powershell
Copy-Item docker/.env.example docker/.env.local
docker compose --env-file docker/.env.local -f docker/docker-compose.yml up --build
```

FastAPI: `http://127.0.0.1:8000/health`  
Langflow: `http://127.0.0.1:7860`

## Docker layout

```text
docker/Dockerfile                 FastAPI image
docker/docker-compose.yml         FastAPI + Langflow local stack
docker/.env.example               Non-secret Docker defaults
generated_reports/                Host-bound report artifacts
whisper_models named volume       /app/models/whisper
hf_cache named volume             /app/cache/huggingface
langflow_data named volume        Langflow state/database
```

No model, report, audio, secret, database, or cache should be committed.

## Git lifecycle

```powershell
git switch main
git pull --ff-only origin main
git switch -c feature/<topic>
pytest -q tests
docker compose --env-file docker/.env.example -f docker/docker-compose.yml config
docker compose --env-file docker/.env.example -f docker/docker-compose.yml up --build
git add <files>
git commit -m "feat(<scope>): <summary>"
git push -u origin feature/<topic>
```

Open a PR, wait for required CI checks, merge to `main`, then tag a release on `main` with `vX.Y.Z`.

Branch conventions: `main`, `transcriber-rewrite` for the current stabilization integration, and short-lived `feature/*`, `fix/*`, and `security/*` branches.

## Component standards

- Place Langflow adapters under `components/<domain>/`.
- Keep implementation in `services/` and technical support in `modules/`.
- Use lowercase snake_case filenames and PascalCase classes.
- Use `tests/unit/test_<service_or_behavior>.py` for logic and `tests/unit/test_api.py` for HTTP behavior.
- Keep component README files beside the component area and service contracts in `docs/`.
- Never copy service logic into a component.

## MCP readiness

MCP tools should be thin adapters only:

| MCP capability | Existing CEQ boundary |
|---|---|
| GenesysAuthService | `services/genesys_auth.py` |
| RecordingService | `services/recording.py` |
| TranscriptionService | `services/transcription.py` |
| Fingerprint/Ticket matching | `services/matching.py` |
| KnowledgeService | `services/knowledge.py` |
| AuditService | `services/audit.py` |
| ReportService | `services/report.py` |

Future MCP code belongs under `mcp/` and must validate inputs, reuse `Settings`/error handling, avoid raw credential parameters, and use `ArtifactStore` for files.
