# Environment Variables

Secrets belong in `.env.local`, Docker local env files, platform secret stores, Azure Key Vault, or managed identity configuration. Never commit populated secret values.

## Application Variables

| Variable | Required | Default | Purpose | Environment |
|---|---:|---|---|---|
| `APP_ENV` | No | `development` | Application environment label | API, Docker, Langflow, Azure |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity | API, Docker, Langflow, Azure |
| `MATCHA_BASE_URL` | Conditional | Empty | Matcha or MatchaOS host; legacy file operations and new Mission operations require the matching host/key pair | API, Docker, Power Automate, Azure |
| `MATCHA_API_KEY` | Conditional | Empty | Matcha API key; also accepts `MATCHA_API_KEY_FILE`; never store in flow exports | API, Docker, Power Automate, Azure |
| `MATCHA_USER_AGENT` | Conditional | Empty | Browser-style User-Agent required by Matcha file and Mission callers | API, Docker, Power Automate, Azure |
| `SNOW_FOLDER_ID` | Conditional | Empty | Matcha folder or Mission-location identifier; no default until confirmed | Power Automate, Azure |
| `SNOW_MISSION_ID` | Conditional | Empty | Matcha Mission used to read the permanent SNOW export | Power Automate, Azure |
| `SNOW_FILE_ID` | Conditional | Empty | Permanent file ID returned by Matcha bootstrap; store in secure configuration | Power Automate |
| `SNOW_FILENAME` | Phase 1 | Empty | Stable permanent export filename, without a path | Power Automate |
| `CEQ_API_SERVICE_TOKEN` | Production | Empty | Bearer token for service-to-service API authentication; also accepts `CEQ_API_SERVICE_TOKEN_FILE` | API, Docker, Azure |
| `GENESYS_REGION` | Conditional | `mypurecloud.com` | Default Genesys API region | API, Langflow, Azure |
| `GENESYS_CLIENT_ID` | Conditional | Empty | Genesys OAuth client ID | API, Langflow, Azure |
| `GENESYS_CLIENT_SECRET` | Conditional | Empty | Genesys OAuth client secret | API, Langflow, Azure |
| `ALLOW_MANUAL_TOKEN_TESTING` | No | `false` | Enables manual bearer tokens only in approved test environments | API, Langflow, Azure |
| `PHI_PROTECTION_MODE` | No | `AUDIT_MODE` | One of `OFF`, `AUDIT_MODE`, `LLM_MODE`, `STRICT` | API, Langflow, Azure |
| `PREMATCH_MODE` | No | `shadow` | One of `matcha`, `shadow`, `azure`; no cutover until the Phase 3 gate passes | API, Azure |
| `PREMATCH_CACHE_ENABLED` | No | `false` | Reserved for the approved D12 cache implementation; the baseline stores refresh metadata only | API, Azure |
| `PREMATCH_TOP_N` | No | `3` | Candidate count from 1 through 5 | API, Azure |
| `MAX_FILE_SIZE_MB` | No | `500` | Maximum upload/download size | API, Docker, Azure |
| `MAX_AUDIO_DURATION_SECONDS` | No | `14400` | Maximum transcribed audio duration | API, Docker, Azure |
| `REPORT_DIR` | No | `generated_reports` locally | Local report/artifact directory; container default should be mounted externally | API, Docker |
| `RECORDING_STORAGE_PATH` | No | `./recordings` | Recording download storage location | API, Docker, Azure |
| `RECORDING_RETENTION_HOURS` | No | Empty | Optional recording retention period used by recording logic | API, Docker, Azure |
| `WHISPER_MODEL_CACHE` | No | Environment-dependent | Explicit Whisper model cache directory | API, Docker, Langflow, Azure |
| `HF_HOME` | No | Empty / Compose cache | Hugging Face cache directory | API, Docker, Langflow |
| `PYTHONPATH` | Conditional | Empty locally; Compose sets `/app/ceq-components:/app` | Module/component import path | Docker, Langflow |

## Azure Variables

Azure runtime configuration is supplied by Container Apps configuration and Key Vault/managed identity references. Host, folder, mission, and key values must remain environment-specific and must not be constants.

## Variable Rules

- Boolean variables should be explicit lowercase `true` or `false` strings in env files.
- Empty Docker defaults must not be interpreted as valid secrets.
- `MAX_FILE_SIZE_MB` and `MAX_AUDIO_DURATION_SECONDS` should be positive and appropriate for platform memory/disk limits.
- `GENESYS_REGION` must match an approved Genesys region allowlist value.
- Production should use secret references rather than placing `GENESYS_CLIENT_SECRET` directly in ordinary environment files.
- `RECORDING_RETENTION_HOURS` should be validated if used by a future retention lifecycle; current workspaces should not assume it is automatically reconciled across providers.

## Example Local Files

```powershell
Copy-Item .env.example .env.local
Copy-Item docker/.env.example docker/.env.local
```

`.env.local` files are ignored by Git. Docker Compose uses the example file for defaults and should be layered with an approved local env file only outside source control.
