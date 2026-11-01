# CEQ v3 Porting Map

Evidence labels in this document follow the programme documents: **Tested**, **Observed in export**, **Documented**, **Proposed**, or **Unknown**.

## 1. Baseline test suite

Existing behaviour is the baseline, per [.github/copilot-instructions.md](../../.github/copilot-instructions.md) and [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) section 3.

- Exact command: `pytest -q tests`
- Result: **168 passed, 1 skipped**, exit code 0
- Warning: 1 Starlette `DeprecationWarning`
- Suite time: 10.16 seconds reported by pytest
- Stopwatch wall time: 11.82 seconds
- Skip: `tests/unit/test_audio_validation.py:121`, because Windows rejected creation of a symlink for lack of privilege (`WinError 1314`)

The exact recommended command is also in [docs/TESTING.md](../TESTING.md): `pytest -q tests`.

### 1.1 Revised specification reconciliation

Four downloaded revisions were compared with the repository specifications. They add the following constraints; repository source documents remain unchanged until the owner explicitly approves them.

| Downloaded revision | Addition affecting this map | Status |
|---|---|---|
| `IMPLEMENTATION_PLAN_1.md` | Phase 1 has a concrete layout: new Power Automate flow under `flows/power-automate/snow-export/`, an Office Script TypeScript production validator, and a mirrored Python rules test under `tests/`. It also requires the dispatcher cleanup behavior for superseded or failed exports to be disabled for the SNOW folder before go-live, and confirms that components need different configured folder values reconciled. | **Observed in downloaded revision; not yet copied into repository spec** |
| `PHI_POLICY_V2_2.md` | Adds self-reported SLM confidence as poorly calibrated; confidence must be calibrated on a labelled corpus or derived from token probabilities/agreement. It adds Ollama runtime analysis, fail-safe behavior, constrained output, policy versioning, and explicit gaps in the current implementation. | **Observed in downloaded revision; not yet copied into repository spec** |
| `SECURITY_OPERATIONS_AND_OPEN_ITEMS_2.md` | Adds Phase 1 blocker #17 (dispatcher deletion), Phase 1 blocker #18 (authoritative folder), Phase 4/packaging blocker #19 (whether Ollama/SLM runs in production), and Phase 0 history-scan correction #20. It replaces the proposed working-tree/history commands with gitleaks and pickaxe scans. | **Observed in downloaded revision; not yet copied into repository spec** |
| `DOCKER_PACKAGING_AND_PORTABILITY_1.md` | Clarifies that model weights and certificates must be baked in and that the PHI row must decide between an embedded inference runtime and a sidecar. The container size constraint also requires measuring the combined ASR and PHI memory peak. | **Observed in downloaded revision; not yet copied into repository spec** |

## 2. Module and file-group porting map

| Module or file group | Current implementation | Specification section | Decision | Reason | Parity test |
|---|---|---|---|---|---|
| `api/main.py`; FastAPI routes and startup | HTTP endpoints for auth, recording download, transcription, ticket matching, KB search, audit and HTML report generation; health/live/ready routes; no endpoint authentication in route definitions | [HYBRID_ARCHITECTURE.md](HYBRID_ARCHITECTURE.md) section 1 gap 4; section 3 | ADAPT | Azure retains the compute API, but the target needs service-to-service auth and an async job contract; direct orchestration endpoints are not the final boundary | Add authenticated route and job-contract tests; retain synthetic `/health`, auth, download, transcribe, match, KB and audit response contract tests |
| `services/recording.py`; `services/genesys_auth.py`; Genesys components | Download/authentication and recording metadata support, with caching and token handling; legacy Matcha component has single-track/downloader paths | Ownership matrix: Genesys recording download and metadata | ADAPT | The capability belongs in Azure, but the target must merge all-track download, metadata, hold alignment and auth into one job | Download/metadata tests for both tracks; bearer-header isolation test; verify live recording failure against pre-signed URIs |
| `services/transcription.py`; `components/CALL AUDITS/v2/modules/*`; legacy `service_desk_qa_transcriber.py` | Two transcription stacks: faster-whisper large-v3-turbo plus a v2 decomposition; Azure returns canonical segments and projected segments, hold signals and metrics; Matcha transcriber has richer speaker/hold behavior | Matrix: Whisper, speaker labelling; [HYBRID_ARCHITECTURE.md](HYBRID_ARCHITECTURE.md) sections 1 and 3 | REWRITE | Duplication exists; Azure needs the canonical contract mismatch fixed and a speaker-labelled, hold-aware job contract behind an adapter | Decompose audio into synthetic tracks; prove exact segment labels, hold/dead-air signals, canonical/projection separation and both Whisper/adapter parity |
| `services/fingerprint_service.py`; `components/CALL AUDITS/call_fingerprint__snow_prematch.py` | Python and Langflow fingerprint extraction from names, phones, tickets, issue terms and interaction metadata; Matcha also downloads and scores SNOW rows | Matrix: caller fingerprint extraction; pre-match compute; [AZURE_PREMATCH_SERVICE_SPEC.md](AZURE_PREMATCH_SERVICE_SPEC.md) | ADAPT | Fingerprint calculation belongs in Azure; keep Matcha implementation only as a shadow reference until gate | Synthetic fingerprint corpus: name, extension, phone, ticket number, agent, time and issue terms produce identical caller data and search window |
| `services/phi_protection.py`; `components/CALL AUDITS/v2/modules/phi_protection.py` | Two regex-driven engines; the v2 engine optionally adds `LocalSLMDetector`; strict and audit/LLM modes differ; canonical text is also returned by transcription | Matrix: PHI protection v2; [PHI_POLICY_V2.md](PHI_POLICY_V2.md) section 4 | ADAPT | Keep regex plus local SLM plus Presidio/role-aware pipeline in Azure, but replace the current no-role/unified thresholds with a policy-versioned implementation | Labelled PHI/caller-name corpus; per-entity recall, caller-name retention, strict fail-safe and projection-only response tests |
| `services/matching.py`; `services/ticket_matching_service.py` | Two naive/deterministic ticket matchers: SequenceMatcher plus a scored exporter parser; the Matcha component has separate duplicate logic and caches exports in process | Matrix: SNOW pre-match compute; ticket matching API and Ticket matching must retire | REWRITE | The target score/pre-match engine belongs in Azure with raw rows and raw fingerprint, while Matcha keeps only the ticket gate and Mission confirmation | Labelled call-to-ticket corpus; compare status, rank, confidence, top three, raw-vs-sanitized fields and shadow disagreement |
| `components/CALL AUDITS/snow_ticket_finder.py`; `components/CALL AUDITS/ticket_gate__kb_query.py`; Matcha ticket gate | Calls the SNOW Mission, verifies candidates and controls downstream KB query; some PHI/circuit-copy behavior | Matrix: SNOW ticket gate and SNOW Mission; ownership transfer of compute, not judgment | ADAPT | Ticket confirmation and override logic stay in Matcha, but must consume Azure candidates and defence-in-depth projection | Synthetic candidate packets and Mission responses; prove no candidate outside code set, freshness hold, rerun and gate override parity |
| `services/knowledge.py`; `providers/knowledge.py`; `components/CALL AUDITS/kb_lookup.py` | Backward-ranked in-memory search, provider abstractions for Matcha/ServiceNow/Azure AI Search, and a Matcha Langflow KB Mission caller | Matrix: KB router, query builder, two-stage lookup; providers row says retire | REWRITE | Current providers do not implement target per-client sharding/two-stage lookup; Matcha owns the target routing and lookup. `flows/power-automate/kb-sync/client-map.json` now supplies a Proposed route/cap template, but production IDs remain unset | Alias-table client routing, search-then-read article-ID validation, zero cross-client citations, promoted-citation policy and confidence parity |
| `components/CALL AUDITS/ceq_auditor.py`; `components/CALL AUDITS/audit_payload_builder.py`; `services/audit.py` | Matcha CEQ Mission payload/result code and a deterministic Azure audit score service | Matrix: CEQ payload builder, CEQ Mission and score math | ADAPT | Mission judgment stays in Matcha; one score/parser implementation must remain after parity testing | Replay Mission JSON against parser and score matrix; critical-fail, incomplete, pass-threshold, manager-review and `award_na` cases |
| `components/CALL AUDITS/audit_result_parser.py`; `components/EMAIL AUDITS/audit_result_parser.py` | Two parsers produce call and email review packages; documented drift is possible because they are separate implementations | Matrix: result/score parser; [HYBRID_ARCHITECTURE.md](HYBRID_ARCHITECTURE.md) section 1 duplication | ADAPT | Reviewer-facing Matcha report stays; parser behavior should converge for parity and channel-specific formatting | Shared fixture suite for CALL and EMAIL JSON, malformed/missing fields, dashboard row and review HTML |
| `services/audit_workflow.py` | State dict, recording download, transcription, matching, KB, audit and report assembly; never calls a Mission | Matrix: workflow orchestration | RETIRE | It is explicitly an Azure evidence assembler, not a Mission orchestrator, and the target puts workflow orchestration in Matcha/FlowBuilder | Shadow-record a synthetic end-to-end chain and compare run states/artifacts; replacement must pass parity before removal |
| `services/dispatcher.py`; `components/CEQ DISPATCHER/new_calls_dispatcher.py` | Python dispatcher has in-memory/durable-contract abstraction; Langflow dispatcher has SNOW freshness gates, roster caps, hold and cleanup logic | Matrix: dispatcher, roster, caps, SNOW-freshness hold | ADAPT | Dispatcher ownership moves to Matcha, but keep its current evidence/freshness behavior during migration | Roster/cap, inbound-only, hold, stale, graceful recover, ticket-grace and no-duplicate dispatch tests |
| `components/CALL AUDITS/html_report_download.py`; `services/report.py`; reviewer HTML | Current Matcha report downloader and Azure `/generate-report` HTML/JSON pre-report generation | Matrix: reviewer HTML report kept; Azure `/generate-report` retire; evidence archive owner Azure | RETIRE | Keep Matcha-login reviewer report; archive generated evidence in Azure rather than returning `<pre>` JSON | Generated report render test, HTML escaping, UUID/filename validation, download-link/auth and evidence-archive metadata parity |
| `services/artifact_store.py`; `modules/storage.py`; `providers/artifact.py` | Local artifact provider is implemented; Azure Blob and S3 providers raise `NotImplementedError`; report artifacts can be saved locally | Matrix: evidence archive and artifact storage | REWRITE | Target Blob evidence archive with lifecycle/purge is a core Azure capability | Blob/S3 contract mocks or emulator: save/read/exists/delete/list/download-link/retention/purge and no content in logs |
| `modules/config.py`; `modules/constants.py`; environment files | Settings and constants read environment/config values for API, PHI, transcription and artifact behavior | Matrix: host, IDs and keys configuration; D4 and D11 | ADAPT | Configuration separation is correct but every Matcha/Azure path and migration switch must use it consistently | Environment-matrix startup test for legacy/new hosts, integer/UUID IDs, missing secrets and migration-switch values |
| `providers/knowledge.py` Matcha/ServiceNow/AI Search classes | Concrete HTTP provider adapters and keyword/article confidence logic | Matrix: Knowledge providers | RETIRE | No KB API exists in the target path; replace with sharded Mission storage/router and two-stage lookup | Zero live-KB provider calls after replacement; old provider response parity until the new gate |
| `infra/main.bicep`; `infra/modules/*.bicep`; `.github/workflows/*`; `docker/*`; `scripts/deploy-azure.ps1` | Azure Container Apps, ACR, environment/app deployment and CI/release configuration; external ingress; Docker packaging | Matrix: secrets, portable container, observability, Azure compute | ADAPT | Preserve deployment, then add auth, fixed secret paths, identity, model/cache prerequisites and preflight before Phase 8 | Infrastructure render/build/apply test; unauthenticated route rejection; Key Vault identity; Docker clean-host synthetic replay and health/preflight |
| `flows/CALL AUDITS.json`; `flows/CEQ DISPATCHER.json`; `flows/EMAIL AUDITS.json`; `flows/README.md` | Exported Langflow/MDS Studio components and dispatcher/audit/email orchestration; Matcha file and Mission HTTP actions | Matrix: workflow, SNOW/KB flows and secret hygiene; D9 | ADAPT | Existing flows are the working orchestration baseline, but exports must contain no secrets and the target adds PA SNOW/KB flows | Flow export smoke plus synthetic Mission/file calls; no secrets, User-Agent browser style, legacy/new environment routing and retry-after tests |
| `components/EMAIL AUDITS/*` | Email ingestion, prompt, parser, KB query and dashboard package support | Matrix: workflow/review queues; PHONE/call ownership | ADAPT | Email remains an audit channel while shared result/score and workflow components are reconciled | Synthetic email fixture test for parsing, KB query, audit payload, recipient subject and dashboard-row parity |
| `components/CALL AUDITS/postaudit_purge.py`; purge components/services | Deletes local recording/report artifacts and purge artifacts after audit | Matrix: post-audit purge | ADAPT | Purge must remain acknowledged across Azure audio/cache/evidence and Matcha run messages | Synthetic purge test for recording, cache, report/run messages and acknowledgement; verify no recipient content is logged |
| `components/CALL AUDITS/mission_cost_summary.py` | Summarizes Mission cost and usage logs | Matrix: observability/routing/cost | ADAPT | Cost and routing telemetry stay in Matcha governance; require shared correlation ID | Synthetic run/cost fixture; aggregate counts and costs without ticket/transcript/customer/agent names |
| Tests: `tests/unit/test_*.py` | 168 passing unit tests and one skipped symlink test | Baseline section 1; `docs/TESTING.md` coverage gaps | KEEP / ADAPT | Preserve this suite and add contract, integration, security, parity and synthetic-PHI coverage before replacements | Existing suite remains green; new shadow/parity, auth, export freshness, projection and artifact tests must pass |

### Current disagreement register

1. **No service authentication.** HYBRID_ARCHITECTURE section 1 says external ingress lacks service-to-service authentication; [api/main.py](../../api/main.py#L134-L150) exposes health and data routes with no auth. Implementation Plan Phase 0 requires authentication.
2. **Readiness is not a readiness check.** HYBRID_ARCHITECTURE section 1 records “`/health/ready` always returns ready”; [api/main.py](../../api/main.py#L144-L146) implements exactly that static response.
3. **Azure workflow orchestrates code but not Missions.** HYBRID_ARCHITECTURE section 1 explicitly says `AuditWorkflowService` never calls Missions; [services/audit_workflow.py](../../services/audit_workflow.py#L64-L114) still assembles services into a local run state and keeps `_runs`/`_attempts` dictionaries in memory.
4. **Azure dispatcher is not SNOW-freshness authoritative.** HYBRID_ARCHITECTURE section 1 says the Azure dispatcher has no SNOW-freshness gate; the [Python dispatcher](../../services/dispatcher.py#L15-L38) has no export freshness input, while the [Matcha dispatcher](../../components/CEQ%20DISPATCHER/new_calls_dispatcher.py#L698-L716) does carry freshness/hold settings.
5. **Azure stores canonical and protected transcription together.** HYBRID_ARCHITECTURE gap 3 says canonical PHI must not leave Azure and PHI projection is required; [services/transcription.py](../../services/transcription.py#L123-L158) returns `transcript`, `segments`, `protected_text`, and `protected_segments` together.
6. **Token/header is a live recording risk.** HYBRID_ARCHITECTURE gap 5 says the recorder might send bearer credentials to a pre-signed URI and requires verification; [services/recording.py](../../services/recording.py#L100-L128) and recording component code must remain under the live verification test.
7. **Blob and S3 are unimplemented.** HYBRID_ARCHITECTURE gap 6 says Blob/S3 providers are incomplete; [providers/artifact.py](../../providers/artifact.py#L224-L276) raises `NotImplementedError`.
8. **Two main ticket matchers remain.** HYBRID_ARCHITECTURE section 1 identifies duplicate naive and ported matchers; [services/matching.py](../../services/matching.py#L11-L39) and [services/ticket_matching_service.py](../../services/ticket_matching_service.py#L78-L138) retain separate implementations.
9. **Two PHI engines and a third component regex set exist.** HYBRID_ARCHITECTURE section 1 says this duplication remains; both [services/phi_protection.py](../../services/phi_protection.py#L11-L97) and [v2 phi_protection.py](../../components/CALL%20AUDITS/v2/modules/phi_protection.py#L66-L204) implement overlapping regex/SLM behavior, while the strict redactor adds a separate caller/operational regex set.
10. **Transcription contract mismatch.** HYBRID_ARCHITECTURE gap 1 requires speaker labels, hold/dead-air and all-track metadata; the Azure [transcription service](../../services/transcription.py#L100-L158) is segment-based without a single async job contract, and the result still includes canonical text.
11. **Three copies of caller/Mission patterns still exist.** HYBRID_ARCHITECTURE section 1 documents three identical copies; `components/CALL AUDITS/{snow_ticket_finder.py,kb_lookup.py}` and `components/CALL AUDITS/ceq_auditor.py` retain separate wrappers and circuit logic.
12. **Knowledge providers are still Azure code.** The mission ownership matrix says knowledge providers are to retire from Azure, but [providers/knowledge.py](../../providers/knowledge.py#L18-L154) and [services/knowledge.py](../../services/knowledge.py#L20-L128) still implement Matcha, ServiceNow and AI Search provider paths.
13. **Azure `/generate-report` remains a review path.** HYBRID_ARCHITECTURE section 3 says it must become evidence archive, and the ownership matrix says `[pre]` JSON dump is to retire; [api/main.py](../../api/main.py#L232-L236) and [services/report.py](../../services/report.py#L10-L30) still generate a stored HTML report directly.
14. **SNOW folder IDs and Mission IDs are configuration in some components, but duplicates are hard-coded.** D4 and the ownership matrix require configuration, never constants. The [Matcha pre-match component](../../components/CALL%20AUDITS/call_fingerprint__snow_prematch.py#L547-L550) uses `50641`/`31790` as UI defaults, while the [dispatcher](../../components/CEQ%20DISPATCHER/new_calls_dispatcher.py#L705-L716) uses `31536` and separate freshness values.
15. **SNOW production still has rolling cleanup behavior in the code while v3 requires one permanent file.** HYBRID_ARCHITECTURE section 1 describes cleanup and a person keeping one file; [new_calls_dispatcher.py](../../components/CEQ%20DISPATCHER/new_calls_dispatcher.py#L405-L417) can delete superseded/failed exports, contrary to the one-permanent-file replacement design until the PA flow replacement is established.
16. **Flow exports carry secret prompts and secret-bearing HTTP patterns.** HYBRID_ARCHITECTURE gap 8 says the production key is in flow exports; security operations documents the key in three KB HTTP actions. The working exports still contain token/client-secret/auth header fields and secret inputs; actual values were not duplicated here.
17. **The Matcha dispatcher defaults differ from the security-SNOW design.** It can hold/override stale exports after configurable hours; Phase 1 has to validate a 72-hour window and one-file freshness, which is not yet recorded in a programmatic export-flow test.

## 3. PHI behavior today

### 3.1 `LocalSLMDetector`

Implementation: [components/CALL AUDITS/v2/modules/phi_protection.py](../../components/CALL%20AUDITS/v2/modules/phi_protection.py#L102-L204).

- Supported models: `gemma3`, `qwen3`, `mistral-small`, and `llama3.2`; the default service model is `llama3.2`.
- Endpoint: `http://127.0.0.1:11434`; timeout: 30 seconds.
- Prompt asks for JSON-only span objects containing `category`, `text`, and exact character `offset`.
- Accepted categories: `MRN`, `FIN`, `ENCOUNTER`, `DOB`, `SSN`, `INSURANCE_ID`, `PATIENT_ACCOUNT`, `DIAGNOSIS`, `MEDICATION`, and `PATIENT_IDENTIFIER`.
- No numeric confidence is requested or parsed, no fixed threshold is applied, and the output is validated only by enum/category, exact source-text span, offsets and exclusion rules.
- Malformed/non-list/non-JSON model output is ignored. Service/network/timeout errors raise an unavailable error rather than returning a finding.
- Alias values are accepted for encounter/insurance/member/patient-name/clinical-detail names.
- Phone-like spans are discarded.
- Spans containing or immediately preceded by ticket, INC, KB, employee, extension, SNOW, ServiceNow, phone, email, caller, or agent operational context are discarded.
- A `patient_identifier` is accepted only when the preceding 30 characters end in a patient-name cue (`patient name`, `patient's name`, `patient named`, `patient is`, or a patient colon marker).
- Titles such as Dr, RN, charge nurse, clinician and nurse are not explicitly modeled or checked. There is no workforce title detector.
- A caller is not labelled by the SLM. The caller/agent exclusion logic prevents some SLM spans near `caller` or `agent` context from being returned, but the code has no title-aware caller lane or caller-identity extraction.
- In the strict v2 redactor, a caller/agent/patient phrase followed by a capitalized name is added as a redaction pattern; this can redact workforce-style names. [phi_protection.py](../../components/CALL%20AUDITS/v2/modules/phi_protection.py#L286-L320).

### 3.2 Regex engines

Core engine [services/phi_protection.py](../../services/phi_protection.py#L11-L97) patterns:

- SSN, patient/MRN/member identifiers, patient/billing/hospital/guarantor accounts, FIN/encounter/admission/visit/health-plan/member/insurance IDs, DOB, patient-name forms, and broad clinical-detail keywords/sentence windows.
- It has `OFF`, `AUDIT_MODE`, `LLM_MODE`, and `STRICT` modes.
- `OFF` returns no projection changes; `AUDIT_MODE` reports findings but leaves text unchanged; `LLM_MODE` replaces findings with typed PHI markers; `STRICT` blocks when any finding exists.
- No Presidio integration exists in this engine.

V2 regex engine [components/CALL AUDITS/v2/modules/phi_protection.py](../../components/CALL%20AUDITS/v2/modules/phi_protection.py#L66-L100):

- SSN, DOB, MRN, FIN, encounter/admission/visit, insurance/member/subscriber/policy, patient/billing/hospital/guarantor accounts, patient names, diagnosis, and medication references.
- It merges overlapping regex/SLM findings, prefers earliest then longest spans.
- It returns typed markers in non-strict mode; strict mode additionally redacts `agent`, `caller`, and `patient` names, phone numbers, and ticket/INC/KB/employee/extension/SNOW/ServiceNow identifiers. It therefore can redact operational/caller material in strict mode.

**Policy-v2 differences**

- Policy v2 section 1 says a title is never a trigger; current code has no title handling and strict mode can redact names after caller/agent/patient labels.
- Policy v2 section 2 keeps caller, requester, contact, agent and workforce phone/extension/department values; current strict mode redacts phone-like numbers and caller/agent names, and the default regex engine lacks a workforce/requester field lane.
- Policy section 4.2 allows fixed SLM labels with confidence and evidence; current SLM output has no allowed confidence field or evidence list and no confidence threshold.
- Policy section 4.3 says workforce removal requires a workforce/caller field, confidence above threshold, and no regex identifier; current code has no confidence or role source metadata and applies no proximity/asymmetry decision engine.
- Policy section 4.4 requires untrusted input schema handling/no tools/no memory; current LocalSLM sends source text with no field/track metadata and discards malformed output, but it does not implement the policy fixed response schema with evidence.
- Policy section 4.5 specifies versioned model/prompt/checksum and CPU/memory/labelled-bake-off decisions; current code supports a model allowlist but stores no checksum/policy version and has no Presidio stage.
- Policy section 4.6 requires fail-safe redaction of ambiguous spans while retaining workforce identity through a code lane; current SLM unavailable errors interrupt the detector, with no code-side caller lane preserving the identity.
- Policy section 4.7 requires `phi_policy_version` and immutable versions; current findings/outputs do not carry a policy version.
- Policy section 7 targets caller retention and zero SLM patient unredaction; no shipped corpus, measured thresholds or targets exist in code.

## 4. Working-tree secret locations

A value-free scan found hard-coded key inventory references in:

- [SECURITY_OPERATIONS_AND_OPEN_ITEMS.md](SECURITY_OPERATIONS_AND_OPEN_ITEMS.md#L9-L12)

The flow export and source scan found no additional actual secret value under the implemented token/key, credential-URL, bearer-token, AWS access-key and secret-assignment patterns. Individual token names, placeholders, test values and UI “paste token” prompts remain and are not secret values. No matched value is reproduced here.

Exact commands to scan git history without printing matched values, per revised [SECURITY_OPERATIONS_AND_OPEN_ITEMS.md](SECURITY_OPERATIONS_AND_OPEN_ITEMS.md) section 8:

```text
gitleaks detect --source . --log-opts="--all" --redact
gitleaks detect --no-git --source . --redact

git log --all --pickaxe-regex -S"mk_live_[0-9a-fA-F]{20}" --format="%H %ad" --name-only
git log --all --pickaxe-regex -S"mos_sk_live_[A-Za-z0-9_-]{20}" --format="%H %ad" --name-only
```

These commands report commit/path information or redacted findings rather than secret values. Also scan gitleaks for Genesys client secrets, SAS tokens and connection strings, as the revised security section requires. The generic pickaxe loop and a hand-built secret regex are not the approved history-scanning method.

## 5. Proposed Phase 0 and Phase 1 order

### Phase 0: security hygiene

1. Rotation inventory and runbook: rotate the production legacy key, delete exposed test keys, update the key inventory, then replace every HTTP action and Azure secret. Quoted section: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) Phase 0; [SECURITY_OPERATIONS_AND_OPEN_ITEMS.md](SECURITY_OPERATIONS_AND_OPEN_ITEMS.md) sections 1 and 2.
2. Move flow/Azure secrets to Power Automate secure inputs or Key Vault and remove secrets from exports. Quoted section: Implementation Plan Phase 0; Matrix “Secrets” row and D11.
3. Obtain and configure a service/business-unit pipeline key and raised daily limit; add managed-identity Key Vault reads. Quoted section: Implementation Plan Phase 0; D11.
4. Add service-to-service authentication to the Azure API and verify `/health/ready` only after dependencies are real. Quoted section: HYBRID_ARCHITECTURE section 1 gap 4; gap 1 readiness observation.
5. Put host, folder ID, Mission ID and key behind configuration in flows/Azure and remove hard-coded defaults. Quoted section: INDEX D4; Implementation Plan Phase 0.

Files touched first: `flows/*.json`, `infra/main.bicep`, `infra/modules/*.bicep`, `api/main.py`, environment/configuration files, `modules/config.py`, and security/runbook documentation.

Exit criterion: no secret in flow exports; no personal-key dependency; only service-to-service authenticated Azure paths.

### Phase 1: hourly SNOW export flow and validation script

1. Implement the single permanent SNOW export file flow, with Power Automate source report email input and in-place replace by file ID.
2. Validate workbook/header/window before replace; keep old file if validation fails; retry/alert; send browser User-Agent; honor retry-after.
3. Wait for settlement, verify refreshed `updated_at`, then call Azure refresh/status; preserve exactly one file and no cleanup deletes.
4. Add a validation script for header, timestamps, window, file count, freshness and refresh parity.
5. Add stale, replacement-failed, duplicate-file and refresh-mismatch alerts.
6. Run 24 consecutive replacements with manual/automatic validation.

Files touched: `flows/power-automate/snow-export/<flow export>` for the new flow, `flows/power-automate/snow-export/` Office Script TypeScript for production validation, `tests/` for the mirrored Python rules, `docs/ceq-v3/SNOW_EXPORT_FLOW_SPEC.md` for the flow contract, and configuration placeholders in `modules/config.py`/environment files if the Azure refresh endpoint is exercised.

Before go-live, disable Matcha dispatcher cleanup of superseded or failed exports for the SNOW folder. Confirm the actual export folder in the flow exports and Matcha UI and reconcile the current defaults (`31790` and `31536`) before introducing configuration; do not treat a default as production truth. Quoted section: revised [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) Phase 1, revised [SECURITY_OPERATIONS_AND_OPEN_ITEMS.md](SECURITY_OPERATIONS_AND_OPEN_ITEMS.md) section 7 items 17 and 18.

Quoted section: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) Phase 1; [SNOW_EXPORT_FLOW_SPEC.md](SNOW_EXPORT_FLOW_SPEC.md); [HYBRID_ARCHITECTURE.md](HYBRID_ARCHITECTURE.md) section 1 SNOW export and section 2 one-file design.

Exit criterion: 24 consecutive successful hourly replacements; exactly one file; export-age alerts tested; Azure refresh verified.

## 6. Phase 0 and Phase 1 open items requiring approval

Before implementation can be final, I need answers only for section 7 items that block the requested phases:

- **#2 Business-unit/service key: who creates it?** Blocks Phase 0.
- **#5 Confirm the longest expected audit backlog and whether 72 hours is correct.** Blocks Phase 1 window validation.
- **#7 Whether the SNOW Mission search index is used and the effect of re-indexing after every replace.** Blocks Phase 1 refresh behavior and settlement validation.
- **#11 Confirm production folder `31790` and Mission `50641` for the SNOW export.** Blocks Phase 1 target configuration.
- **#17 Confirm when the Matcha dispatcher deletes exports, on which folder, and disable deletion for the permanent SNOW file.** Blocks Phase 1 go-live.
- **#18 Reconcile folder defaults `31790` and `31536` against actual flow exports and Matcha UI configuration.** Blocks Phase 1 target configuration.
