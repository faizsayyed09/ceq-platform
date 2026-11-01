# DOCKER_PACKAGING_AND_PORTABILITY (v1, 2026-11-01)

Goal: after the service is finished (Phase 8), produce one container image that runs on any host that meets a documented list of prerequisites: Azure Container Apps, Kubernetes, or a plain Docker host. This document specifies the image and its prerequisites. The Dockerfile, compose file and CI definition are code and are written when you approve Phase 8, from the repository (I do not have the finished repository here).

## 1. Principles

1. **Twelve-factor**: all configuration through environment variables; no environment-specific value in the image.
2. **No secrets in the image**, ever. Secrets arrive at start-up from the host.
3. **Nothing downloaded at run time**: models, language data and certificates are baked in, so the image starts offline except for the services it must call.
4. **Same image everywhere**: the host differs only in configuration, secrets, network and storage.
5. **Fail early**: a preflight command reports every missing prerequisite before traffic arrives.

## 2. Image contents

| Layer | Contents |
|---|---|
| Base | Slim Linux image pinned by digest; time zone data; CA bundle; non-root user |
| System tools | FFmpeg and ffprobe |
| Python runtime and dependencies | Pinned by lock file; hash-checked |
| ASR | The chosen engine and model, pinned by checksum (faster-whisper `large-v3-turbo` today; Parakeet if the bake-off selects it) |
| PHI | Presidio, the language model it needs, the classifier model, the regex pack, the policy version |
| Application | API, job runner, pre-match service, adapters |
| Notices | License file, SBOM, third-party attributions (including CC-BY-4.0 if Parakeet is used) |

Multi-stage build; final image has no compilers or package caches. One image, selectable role: `api`, `worker`, `preflight`, `migrate` (if any). Platform amd64 required; arm64 only if a target needs it.

## 3. Configuration (proposed variable names)

| Variable | Purpose |
|---|---|
| `APP_ENV`, `LOG_LEVEL`, `TZ` | Environment name, verbosity, time zone (UTC) |
| `MATCHA_BASE_URL` | Legacy or new host; changes at migration |
| `MATCHA_API_KEY` or `MATCHA_API_KEY_FILE` | Read-only key for the SNOW folder |
| `MATCHA_USER_AGENT` | Browser-style string; mandatory |
| `SNOW_FOLDER_ID`, `SNOW_MISSION_ID` | Export location |
| `SNOW_CACHE_DIR`, `SNOW_CACHE_TTL_MINUTES` | Cache path and expiry |
| `SNOW_BACKUP_CHECK_MINUTES` | Backup refresh interval |
| `PREMATCH_TOP_N`, `PREMATCH_GRACE_MINUTES` | Defaults 3 and 60 |
| `GENESYS_REGION`, `GENESYS_CLIENT_ID`, `GENESYS_CLIENT_SECRET` (or `_FILE`) | Recording access |
| `STORAGE_PROVIDER` | `local`, `azure_blob` or `s3`; plus the provider's own settings |
| `AUTH_MODE`, `AUTH_API_KEYS_FILE` or `ENTRA_TENANT_ID`, `ENTRA_AUDIENCE` | Caller authentication |
| `PHI_POLICY_VERSION_MIN` | Minimum accepted version |
| `ASR_ENGINE`, `ASR_MODEL_PATH`, `ASR_THREADS` | Engine selection and CPU use |
| `HTTPS_PROXY`, `NO_PROXY`, `EXTRA_CA_BUNDLE` | Corporate proxy and private CA |
| `OTEL_EXPORTER_OTLP_ENDPOINT` or `APPLICATIONINSIGHTS_CONNECTION_STRING` | Telemetry sink |

Every secret variable accepts a `_FILE` form so Docker secrets, Kubernetes secrets and mounted Key Vault files work without code changes. A committed `.env.example` lists every variable with a comment and no real values.

## 4. Network prerequisites

| Direction | Destination | Port | Needed for |
|---|---|---|---|
| Outbound | Matcha host (legacy today; new host later) | 443 | SNOW export read; browser-style User-Agent required |
| Outbound | Genesys regional API and its media hosts (pre-signed URLs; **verify the exact host list**) | 443 | Recording download |
| Outbound | Key Vault or the chosen secret store | 443 | Secrets at start-up (optional if secrets are mounted) |
| Outbound | Blob or S3 endpoint | 443 | Evidence and canonical transcript (not needed with `local`) |
| Outbound | Telemetry endpoint | 443 | Logs and traces |
| Outbound | DNS and time (NTP) | 53, 123 | Resolution and token validity |
| Inbound | The API port (default 8000) | 8000 | Only from Matcha and Power Automate; TLS ends at the ingress or proxy |

Do not depend on fixed source addresses: Container Apps outbound is a shared pool; a NAT gateway is needed if a partner insists on a fixed address (open item 9). If a corporate proxy is used it must pass the Matcha host without rewriting the User-Agent.

## 5. Volumes and state

| Mount | Purpose | Persistence |
|---|---|---|
| `/data/cache` | Encrypted SNOW cache | Recommended so restarts and scale-to-zero reuse it; safe to lose |
| `/data/jobs` | Job state if no database is configured | Required unless a durable store is configured |
| `/tmp` | Audio and scratch | Ephemeral; cleared after each job |

Audio and canonical transcripts are never written to the image or to a shared volume that outlives the retention policy.

## 6. Start-up, health and preflight

- `preflight` role: checks that every required variable is present; secrets readable; DNS and TLS to each destination; Matcha list call succeeds (and a 403 is reported as "check User-Agent"); Genesys token obtainable; storage writable; model files present with the expected checksum; ffprobe runs; the PHI classifier loads; clock skew small. It prints a pass or fail per check, with no secret values, and exits non-zero on failure.
- `/health/live`: process alive. `/health/ready`: dependencies healthy (the existing check always says ready; replace it).
- The container refuses to serve if preflight's required checks fail.

## 7. Resources (to be measured, not assumed)

Today: 1 vCPU, 2 Gi, min 0, max 1. Measure peak memory and real-time factor for the chosen ASR model, Presidio and the classifier together before fixing requests and limits; record cold-start time. Publish the measured numbers in the release notes.

## 8. Supply chain and release

| Step | Rule |
|---|---|
| Build | CI builds from a tagged commit; reproducible; base image and dependencies pinned |
| Tags | Semantic version plus short commit hash; deployments use the digest |
| Scan | Vulnerability scan; fail on critical findings |
| SBOM | Generated and stored with the release |
| Signing | Image signed; hosts verify |
| Registry | Azure Container Registry with managed identity (align the Bicep drift: admin user off) |
| Notices | Licenses and attributions included |

## 9. Reference deployments

- **Azure Container Apps**: image from the registry; secrets from Key Vault by managed identity; ingress with authentication; scale rules; min replicas set by the cold-start measurement.
- **Kubernetes**: Deployment plus Service; Secrets or CSI-mounted Key Vault; readiness on `/health/ready`; a CronJob not needed (refresh is push plus in-process timer).
- **Plain Docker host**: a compose file with the API and an optional reverse proxy, a named volume for `/data`, secrets as files.
- **Offline or air-gapped**: works if the Matcha host, Genesys and storage are reachable; telemetry optional.

## 10. Release gate (Phase 8 exit)

1. The image starts on a clean host using only this document's prerequisites.
2. Preflight passes; a deliberately removed secret or blocked host is reported clearly.
3. A synthetic call replays end to end: download, transcription, fingerprint, pre-match, sanitize, result.
4. No secret, audio or transcript is present in the image or its layers (checked by scan).
5. The same image digest runs in Container Apps and on a plain Docker host with different configuration only.
6. Release notes list measured resources, versions, model checksums and the policy version.

## 11. What I need to build it

The finished repository (or access to it), the list of target hosts (open item 13), the chosen ASR engine, and the secret store each host will use.
