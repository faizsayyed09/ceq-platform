# Deployment Guide

## Local FastAPI

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env.local
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Verify:

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/docs
```

## Docker Compose

```powershell
Copy-Item docker/.env.example docker/.env.local
# Replace placeholders in docker/.env.local with approved local values.
docker compose --env-file docker/.env.local -f docker/docker-compose.yml up --build
```

Endpoints:

- FastAPI: `http://127.0.0.1:8000`
- Langflow: `http://127.0.0.1:7860`

Docker Compose supplies persistent Langflow, Whisper, and Hugging Face volumes. Generated reports, audio, model files, credentials, PHI, and transcripts must not be committed.

Before deployment, validate Compose in a Docker-capable environment:

```powershell
docker compose --env-file docker/.env.example -f docker/docker-compose.yml config
docker compose --env-file docker/.env.example -f docker/docker-compose.yml build
docker compose --env-file docker/.env.example -f docker/docker-compose.yml up -d
```

## Docker Image

The Dockerfile uses a Python 3.12 runtime, installs ffmpeg, creates a non-root user, and starts Uvicorn on port 8000. The builder stage copies `requirements.txt`, and the runtime stage copies the application.

Production images should be reproducible and vulnerability-scanned before release. The Compose Langflow image and package versions should be pinned or reviewed in release automation before production promotion.

## Azure Container Apps

`scripts/deploy-azure.ps1` provides an initial Azure Container Registry and Azure Container Apps deployment workflow. Example:

```powershell
.\scripts\deploy-azure.ps1 `
  -SubscriptionId "<subscription-id>" `
  -AcrName "<globally-unique-acr-name>" `
  -ResourceGroup "rg-ceq-v2-dev" `
  -Location "eastus"
```

The script:

1. Sets the subscription and creates the resource group.
2. Creates Azure Container Registry and builds/pushes the image.
3. Creates a Container Apps environment and application.
4. Configures external ingress and port 8000.
5. Uses a system-assigned identity for ACR pull.

## Azure Readiness Gaps

Before production Azure deployment, verify:

- External or managed artifact storage instead of ephemeral container files
- Durable workflow/dispatcher state outside worker memory
- Key Vault or managed identity secret access
- HTTPS, ingress restrictions, authentication, and authorization
- Container replica sizing for Whisper and larger memory requirements
- Persistence and cache strategy for models
- Queue or broker integration if workflow jobs become asynchronous
- Structured logs, metrics, tracing, alerts, and retention
- Backup, recovery, retention, and deletion procedures
- Controlled release rollback and image promotion
- Readiness probes that check dependencies without leaking data

The Azure script is a development/deployment accelerator, not proof of production readiness.

## Environment and Secrets

Use secret stores or Container Apps secrets in Azure. Do not put credentials in source control or place client secrets in image layers. See [ENVIRONMENT.md](ENVIRONMENT.md) for variables.

## Artifact Storage

Local filesystem storage is the default development implementation. For stateless or scaled production execution, use a provider with external object storage and explicit lifecycle policies. Container-local reports must not be the system of record.

## Verification Checklist

- [ ] Python test suite passes
- [ ] Python sources compile
- [ ] Compose configuration renders successfully
- [ ] FastAPI health, liveness, and readiness endpoints respond
- [ ] Docker image starts as non-root
- [ ] Recording/transcription limits are exercised
- [ ] No secrets or PHI are present in logs or repository changes
- [ ] Azure identity and provider configuration are validated
- [ ] External artifact storage is tested
- [ ] Release image is scanned and pinned
