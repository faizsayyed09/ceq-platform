# MISSION_OWNERSHIP_MATRIX (v2, 2026-11-01)

Legend: **Owner** = system of record and runtime. **Mirror** = tested reference code kept only for parity tests. **Shadow** = runs beside the current path, results compared, not used for decisions. PA = Power Automate.

| Capability | Azure | Matcha | PA | Reason | Future state |
|---|---|---|---|---|---|
| Genesys recording download (both tracks) | **Owner** | – | – | Binary, large, Azure network need; audio never crosses to Matcha | Single async Azure job |
| Genesys metadata (agents, queues, wrap-up, holds) | **Owner** (per interaction) | Dispatcher polls separately | – | Needed beside audio for hold alignment and speaker mapping | In job result contract |
| Audio validation, FFmpeg | **Owner** | – | – | Container binaries, CPU work | Unchanged |
| Whisper transcription | **Owner** | – | – | Compute heavy | Persistent model volume |
| Speaker labelling, hold and dead-air signals | **Owner** | – | – | Derived from audio channels and Genesys | Emit legacy `Structured Data` contract |
| Caller fingerprint extraction (raw) | **Owner** | – | – | Needs the raw transcript; raw identity must stay in Azure | New, inside the job |
| PHI protection v2 (regex, Presidio, SLM adjudication, role-aware) | **Owner** | Verifies attestation | – | Must precede any Mission call | Versioned policy with golden corpus; staged pipeline in `PHI_POLICY_V2.md` section 4 |
| PHI gate on Mission input (KB text, second line for tickets) | – | **Owner** | – | Defence in depth | One shared Mission Caller |
| Canonical transcript storage | **Owner** (encrypted) | Never receives | – | Limits PHI footprint | Blob with lifecycle policy |
| Evidence archive | **Owner** | – | – | Retention-controlled | Implement Blob provider |
| Reviewer-facing HTML report | – | **Owner** | – | Existing parser output, login-gated | Keep |
| Azure `/generate-report` | Retire from review path | – | – | `<pre>` JSON dump | Fold into evidence archive |
| **SNOW export production** (ServiceNow report) | – | – | Trigger source | ServiceNow scheduled report, 72-hour window, ET | Report owned by ServiceNow admin |
| **SNOW export flow** (validate, replace in place, notify) | – | – | **Owner** | No SNOW API; PA feeds storage | New hourly flow; `SNOW_EXPORT_FLOW_SPEC.md` |
| SNOW export storage (one file) | – | **Owner** | Writes | Mission Storage is authoritative | Single permanent file |
| **SNOW derived cache** | **Owner** (short-lived, encrypted) | – | – | Avoid re-download and re-parse per audit | Needs approval (D12); TTL about 6 h |
| **SNOW pre-match compute** | **Owner** | Shadow, then retire | – | Needs raw identity (Azure) and raw rows (read from Matcha) | Azure service; cutover gate in plan |
| SNOW ticket gate | – | **Owner** | – | Overrides any Mission answer not in the code candidates | Keep; one component |
| SNOW Mission (ticket confirm) | – | **Owner** | – | Intelligence layer | Unchanged; sees sanitized candidates |
| KB sync flow (Office Scripts, index workbook) | – | – | **Owner** | No KB API; PA feeds storage | One parameterized flow over a client map; `KB_SYNC_AND_SHARDING_SPEC.md` |
| KB storage (about 12 shard missions) | – | **Owner** | Writes | 200-file cap per mission | Per-client missions |
| KB router (Company to shard, alias table) | – | **Owner** (code) | Maintains map data | Needs the verified ticket's Company | Alias table under change control |
| KB query builder and two-stage lookup | – | **Owner** | – | Beside the Missions | `KB_LOOKUP_V2_SPEC.md` |
| KB policy (HIGH enforceable, cited promoted) | Mirror | **Owner** | – | Guardrail beside Mission output | One implementation in the payload builder |
| CEQ payload builder | Mirror | **Owner** | – | Combines Matcha-held ticket and KB facts | De-duplicate |
| CEQ Audit Mission | – | **Owner** | – | Maintained intelligence | Unchanged |
| Score math, verdict, manager-review rules | Mirror | **Owner** | – | Deterministic, needs Mission output | One parser, parity-tested against `AuditService` |
| Model routing, retries, circuit breaker, client rate limiter | – | **Owner** | – | Mission governance | One component (three copies today) |
| Prompt management | – | **Owner** | – | Mission lifecycle | Per-client prompts generated from one master template |
| Workflow orchestration | Retire | **Owner** | – | Azure copy never calls Missions | Matcha flow with Azure as HTTP steps |
| Dispatcher, roster, caps, SNOW-freshness hold | Retire | **Owner** | – | Matcha version has the freshness gate | Keep; move off thread-plus-file-lock if possible |
| Background compute and job state | **Owner** | – | – | Durable state, not memory | Queue plus Container Apps job/KEDA |
| Review queues, dashboard, email | – | **Owner** | – | Already produced | Unchanged |
| Post-audit purge | **Owner** (audio, caches) | **Owner** (run messages) | – | Each deletes what it holds | Acknowledged purge |
| Observability | **Owner** (App Insights) | **Owner** (routing log, cost) | Run history | Correlate by `conversation_id` and `run_id` | Shared correlation id |
| Secrets | **Owner** (Key Vault) | **Owner** (secret store) | **Owner** (secure inputs / Key Vault) | Each side holds its own | Rotate; none in exports |
| MCP tools (analyst / agent) | Hosts server if built | Consumers | – | Optional, read-only first | Phase 6; never in the batch pipeline |
| Ticket matching API `services/matching.py` | Retire | – | – | Naive duplicate | Delete after parity |
| Knowledge providers (Matcha/ServiceNow/AI Search) | Retire | – | – | No KB API exists | Delete or archive |
| Legacy-to-new environment migration | – | **Owner** (Matcha team) | Updates HTTP actions | Platform decision | Host, IDs and keys are configuration; see operations doc |
