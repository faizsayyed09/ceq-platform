# SECURITY_OPERATIONS_AND_OPEN_ITEMS (v1, 2026-11-01)

## 1. Key inventory and rotation

Only the leading characters are shown. Every key listed was pasted into a chat or a terminal and must be treated as exposed.

| Key | Type | Where exposed | Action |
|---|---|---|---|
| `mk_live_5e4c…` | Legacy, production | Hard-coded in three KB flow HTTP actions; typed at a container prompt | **Rotate** right after a KB sync run (revoked immediately, no overlap); update the KB flow, the new SNOW flow, Azure and any Langflow component |
| `mk_live_2f92…` | Legacy, test | Pasted in chat | Delete |
| `mos_sk_live_9gEQ…` | New, test | Pasted in chat | Delete |
| `mos_sk_live_EXao…` | New, test | Pasted in a terminal log and chat | Delete |
| First 55-character `mos_sk_` key | New, test | Pasted in chat | Delete |

Local cleanup: in the container run `unset MATCHA_API_KEY; exit`; in PowerShell run `Remove-Item Env:MATCHA_API_KEY, Env:TEST_FOLDER`; clear shell history where a key was typed.

Rules going forward: keys live in Key Vault or Power Automate secure inputs; never in flow exports, repository files or chat; one key per purpose (SNOW flow, KB flow, Azure read-only, Mission calls); pipeline keys belong to a service or business-unit account; rotation runbook below.

## 2. Rotation runbook (legacy key)

1. Create the new key (Matcha user menu, API).
2. Store it in Key Vault and the Power Automate secure input.
3. Wait for the end of a KB sync run and the top of an hourly SNOW replace.
4. Rotate; the old key stops working at once.
5. Run the preflight and one manual SNOW replace and one KB delta.
6. Record the date and the next rotation date.

## 3. Legacy versus new environment

Risk: files and file-reading missions live in the legacy environment; the new environment has no file endpoints and is not synced.

Mitigations in this design: host, folder IDs, mission IDs and keys are configuration in every flow and in Azure; file access and the missions that read the files stay in one environment; the Mission response parser handles both formats; the client map holds both integer and UUID IDs.

Questions for the Matcha team (send now, not blocking):
1. When does the legacy environment retire, and what is the migration path for missions and files?
2. Will the new API get file endpoints (list, download, upload, replace, delete) and folder creation, or will the legacy host stay in sync?
3. What is the window and the daily limit for the 120-request limit, and can a business-unit key have more?
4. Can missions, folders and prompts be created or updated through an API?
5. What is the file cap per mission in the new environment?
6. Are Matcha egress addresses fixed, and does the edge accept service traffic from a fixed Azure address?
7. Does each file replace re-index the file, and is the mission's search index used by the SNOW mission at all?

## 4. Alerts

| Alert | Condition | To |
|---|---|---|
| SNOW export stale | Export age above 2 hours | Operator, ServiceNow admin |
| SNOW replace failed | Flow run failed after retries | Operator |
| More than one file in the SNOW folder | Listing shows two or more | Operator |
| Refresh mismatch | Azure rows differ from the flow's | Operator |
| KB shard near cap | 170 files or more | KB team |
| KB sync failures | Any failed item | KB team |
| Matcha 403 or 401 | Any | Operator (UA setting, key rotated) |
| Matcha 429 | More than a few in an hour | Operator (limits) |
| PHI attestation missing | Any | Compliance, operator |
| Pre-match `RETRY_LATER` rate | Above a set share | Operator |

## 5. Runbooks (short)

**SNOW export stale.** Check the ServiceNow report schedule and mailbox; check the flow run history; check Azure `/snow/status`; if the flow is broken, upload an export by hand with the same replace call; confirm Azure refreshed.

**Replace failed.** Read the failure reason; if the file ID is wrong the recovery branch fixes it; if Matcha returns 403 check the User-Agent and key; the old file stays in place meanwhile.

**Shard near cap.** Prune retired articles; if still near the cap, split by sub-client or product and update the client map.

**403 from Matcha.** Confirm the User-Agent header is set; confirm the key was not rotated; confirm the host.

**429 from Matcha.** Respect `retry-after`; reduce concurrency; check other users of the same key owner; ask for a higher or business-unit limit.

## 6. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| Legacy environment retires before file endpoints exist in the new API | File flows stop | Configuration switch; early question to Matcha; keep an export of all KB and SNOW source files |
| PHI recall below policy | Compliance exposure | Measured corpus; fail-closed attestation; second gate in Matcha; policy owner sign-off |
| Matcha edge blocks Azure | Pre-match fails | Browser User-Agent; `RETRY_LATER`; alert on 403; ask for a service allow-list |
| Daily request limit exhausted | Audits stall | Client limiter, budget, business-unit key, batch backfill |
| Key exposed again | Unauthorised access | Key Vault, rotation runbook, one key per purpose |
| One-file design loses a file | Matching stops | Recovery branch, stale alert |
| Cache holds PHI longer than policy | Compliance | Encryption, short TTL, approval of D12, no content logging |
| ASR change lowers accuracy on names and digits | Matching and audit quality | Bake-off on real calls, shadow, adapter with rollback |
| Shared outbound pool changes | Allow-lists break | Do not rely on IPs; NAT gateway if a fixed address is required |
| Daylight-saving ambiguity | Wrong ticket times | Explicit timezone handling, test the transition week |

## 7. Open items

| # | Item | Owner (role) | Blocks |
|---|---|---|---|
| 1 | Effective limits on the legacy key; daily limit on the new key | Platform admin | Request budget |
| 2 | Business-unit or service key: who creates it | Platform admin | Phase 0 |
| 3 | Can missions and prompts be created by API | Matcha team | Phase 2 effort |
| 4 | Approve the short-lived Azure cache of the SNOW export (D12) | Data owner, compliance | Phase 3 live |
| 5 | Longest expected audit backlog (confirm the 72-hour window) | Operations | Phase 1 |
| 6 | PHI recall target and policy owner | Compliance | Phase 4 |
| 7 | Whether the SNOW mission's search index is used; effect of re-indexing on each replace | Matcha team | Phase 1 |
| 8 | Retention periods (inbound copies, cache, transcripts, evidence) | Compliance | Phase 3 |
| 9 | NAT gateway for a fixed Azure address | Cloud team | Optional |
| 10 | Labelled set of past call-to-ticket matches and PHI examples | Operations, QA | Phases 3 and 4 |
| 11 | Confirm production folder 31790 and mission 50641 for the SNOW export | Operations | Phase 1 |
| 12 | Are all calls English, or is Spanish and other language support needed | Operations | ASR choice |
| 13 | Which hosting targets must the image run on (other clouds, on-premises, offline) | Cloud team | Phase 8 |
| 14 | Whether the audio can leave Azure at all (affects hosted ASR options) | Compliance | ASR choice |
| 15 | Who owns the flow-run service account for FlowBuilder | Platform admin | Orchestration choice |
| 16 | Share your SLM and regex rules (or the old `LocalSLMDetector` logic): model used, labels, thresholds, what counts as PHI versus caller | Policy owner | Phase 4 (PHI_POLICY_V2 section 4) |
