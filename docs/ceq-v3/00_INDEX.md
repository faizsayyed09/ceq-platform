# CEQ Platform v3: Document Set (v2, 2026-11-01)

Scope: Matcha is the Intelligence, Workflow, Mission, Dashboard and Governance layer. Azure is the compute, storage and PHI-processing layer. Power Automate feeds ServiceNow (SNOW) and KB data into Matcha Mission Storage, which stays authoritative. This set supersedes the four documents sent on 2026-10-31 and the plan sent earlier today. Nothing here changes repository files; these are architecture and ownership documents, and the specs describe behaviour, not code.

Evidence labels used everywhere: **Tested** (observed in a live test), **Documented** (in a Matcha API document, not run), **Observed in export** (read from a flow or workbook you supplied), **Proposed** (my recommendation, needs your approval), **Unknown** (needs an answer).

## Reading order

| # | Document | Use it for |
|---|---|---|
| 1 | `00_INDEX.md` | This page: map, decision log, glossary |
| 2 | `HYBRID_ARCHITECTURE.md` | What exists, the target design, the reasoning |
| 3 | `MATCHA_AZURE_BOUNDARY.md` | Contracts, auth, PHI boundary, what may cross |
| 4 | `MISSION_OWNERSHIP_MATRIX.md` | Who owns each capability, now and later |
| 5 | `IMPLEMENTATION_PLAN.md` | Phases, exit criteria, request budget |
| 6 | `MATCHA_API_TEST_REPORT.md` | Every live test, what it proved, how to repeat it |
| 7 | `SNOW_EXPORT_FLOW_SPEC.md` | The hourly Power Automate flow that replaces one file |
| 8 | `KB_SYNC_AND_SHARDING_SPEC.md` | KB sync fixes, per-client missions, 200-file cap |
| 9 | `AZURE_PREMATCH_SERVICE_SPEC.md` | SNOW pre-match in Azure: cache, scoring, shadow mode |
| 10 | `PHI_POLICY_V2.md` | Role-aware PHI rules; clinicians are not PHI |
| 11 | `KB_LOOKUP_V2_SPEC.md` | Two-stage KB lookup, validation, evaluation |
| 12 | `FLOWBUILDER_IMPLEMENTATION_GUIDE.md` | The audit flow step by step, error paths, MCP placement |
| 13 | `SECURITY_OPERATIONS_AND_OPEN_ITEMS.md` | Keys, rotation, migration risk, alerts, runbooks, open items |
| 14 | `ASR_MODEL_EVALUATION.md` | Whether to replace faster-whisper large-v3-turbo; bake-off plan |
| 15 | `DOCKER_PACKAGING_AND_PORTABILITY.md` | Portable image: contents, configuration, network and secret prerequisites, release gate |
| 16 | `../AZURE_MATCHAOS_DEPLOYMENT.md` | Azure resources, Power Automate ingestion, MatchaOS provider settings, and deployment/rollback instructions |

## What changed since the first set

1. SNOW pre-match moves from a Matcha component to an Azure service (Matcha's copy runs in shadow until parity).
2. The SLM is kept, together with Presidio and regex, and PHI rules are now role-aware. The first set had retired the local SLM.
3. One permanent SNOW file, replaced in place every hour. No deletes, no second file.
4. KB lookup is split into per-client missions (about 12) with a code router, because of the 200-files-per-mission cap.
5. KB lookup becomes two-stage, with cited-article validation and confidence computed in code.
6. A portable container image is now a deliverable (Phase 8), and the speech-recognition model is up for evaluation (Parakeet versus Whisper).
7. Live tests changed several assumptions: a browser-style User-Agent is mandatory; MatchaOS now supports tested folder/file create, list, upload, and delete routes; download and replacement remain untested; the new key is limited to 120 requests per minute; the legacy and new environments are not in sync.

## Decision log

| ID | Decision | Status |
|---|---|---|
| D1 | Matcha decides, Azure processes. Azure never calls a Mission and holds no authoritative SNOW or KB data. | Unchanged |
| D2 | SNOW pre-match runs in Azure; the Matcha component runs in shadow, then retires after a gate. | Proposed |
| D3 | One permanent SNOW file replaced in place hourly; rolling 72-hour report window. | Proposed (replace itself Tested) |
| D4 | MatchaOS Mission folders/files use UUID routes for tested create, list, upload, and delete operations. Existing legacy replacement/download migration paths remain separate until MatchaOS replacement/download parity is proven. All host, folder, Mission IDs and keys remain configuration. | Tested/Proposed |
| D5 | Mission calls use the same environment as the files they read. The new environment is not used for the pipeline until it is synced. | Proposed |
| D6 | Keep the SLM plus Presidio plus regex, role-aware; typed placeholders plus flags. | Proposed |
| D7 | KB: about 12 per-client missions, routed in code from the SNOW Company field through an alias table. | Proposed |
| D8 | KB lookup: search with sources, then read the chosen articles in full by file ID; confidence computed in code. | Proposed |
| D9 | MCP only for analyst and agent tools, never inside the batch pipeline. | Unchanged |
| D10 | Shadow mode and a single rollback switch before any cutover. | Proposed |
| D11 | Pipeline uses a business-unit or service key held in Key Vault; no secrets in flow exports. | Proposed |
| D12 | Azure may hold a short-lived, encrypted, derived cache of the SNOW export. | **Needs your approval** (conflicts with "no duplicate SNOW storage") |

## Glossary

- **Legacy Matcha API**: `https://matcha.harriscomputer.com/rest/api/v1`, `mk_live_` keys in the `MATCHA-API-KEY` header, integer IDs, has file endpoints.
- **New MatchaOS API**: `https://matchaos.harriscomputer.com/api`, `mos_sk_live_` keys, UUID IDs, Mission completions and folders/files with tested create, list, upload, and delete routes. Download and replacement remain untested.
- **Shard**: one KB mission holding one client's articles (limit 200 files).
- **Fingerprint**: the identifying facts of an interaction (caller name hint, phones, extension, location hints, issue terms, spoken ticket numbers, agent, times) extracted before redaction and used for matching in code.
- **Projection**: the PHI-safe version of a transcript or ticket that models may see.
- **Coverage window**: the span of ticket activity the SNOW export contains (72 hours back from its generation time).
