# IMPLEMENTATION_PLAN (v2, 2026-11-01)

Scope: Matcha stays the intelligence layer; Azure is compute, cache and PHI processing; Matcha Mission Storage stays the only authoritative copy of SNOW and KB data. Labels: Tested, Documented, Proposed, Unknown. Test evidence is in `MATCHA_API_TEST_REPORT.md`.

## 1. Starting facts

| Fact | Status |
|---|---|
| Legacy file API works with an `mk_live_` key: list, download, upload, in-place replace, delete. | Tested |
| It works from a PC, Azure Cloud Shell and inside `ca-ceq-dev-api`. Python's default User-Agent gets 403; a browser-style one gets 200. | Tested |
| In-place replace keeps file ID and filename; new content is downloadable at the first probe; `updated_at` changes up to three times in about 20 seconds, then settles. | Tested |
| The new MatchaOS API has no file endpoints; `mk_live_` and `mos_sk_live_` keys do not cross over. | Tested |
| New key limit 120 per minute (fixed window consistent); daily limit unknown. Legacy documented 500 per minute and 2,000 per day. | Tested / Documented |
| Legacy and new environments are not synced. Prompts exist in the new environment; files do not. | Tested / reported |
| Container Apps outbound addresses are a shared pool of about 300; the key had no IP restriction. | Tested |

## 2. Decisions

See the decision log in `00_INDEX.md` (D1 to D12). D12 (Azure derived cache of the SNOW export) needs your approval before Phase 3 goes live.

## 3. Phases

### Phase 0: Security and hygiene (first)
- Rotate the production `mk_live_` key (hard-coded in the KB flow, pasted into chat) and delete all test keys (inventory in `SECURITY_OPERATIONS_AND_OPEN_ITEMS.md`). Rotation revokes the old key immediately: do it right after a KB sync run, then update every HTTP action and the Azure secret.
- Move keys out of flow definitions into secure inputs or Key Vault; Azure reads Key Vault by managed identity.
- Request a business-unit or service key for the pipeline and raise the daily limit.
- Add authentication to the Azure API.
- Put host, IDs and key behind configuration in every flow and in Azure (the migration switch).
- **Exit:** no secret in any flow export; pipeline key is not tied to a personal account.

### Phase 1: Hourly SNOW export flow (Power Automate)
Spec: `SNOW_EXPORT_FLOW_SPEC.md`. One permanent file, replaced in place; validate before replace; retries and alerts; settle wait; Azure refresh call; 72-hour window.
- **Exit:** 24 consecutive successful hourly replacements; exactly one file in the folder; export age alert tested.

### Phase 2: KB sync hardening and per-client shards
Spec: `KB_SYNC_AND_SHARDING_SPEC.md`. Fix the sync defects, add the client map, create about 12 shard missions with prompts from one master template, backfill in batches.
- **Exit:** every shard under 180 files; delta run idempotent; failed items retried the next day; old mission 47043 untouched until Phase 5 parity.

### Phase 3: Azure job API baseline and SNOW pre-match service
Spec: `AZURE_PREMATCH_SERVICE_SPEC.md`, boundary in `MATCHA_AZURE_BOUNDARY.md`.
- Async job API, transcription contract v2, projection-only responses, service authentication.
- Pre-match: cache, validation, scoring, sanitizing, refresh push, status endpoint.
- **Shadow mode:** run beside the Matcha component for every audit; log both; review every disagreement. Switch values: `matcha`, `shadow`, `azure`.
- **Cutover gate (Proposed):** no regression on a labelled set; every disagreement explained; zero PHI in sampled candidate payloads; rollback switch tested. The Matcha component stays deployed until the gate passes and for an agreed period after.
- **Parallel track 3b:** ASR bake-off (`ASR_MODEL_EVALUATION.md`) behind an adapter, so the model can change without touching the job contract.

### Phase 4: PHI policy v2 (role-aware)
Spec: `PHI_POLICY_V2.md`. Clinicians and staff are not PHI; caller identity lane before redaction; typed placeholders and flags.
- **Exit:** labelled corpus built; PHI recall and caller-name retention measured per entity type; targets signed off by the policy owner.

### Phase 5: KB lookup v2
Spec: `KB_LOOKUP_V2_SPEC.md`. Router, two-stage search, cited-ID validation, code-side confidence, evaluation set.
- **Exit:** hit rate at least equal to mission 47043 on the evaluation set; zero cross-client citations.

### Phase 6: MCP tools (optional)
Read-only tools for analysts and the Teams bot (`kb_search`, `kb_get_article`, `snow_find_ticket`, `ceq_audit`). Writes need approval. The batch pipeline never calls MCP.

### Phase 7: Cutover and retirement
Retire the Matcha pre-match component after the gate; retire the Azure workflow, dispatcher, matcher and knowledge providers per the ownership matrix. Retire mission 47043 after Phase 5.

### Phase 8: Container release
Spec: `DOCKER_PACKAGING_AND_PORTABILITY.md`. A portable image built last, from the finished service, with a documented list of prerequisites (network, secrets, volumes, configuration) and a preflight check. Requirements are tracked from Phase 3 so nothing is hard-coded to Azure.
- **Exit:** the image starts on a clean host using only its documented prerequisites; preflight passes; a replay of a synthetic call completes end to end.

## 4. Request budget (planning figures, not measured)

Per audit: SNOW Mission 1, KB lookup 2 to 3 (search, read, sometimes one extra query), CEQ Mission 1: about 4 to 5 calls, plus retries. Fixed daily load: 24 SNOW replacements, about 48 Azure refresh reads, about 48 backup checks, KB sync delta about 50: about 170 per day.

| Key | Limit | Planning ceiling |
|---|---|---|
| Legacy `mk_live_` | 500/min, 2,000/day (documented, shared per key owner) | About 350 audits a day at 5 calls; about 100 audits a minute at 5 calls |
| New `mos_sk_live_` | 120/min tested, daily unknown | About 24 audits a minute at 5 calls |

The KB backfill (about 917 uploads) uses nearly half a legacy day: run it in batches of at most 300 a day or use a business-unit key. Every caller runs a client-side limiter below the limit and honours `retry-after` on 429.

## 5. Risks

See the risk register in `SECURITY_OPERATIONS_AND_OPEN_ITEMS.md`. The top three: the legacy environment retiring before file endpoints exist in the new API; PHI recall below the policy target; the Matcha edge blocking Azure traffic.

## 6. Open items

The numbered list, owners and blocking status are in `SECURITY_OPERATIONS_AND_OPEN_ITEMS.md`, section 7.
