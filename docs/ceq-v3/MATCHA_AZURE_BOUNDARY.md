# MATCHA_AZURE_BOUNDARY (v2, 2026-11-01)

Defines what crosses the boundary, in which direction, and under what trust rules.

## 1. Rules

1. Matcha calls Azure. Azure does not call Missions. Azure may call back only to signal completion (optional, signed webhook).
2. **Azure may read the SNOW export from the Matcha folder** (list and download only, never write) to run pre-match. This is the one exception to "Azure holds no SNOW data" and is limited to a short-lived derived cache (D12, needs approval).
3. Data entering Matcha is LLM-safe by construction: projection only, with a `phi_policy_version` attestation.
4. Matcha never stores audio or the canonical transcript. Azure never stores KB content and never writes to Mission Storage.
5. Every call carries `conversation_id`, `run_id` and `correlation_id`.
6. Idempotent: the same `conversation_id` plus `run_id` returns the existing job.

## 2. The two Matcha API surfaces

| | Legacy | New MatchaOS |
|---|---|---|
| Base URL | `https://matcha.harriscomputer.com/rest/api/v1` | `https://matchaos.harriscomputer.com/api` |
| Key | `mk_live_` + 64 hex, header `MATCHA-API-KEY` | `mos_sk_live_…`, any of several headers (Bearer, `matcha-api-key`, `x-api-key`) |
| IDs | Integers | UUIDs |
| Files | list, get, upload, replace (`PUT`, max 60 MB), delete, folder create | **None** |
| Missions | `completions` | `POST /v1/completions` (options include `includeSources`, `max_hits` 1 to 20, `responseLLM`) |
| Other | MDS flow endpoints | Flows runs (start, sync up to 90 s, poll), OpenAI/Anthropic/Gemini passthroughs |
| Limits | Documented 500/min and 2,000/day per key owner | Tested 120/min (daily unknown) |
| Required from Azure | Browser-style `User-Agent` (default Python agent gets 403) | Same assumed; set it everywhere |

Rule: environment values (host, folder ID, mission ID, key) are configuration, never code. File access and the missions that read those files stay in the same environment.

## 3. Azure internal API (called only by Matcha)

| Endpoint | Purpose |
|---|---|
| `POST /jobs/interaction` | Body: `conversation_id`, `region`, `channel`, `phi_mode` (default `LLM_MODE`). Returns `202` and `job_id`. |
| `GET /jobs/{job_id}` | Status `QUEUED`, `RUNNING`, `DONE`, `FAILED`, `RETRY_LATER`, with progress and error code. |
| `POST /snow/prematch` | Run (or re-run) pre-match for a conversation; calls use the stored fingerprint, emails pass one. See `AZURE_PREMATCH_SERVICE_SPEC.md`. |
| `POST /snow/refresh` | Called by Power Automate after each hourly replace. Body: `expected_rows`, `expected_size`. Azure re-reads, validates and returns what it saw (rows, size, hash, `updated_at`). |
| `GET /snow/status` | Export age, `updated_at`, rows, cache state. For alerts. |
| `POST /evidence/{conversation_id}` | Archive the final audit JSON and report; sets retention. |
| `POST /purge/{conversation_id}` | Delete audio, canonical transcript and caches; returns what was removed. |
| `GET /health/live`, `GET /health/ready` | Ready checks Whisper model, ffprobe, storage, Genesys credentials, Matcha read access. |

`/recording/download`, `/transcribe` and `/generate-report` stay internal building blocks.

## 4. Job result contract (v2)

- Identity: `status`, `channel`, `conversation_id`, `recording_id`, `call_start`, `call_end`, `agent_names`, `agent_emails`, `queue_ids`, `wrapup_code_ids`.
- Text: `clean_transcript` as `[mm:ss] AGENT|CALLER|IVR:` lines, projected for PHI.
- Signals: `hold_events` (Genesys source preferred), `long_silence_events`, caller-requested pauses, talk ratios, confidence and review flags.
- **Fingerprint (projected)**: only the fields Matcha needs to explain a match (see pre-match spec). The raw fingerprint stays in Azure.
- **SNOW block**: `snow_status` (`MATCHED`, `AMBIGUOUS`, `NOT_FOUND`, `PENDING_EXPORT`, `RETRY_LATER`, `OUT_OF_WINDOW`), `exported_at`, up to N sanitized candidates with score breakdown, PHI flags per field.
- PHI: `phi_policy_version`, `phi_mode`, finding categories and counts only.
- Provenance: `model_used`, `engine_version`, `transcript_artifact_ref`, `prematch_engine_version`.

Absent by design: canonical transcript, raw ticket text, audio paths, offsets that could locate redacted text.

## 5. PHI boundary

| Data | Where protected | Mechanism |
|---|---|---|
| Audio-derived transcript | Azure, before response | PHI v2 projection plus attestation |
| SNOW ticket rows (candidates) | Azure, after scoring on raw rows | Sanitize top N only; typed placeholders plus flags |
| KB excerpts | Matcha Mission Caller | Sentence gate with the same policy version (KB text should hold no PHI) |
| Reports, archive | Azure Blob / MatchaOS | Encryption, access control, retention |

Keep, never redact in `LLM_MODE`: workforce names (analysts, callers who are clinicians or staff, requesters and contacts on tickets), call fingerprint, ticket and KB references, phone and extension, employee IDs, departments, devices. Protect: patient names, MRN, FIN, DOB, SSN, insurance IDs, clinical information. Details and decision rules: `PHI_POLICY_V2.md`.

Fail closed: the Mission Caller blocks to manual QA if the attestation is missing, the policy version is below the minimum, or Azure reports `STRICT` hits.

## 6. Azure calling Matcha (read-only)

| Rule | Detail |
|---|---|
| Operations | List folder and download the single export only. |
| Identity | A dedicated service user whose permissions cover only the SNOW mission folder, with its own key (legacy keys appear to carry the user's permissions; confirm scoping). |
| Headers | Browser-style `User-Agent` on every call. |
| Validation | Check the `PK` zip header, expected sheet and column names, row count above zero, and hash against the value Azure computed. |
| Throttle | Refresh on a push from Power Automate plus a backup check every 15 minutes; single-flight; no per-audit listing. |
| Failure | Retry with exponential backoff; keep the last good copy; if nothing readable, return `RETRY_LATER`, never `NOT_FOUND`. |
| Logging | Never log row contents, file names beyond ID, or keys. |

## 7. Authentication

- Matcha to Azure: Entra ID app token or a rotated API key from the Matcha secret store; Azure validates at ingress. Matcha egress addresses unknown (verify) so do not rely on IP restriction alone.
- Azure to Genesys: client credentials from Key Vault by managed identity. Manual-token mode disabled in production.
- Azure to Matcha files: key from Key Vault by managed identity.
- Power Automate to Azure (`/snow/refresh`): API key in a secure input, not in the flow body.
- Azure to Matcha (callback): signed webhook (optional).

## 8. Reliability

- Matcha polls `GET /jobs/{id}` with backoff; total budget aligned to the existing 90-minute per-item ceiling.
- `RETRY_LATER` when the Genesys recording is not ready or the SNOW export is unreadable.
- Job state and the SNOW cache live in durable storage, so scale-to-zero and restarts lose nothing.
- Client-side rate limiter in every Matcha caller (under 120 per minute for the new key, under 500 for legacy) and honour `retry-after` on 429.

## 9. Observability

Azure: structured JSON logs (no transcripts, ticket text or tokens), Application Insights with `correlation_id`, metrics `snow_export_age_minutes`, `prematch_status_counts`, `cache_hit_rate`, `matcha_http_status_counts`. Matcha: routing log with cost and model per Mission call. A shared `run_id` links both.

## 10. Retention (proposals, need owner sign-off; none is specified in the repo)

| Item | Proposal |
|---|---|
| Audio | Delete after transcription; hard cap same day |
| Canonical transcript | Shortest period legal and QA allow |
| SNOW cache in Azure | Expires about 6 hours after the last refresh; encrypted |
| Inbound SNOW copies in SharePoint | 1 to 2 days (they may contain PHI) |
| Evidence archive | Per client retention |
| Matcha run messages | Purge after audit via the existing component |
