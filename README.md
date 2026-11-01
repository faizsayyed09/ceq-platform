# CEQ Platform

CEQ Platform is a FastAPI service for Genesys recording retrieval, transcription, role-aware PHI protection, ticket pre-match, knowledge lookup, audit workflows, reports, and artifacts.

## Architecture

- Matcha/Missions own workflow, governance, authority, ticket confirmation, dashboards, and Mission Storage.
- Azure owns compute, transcription, PHI processing, pre-match, jobs, and derived caches.
- Matcha never holds duplicate authoritative SNOW/KB data; Azure must never call a Mission.
- The maintained CEQ v3 source is [docs/ceq-v3/00_INDEX.md](docs/ceq-v3/00_INDEX.md).

See [Architecture](docs/ARCHITECTURE.md), [Services](docs/SERVICES.md), and the ownership matrix under `docs/ceq-v3/`.

## Run locally

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env.local
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

## Test

```powershell
python -m pytest -q
```

## Docker

```powershell
docker compose --env-file docker/.env.example -f docker/docker-compose.yml config
docker compose --env-file docker/.env.example -f docker/docker-compose.yml up --build
```

The API-only Compose path is the maintained local deployment. Langflow components and legacy flow exports remain compatibility assets; they are not authoritative deployment components.

## Security

Use Key Vault, Container Apps secrets, mounted `_FILE` secrets, or approved environment configuration. Never commit keys, recordings, transcripts, ticket exports, reports, or PHI.

## Maintained documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Services](docs/SERVICES.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Development](docs/DEVELOPMENT.md)
- [Testing](docs/TESTING.md)
- [Security](docs/SECURITY.md)
- [Environment](docs/ENVIRONMENT.md)
- [Status](docs/STATUS.md)
- [Changelog](docs/CHANGELOG.md)
