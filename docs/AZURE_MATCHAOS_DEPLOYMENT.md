# Azure and MatchaOS Deployment Guide

This document describes the supported migration baseline. Azure is the
authoritative storage and processing layer; MatchaOS is the LLM provider and
workflow governance layer.

Runtime dependency: `azure-identity==1.25.1` provides managed-identity
authentication for Azure Storage and Azure AI Search. It is MIT licensed.

## Deployment topology

```text
ServiceNow/SharePoint/Power Automate
                |
                v
      Azure Blob private containers
                |
                +--> Azure AI Search (KB)
                +--> Azure Container App worker/API (SNOW + PHI)
                |
                v
          MatchaOS API
```

MatchaOS Mission storage is not used for source authority. Legacy Matcha file
routes and `mk_live_` keys are not used by the MatchaOS migration path.

## Azure resources

The Bicep deployment creates:

- a private Azure Storage account and private Blob containers
- Azure AI Search
- Key Vault
- a user-assigned managed identity
- Azure Container Registry
- Container Apps environment and application
- managed-identity role assignments for Blob, Key Vault, and ACR where supported

The default resource and network names are deployment parameters, never code
constants. Review global name uniqueness and Azure region availability before
deployment.

## Owner prerequisites

Before deployment, provide:

1. Subscription ID, tenant ID, approved region, and resource group.
2. A deployment principal with resource deployment and role-assignment rights.
3. Globally unique storage, Search, Key Vault, ACR, and Container App names.
4. A non-production MatchaOS key beginning with `mos_sk_live_`.
5. A browser-style `MATCHA_USER_AGENT`.
6. ServiceNow report attachment contract and synthetic export sample.
7. KB source location and synthetic sample.
8. Genesys region/client credentials and approved synthetic test data if call
   recording is in scope.

No ticket text, transcript text, audio, PHI, or secret value belongs in chat,
repository files, flow exports, source control, logs, or screenshots.

## Secret setup

Use Azure Key Vault, managed identity, and Container Apps secret references.
Secrets must not be added to Bicep parameter files or `.env.local`.

Runtime secret names:

- `MATCHAOS_API_KEY`
- `CEQ_API_SERVICE_TOKEN`
- `GENESYS_CLIENT_SECRET`
- `POWER_AUTOMATE_CALLBACK_SECRET`

Each secret also accepts a mounted-file equivalent:

- `MATCHAOS_API_KEY_FILE`
- `CEQ_API_SERVICE_TOKEN_FILE`
- `GENESYS_CLIENT_SECRET_FILE`
- `POWER_AUTOMATE_CALLBACK_SECRET_FILE`

The container and application must read only secret names/references. They must
not print, return, or log secret values.

## Environment contract

Required MatchaOS settings:

```text
MATCHAOS_BASE_URL=https://matchaos.harriscomputer.com
MATCHAOS_API_KEY or MATCHAOS_API_KEY_FILE
MATCHA_USER_AGENT=<browser-style User-Agent>
MATCHAOS_RATE_LIMIT_PER_MINUTE=120
```

Azure settings:

```text
AZURE_CLIENT_ID=<managed identity client id>
AZURE_STORAGE_ACCOUNT_URL=<storage blob endpoint>
AZURE_BLOB_SNOW_CONTAINER=snow
AZURE_BLOB_KB_CONTAINER=ceq-kb
AZURE_BLOB_EVIDENCE_CONTAINER=evidence
AZURE_SEARCH_ENDPOINT=<search endpoint>
AZURE_SEARCH_INDEX=ceq-kb
```

Do not place Azure access keys in these values. Managed identity is the
production authentication baseline.

## Power Automate SNOW ingestion

SNOW can move from legacy Matcha Storage without deleting or replacing the source
report file in a Mission.

1. The ServiceNow report flow must validate exactly one accepted attachment.
2. Validate workbook headers, minimum row count, timezone, and file hash.
3. Upload the file to the private `snow` Blob container with a unique immutable
   ingestion key.
4. Replace the approved current export only after the upload and hash validate.
5. Record generation, upload, settle, row count, and index state in metadata.
6. Wait the approved settle interval or until the hash/metadata is stable.
7. Send an authenticated callback to `/snow/refresh` with identifiers and counts
   only.
8. Keep the old current export until validation and processing succeed.

Raw SNOW exports must follow the approved no-retention/lifecycle policy. Derived
candidate data should be projected through the PHI gate before it reaches an LLM.

## KB ingestion

1. Power Automate or a SharePoint trigger uploads source files to the private `ceq-kb`
   container under tenant/client/source keys.
2. An Azure ingestion job validates format, normalizes HTML/text, chunks content,
   records source version/hash, and assigns the client alias.
3. Azure AI Search indexes article text and metadata.
4. Replacement and delete jobs reprocess the same logical source ID.
5. Retrieval uses client and tenant metadata filters, then hybrid search.
6. Application code validates returned source IDs before MatchaOS receives context.
7. MatchaOS receives only retrieved context and approved instructions, never raw
   source ownership state.

The initial portal/API implementation should use test data because MatchaOS is
not an authoritative file or folder API and cannot perform file replacement,
deletion, or download operations.

## Runtime roles

The existing container entrypoint supports `api`, `worker`, and `preflight`.

```text
docker build -f docker/Dockerfile -t ceq-platform:dev .
docker run --rm ceq-platform:dev preflight
docker compose --env-file .env.example --file docker/docker-compose.yml up
```

Production startup must use `_FILE` secret mounts or Key Vault references rather
than committed `.env` files.

## Health and rollout

- `/health/live` checks process liveness.
- `/health/ready` must be dependency-aware before production traffic.
- `/matchaos/models` verifies MatchaOS authentication when configured.
- `/matchaos/completions` executes a UUID Mission completion for controlled tests.
- `/snow/status` reports refresh metadata but not ticket text.
- Cutover remains in shadow mode until golden-corpus parity and rollback tests pass.

## Cleanup and rollback

Rollback:

- restore the previous Container App revision and image digest
- keep the last validated Blob source and index version
- leave Matcha Mission shadow paths active until the Azure cutover gate passes
- disable ingestion callbacks if source validation fails

Purge:

- delete ephemeral audio and scratch files after processing
- delete derived cache according to the approved lifecycle policy
- use versioned Blob deletion or container lifecycle only after evidence approval
- remove Key Vault secret versions according to tenant rotation policy
