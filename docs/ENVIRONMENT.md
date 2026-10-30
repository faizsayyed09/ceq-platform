# Environment Variables

Secrets belong in `.env.local`, Docker local env files, platform secret stores, Azure Key Vault, or managed identity configuration. Never commit populated secret values.

## Application Variables

| Variable | Required | Default | Purpose | Environment |
|---|---:|---|---|---|
| `APP_ENV` | No | `development` | Application environment label | API, Docker, Langflow, Azure |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity | API, Docker, Langflow, Azure |
| `GENESYS_REGION` | Conditional | `mypurecloud.com` | Default Genesys API region | API, Langflow, Azure |
| `GENESYS_CLIENT_ID` | Conditional | Empty | Genesys OAuth client ID | API, Langflow, Azure |
| `GENESYS_CLIENT_SECRET` | Conditional | Empty | Genesys OAuth client secret | API, Langflow, Azure |
| `ALLOW_MANUAL_TOKEN_TESTING` | No | `false` | Enables manual bearer tokens only in approved test environments | API, Langflow, Azure |
| `PHI_PROTECTION_MODE` | No | `AUDIT_MODE` | One of `OFF`, `AUDIT_MODE`, `LLM_MODE`, `STRICT` | API, Langflow, Azure |
| `MAX_FILE_SIZE_MB` | No | `500` | Maximum upload/download size | API, Docker, Azure |
| `MAX_AUDIO_DURATION_SECONDS` | No | `14400` | Maximum transcribed audio duration | API, Docker, Azure |
| `REPORT_DIR` | No | `generated_reports` locally | Local report/artifact directory; container default should be mounted externally | API, Docker |
| `RECORDING_STORAGE_PATH` | No | `./recordings` | Recording download storage location | API, Docker, Azure |
| `RECORDING_RETENTION_HOURS` | No | Empty | Optional recording retention period used by recording logic | API, Docker, Azure |
| `WHISPER_MODEL_CACHE` | No | Environment-dependent | Explicit Whisper model cache directory | API, Docker, Langflow, Azure |
| `HF_HOME` | No | Empty / Compose cache | Hugging Face cache directory | API, Docker, Langflow |
| `PYTHONPATH` | Conditional | Empty locally; Compose sets `/app/ceq-components:/app` | Module/component import path | Docker, Langflow |

## Docker and Langflow Variables

| Variable | Required | Default | Purpose | Environment |
|---|---:|---|---|---|
| `LANGFLOW_IMAGE` | No | `langflowai/langflow:latest` | Compose Langflow image | Docker local |
| `LANGFLOW_PORT` | No | `7860` | Host port for Langflow | Docker local |
| `LANGFLOW_AUTO_LOGIN` | No | `true` | Enables local Langflow auto-login; not for production exposure | Docker local |
| `LANGFLOW_SUPERUSER` | Conditional | `admin` | Langflow local superuser name | Docker local |
| `LANGFLOW_SUPERUSER_PASSWORD` | Conditional for secured Langflow | Empty | Langflow local superuser password | Docker local |
| `LANGFLOW_CONFIG_DIR` | No | `/app/langflow` | Langflow persistent configuration directory | Docker |
| `LANGFLOW_COMPONENTS_PATH` | No | `/app/ceq-components` | Custom-component mount location | Docker/Langflow |

## Azure Variables

The Azure deployment script accepts script parameters separately from runtime variables:

| Script Parameter | Required | Default | Purpose |
|---|---:|---|---|
| `SubscriptionId` | Yes | None | Azure subscription |
| `Location` | No | `eastus` | Resource location |
| `ResourceGroup` | No | `rg-ceq-v2-dev` | Resource group |
| `AcrName` | Yes | None | Globally unique Azure Container Registry name |
| `ContainerAppEnvironment` | No | `cae-ceq-v2-dev` | Container Apps environment |
| `ContainerApp` | No | `ca-ceq-v2-dev` | Container App name |
| `ImageTag` | No | `v2-dev` | Built image tag |
| `GenesysRegion` | No | `mypurecloud.com` | Genesys region injected into the app |
| `GenesysClientId` | No | Empty | Optional Genesys client ID |
| `GenesysClientSecret` | No | Empty | Optional Genesys client secret |

## Variable Rules

- Boolean variables should be explicit lowercase `true` or `false` strings in env files.
- Empty Docker defaults must not be interpreted as valid secrets.
- `MAX_FILE_SIZE_MB` and `MAX_AUDIO_DURATION_SECONDS` should be positive and appropriate for platform memory/disk limits.
- `GENESYS_REGION` must match an approved Genesys region allowlist value.
- Production should use secret references rather than placing `GENESYS_CLIENT_SECRET` directly in ordinary environment files.
- `LANGFLOW_AUTO_LOGIN=true` is for local development only.
- `RECORDING_RETENTION_HOURS` should be validated if used by a future retention lifecycle; current workspaces should not assume it is automatically reconciled across providers.

## Example Local Files

```powershell
Copy-Item .env.example .env.local
Copy-Item docker/.env.example docker/.env.local
```

`.env.local` files are ignored by Git. Docker Compose uses the example file for defaults and should be layered with an approved local env file only outside source control.
