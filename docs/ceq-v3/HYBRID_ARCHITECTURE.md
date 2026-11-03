# HYBRID_ARCHITECTURE (v2, 2026-11-01)

Basis: the `transcriber-rewrite` repo contents, the Matcha reference documents, the three original MDS Studio flows (CALL_AUDITS, EMAIL_AUDITS, CEQ_DISPATCHER), the KB Power Automate flow export, and the live tests in `MATCHA_API_TEST_REPORT.md`. Labels: Tested, Documented, Observed in export, Proposed, Unknown.

## 1. Current state

| Area | Finding |
|---|---|
| Azure deployment | Container Apps app `ca-ceq-dev-api` in `rg-ceq-dev-eastus`, environment `cae-ceq-dev`, FastAPI, 1 CPU / 2 Gi, min 0 and max 1 replicas. Ingress defaults to private and deployments set `APP_ENV=production`; bearer authentication is required outside public health endpoints. `/health/ready` reports preflight failures. Outbound traffic leaves from a shared pool of about 300 addresses (not whitelistable). Tested/Observed/Partially remediated. |
| Matcha pipeline | The working audit chain is Langflow (MDS Studio): recording downloader, transcriber, fingerprint plus SNOW pre-match (deterministic), SNOW Mission, ticket gate, KB query, KB Mission, payload builder, CEQ Mission, audit result parser, report download, purge. It already follows "code guards, Missions judge". |
| Azure `AuditWorkflowService` | Never calls a Mission; takes `ceq_response` as input; keeps run state in a Python dict; uses a naive matcher. An evidence assembler, not an orchestrator. |
| Azure `DispatcherService` | In-memory state, no SNOW-freshness gate (the Matcha dispatcher has one). |
| Duplication | Two ticket matchers (naive `matching.py`; ported `ticket_matching_service.py`). Two PHI engines plus a third regex set inside the Matcha LLM-caller components. Two transcription stacks. Three identical copies of the Mission-caller and Genesys-auth components. EMAIL and CALL result parsers drifted. |
| SNOW export | ServiceNow scheduled report emailed to Power Automate, which feeds a Mission folder. The pre-match component lists the folder, picks the newest `.xlsx` by `updated_at`, falls back through the three newest, validates the file header, caches by (file id, `updated_at`) in process, and returns `PENDING_EXPORT` when the export is older than call end plus 60 minutes. A person currently makes sure only one file is in the folder. Observed in export. |
| KB | One mission (47043) with a daily Power Automate flow (email trigger, Office Scripts, Excel index workbook with `Matcha_Index` and `DeltaActions` tables, sequential Upload / Replace / Delete loop against the legacy file API). The mission now hits the 200-files-per-mission cap. Observed in export. |
| Matcha platform | Two API surfaces and two environments that are **not synced** (see section 4). |

### Gaps that block the split (highest impact first)

1. **Transcription contract mismatch.** Downstream steps need speaker-labelled lines, Genesys hold events, caller-requested pauses and agent identity. Azure `/transcribe` returns an unlabelled transcript and gap-based holds, and downloads one track only.
2. **Synchronous endpoints.** Ingress allows roughly four minutes per request; a long call transcription can exceed that.
3. **Canonical PHI leaves Azure.** `/transcribe` returns the canonical transcript alongside the protected text.
4. **No service-to-service auth.** No endpoint authenticates its caller.
5. **Media download header.** The Azure recorder sends the Genesys bearer header to pre-signed media URIs; the legacy downloader deliberately sends none. Likely to fail and would leak the token to a third-party host. **Verify** against a live recording.
6. **State and storage.** Blob and S3 providers raise `NotImplementedError`; the Whisper cache is not on a persistent volume; scale-to-zero means a cold model load.
7. **Matcha edge blocks default User-Agents.** Calls from Python's default client get 403; a browser-style User-Agent gets 200. Tested.
8. **Secrets in exports.** The production legacy key is hard-coded in the KB flow definition.

## 2. Target architecture

```
 ServiceNow --(hourly report email)--> Power Automate: SNOW export flow
                                          | PUT in place, one permanent file
 KB source --(daily email)-----------> Power Automate: KB sync flow (per-client shards)
                                          |
   +--------------------------- Matcha (legacy env today) -----------------------+
   |  Mission Storage: SNOW folder (1 file) | KB shards (about 12 missions)       |
   |  Dispatcher -> Audit flow -> SNOW Mission -> Ticket gate                    |
   |  KB router -> KB Mission (2-stage) -> Payload builder -> CEQ Mission         |
   |  Result parser -> report/email/row ; Mission Caller (PHI gate, model chain)  |
   +-------^----------------------------------------------------------^----------+
           | read-only list + download (browser User-Agent)             | HTTPS, LLM-safe JSON
           |                                                            v
   +------------------------------- Azure --------------------------------------+
   |  Interaction Job API (async): Genesys download (all tracks) -> ffprobe       |
   |    -> Whisper -> speaker/hold signals -> fingerprint (raw, in Azure only)     |
   |    -> SNOW pre-match (cache, scoring) -> PHI v2 sanitize (Presidio + SLM)     |
   |  Evidence archive (Blob, retention) ; purge ; Key Vault ; App Insights        |
   +------------------------------------------------------------------------------+
```

Principle: **Matcha decides, Azure processes.** Azure holds no authoritative SNOW or KB data, never calls a Mission, and holds only a short-lived derived cache of the SNOW export (decision D12, needs approval).

## 3. Answers to the review questions

**Is the expected flow correct?** Directionally yes, with changes:

1. Merge `/recording/download` and `/transcribe` into one async Azure job. Audio never travels through Matcha.
2. SNOW pre-match moves to Azure. It needs raw caller identity, which exists only in Azure, and raw ticket rows, which Azure reads from the Matcha folder. Only sanitized top candidates return to Matcha.
3. The three Mission steps stay in Matcha, wrapped by the existing deterministic code (ticket gate, KB policy, payload builder, result parser).
4. `/generate-report` becomes an evidence-archive call; the reviewer report stays the MatchaOS-hosted HTML.
5. Add purge and acknowledgement steps.

**Should workflow stay in Azure?** No. Retire `AuditWorkflowService` as orchestrator.

**Should workflow move to FlowBuilder?** Possibly. The new API documents flow runs (start, run-and-wait up to 90 seconds, poll), which answers part of the earlier doubt. Still to verify: HTTP steps with header secrets, polling loops and branches, and that runs are not tied to a personal account (only the flow's owner can run it). If these fail, the existing MDS (Langflow) flow remains the orchestrator and the design is unchanged.

**PHI location.** Azure remains the place for audio-derived text and now also for raw ticket rows during pre-match. Azure returns only the sanitized projection. The Matcha Mission Caller still gates ticket and KB text with the same policy version (defence in depth). See `PHI_POLICY_V2.md`.

**Where does the SLM go?** The first set retired the local SLM. That is reversed: a small CPU classifier decides patient versus workforce for ambiguous names, alongside Presidio and regex, inside Azure.

**Ticket matching, KB lookup, CEQ audit.** Ticket pre-match computation moves to Azure; the SNOW Mission, ticket gate, KB Missions and CEQ Mission stay in Matcha.

## 4. Platform facts that shape the design

| Fact | Status |
|---|---|
| Legacy API has file endpoints (list, download, upload, in-place replace, delete). MatchaOS has tested folder/file create, list, upload, and delete routes; MatchaOS download/replacement behavior remains untested. | Tested |
| `mk_live_` keys work only on the legacy host; `mos_sk_live_` keys work only on the new host. | Tested |
| The new environment is not synced with the legacy one: a mission folder created there is empty and has no integer IDs. Prompts did migrate (the new SNOW mission answered with the ticket-match JSON). | Tested (user report plus one completion) |
| New key limit: 120 requests per minute, consistent with a fixed 60-second window anchored on the first request. Daily limit unknown. | Tested |
| Legacy documented limits: 500 per minute and 2,000 per day per key owner. Your actual limits not yet read. | Documented |
| Matcha edge returns 403 to default client User-Agents. | Tested (container to legacy host) |

Consequence: until Matcha confirms file endpoints in the new API (or a sync), the file layer and the missions that read those files stay on the legacy environment. Host, IDs and key are configuration in every flow and in Azure so the move later is a settings change.

## 5. Services by disposition

| Disposition | Services |
|---|---|
| Keep in Azure | Recording, transcription (extended), PHI protection v2 (Presidio, SLM, regex), artifact store (implement Blob), job runner, **SNOW pre-match service (new)** |
| Internal API only (behind auth) | `/jobs/*`, `/snow/*`, `/evidence/*`, `/health/*` |
| Retire from runtime | `AuditWorkflowService`, `DispatcherService`, `services/matching.py` and `/ticket-match`, `KnowledgeService` providers, Azure `ReportService` as reviewer report |
| Reuse as the base of new work | `ticket_matching_service` (starting point for the Azure scorer), `ticket_policy_service`, `AuditService` and KB policy (parity oracles), `LocalSLMDetector` (starting point for the PHI classifier) |
| Becomes Mission | None. |

## 6. Migration recommendations (ordered)

1. Security first: rotate keys, remove secrets from exports, add auth to the Azure API (Phase 0).
2. Hourly SNOW export flow replacing one file in place (Phase 1).
3. KB sync hardening and per-client shards (Phase 2).
4. Azure pre-match service in shadow mode (Phase 3), then PHI v2 (Phase 4), then KB lookup v2 (Phase 5).
5. Async job API, transcription contract v1, projection-only responses, one consolidated Mission Caller.
6. Optional MCP tools for analysts (Phase 6); cutover and retirement (Phase 7).
7. Fix infra drift: Bicep enables the ACR admin user while the script uses managed identity; align to managed identity.

## 7. Final recommendation

Keep Matcha as the intelligence and orchestration layer, with deterministic guardrails beside the Missions and their data. Use Azure as an authenticated, asynchronous media, matching and PHI processor with durable evidence storage and a short-lived SNOW cache. Do not build a second orchestrator, scorer or KB client in Azure. Keep every environment-specific value (host, IDs, keys) in configuration so the legacy-to-new migration is a settings change.
