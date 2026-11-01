# AZURE_PREMATCH_SERVICE_SPEC (v1, 2026-11-01)

Moves SNOW pre-match from a Matcha component to an Azure service. Matcha stays authoritative for the data; Azure reads it, scores it, sanitizes the top candidates and returns them with the call fingerprint to the SNOW Mission. Behaviour only; no code.

## 1. Why Azure

Matching needs raw caller identity (name, phone, extension) that exists only in the raw transcript inside Azure, and raw ticket rows that live in Matcha. Doing the match in Azure keeps raw identity out of Matcha and lets the PHI classifier run on both sides of the comparison. Only sanitized top candidates and the explanation of the match travel to Matcha.

## 2. Data flow

```
Power Automate hourly PUT --> Matcha SNOW folder (one file)
        | POST /snow/refresh (rows, size)
        v
Azure: list + download (browser User-Agent) -> validate -> parse -> normalise -> encrypted cache
Audit run: job result (raw fingerprint stays in Azure) -> score all rows -> top N -> sanitize -> return
Matcha: SNOW Mission (candidates + projected fingerprint) -> ticket gate (only candidates allowed)
```

## 3. Export cache

| Item | Rule |
|---|---|
| Source | The single `.xlsx` in the SNOW folder. If more than one, take the newest by `updated_at` and raise an alert. |
| Fallback | If the newest fails validation, try the next newest, up to three (current component behaviour). |
| Validation | `PK` header; expected column names; rows above zero; dates parse. |
| Settle | Treat as stable when `updated_at` is unchanged for 30 seconds, or when rows and size match the refresh call. |
| Key | (file ID, `updated_at`, SHA-256). A new key replaces the old entry atomically. |
| Refresh | Push from Power Automate after each replace; backup check every 30 minutes; single-flight (one refresh at a time, others wait). |
| Storage | In-memory plus an encrypted copy on durable storage so scale-to-zero and restarts do not lose it. Contents never logged. |
| Expiry | About 6 hours after the last successful refresh (**Proposed; needs approval, D12**). |
| Failure | Retry with backoff, keep the last good copy; if none is readable, return `RETRY_LATER`. Never `NOT_FOUND` because of a read failure. |

## 4. Statuses

| Status | Meaning |
|---|---|
| `MATCHED` | Top score at or above the high threshold, or above the medium threshold with a clear lead |
| `AMBIGUOUS` | Candidates close together; the Mission decides among them |
| `NOT_FOUND` | Best score below the floor with a readable, covering export |
| `PENDING_EXPORT` | Export `updated_at` is earlier than call end plus a grace (current default 60 minutes): the ticket may not have been exported yet |
| `OUT_OF_WINDOW` | Call earlier than the export's coverage start (export time minus 72 hours): send to review, never score as unmatched |
| `RETRY_LATER` | Export unreadable or cache empty |

Thresholds carried over from the current component (**Observed in export**): matched at 100 or more, or 70 or more with a lead of 25 or more; below 45 not found. Defaults: top 3 candidates, window 60 minutes. These stay until the labelled set justifies a change.

## 5. Scoring

Keep the current features: explicit ticket number in the call, agent identity, time window, caller name and number, issue words. Additions (Proposed):

- Phonetic and fuzzy name matching for transcription errors.
- Spoken-digit normalisation ("five five five" to 555; extension and ticket numbers).
- Time proximity between call times and ticket Opened / Updated.
- Structured lines in Description (`Name`, `PH no`, `Location`) as strong evidence.
- Role-aware caller identity (clinicians and staff are expected callers; see `PHI_POLICY_V2.md`).
- One ticket per call across a batch (assignment, not independent picks) so two calls never claim the same ticket without a flag.
- A score breakdown per candidate, returned for explanation and for the evaluation set.

All scoring runs on raw rows. Only after ranking are the top N sanitized.

## 6. Sanitizing candidates

| Field | Treatment |
|---|---|
| Number, Opened, Updated, State, Company, `KA number` | Keep |
| Opened by, Contact, Requester, Email, phone | Keep (workforce identifiers; the policy owner confirms) |
| Short description, Description, work notes, comments | Presidio plus regex plus classifier; replace PHI with typed placeholders; truncate to a configured length |
| Any field | Return `phi_flags` per field and type (counts, no values), and a flag for whether the field is client-visible |

Result: Matcha receives candidates plus flags, so the "PHI in a client-visible field" attribute can be computed from flags without anyone reading the raw text.

## 7. API (internal, authenticated)

Request: `conversation_id`, `run_id`, `correlation_id`, `channel`, `top_n` (default 3, maximum 5), optional `fingerprint` (for email; calls use the stored one), optional `config_overrides` for testing.

Response: `snow_status`, `exported_at`, `export_rows`, `coverage_start`, `candidates` (sanitized rows with score breakdown and flags), `prematch_engine_version`, `phi_policy_version`, `cache_state`.

Idempotent on `conversation_id` plus `run_id`. Batch variant takes a list for the one-ticket-per-call assignment.

## 8. Shadow mode and cutover

A configuration switch with three values: `matcha` (current path decides), `shadow` (both run, current path decides, results logged), `azure` (Azure decides). Matcha's component stays deployed.

Per audit in shadow: log both statuses, both top tickets, scores, and a disagreement class (same, Azure only, Matcha only, different tickets, both none). Humans review every disagreement for the trial period and label the right ticket. Metrics: top-1 and top-3 agreement with the label, false match rate, `PENDING_EXPORT` and `OUT_OF_WINDOW` rates, latency.

**Cutover gate (Proposed; owner approves the numbers):** no regression against the Matcha component on the labelled set; every disagreement explained; zero PHI in a sampled review of candidate payloads; rollback switch tested. Rollback is setting the switch to `matcha`.

## 9. Operations

| Topic | Rule |
|---|---|
| Authentication | Service authentication on every endpoint (Phase 0). |
| Credentials | Matcha read-only key in Key Vault; dedicated service user limited to the SNOW folder if the platform allows. |
| Network | Outbound only to the Matcha host (and Genesys for jobs); browser-style User-Agent; client-side limiter. |
| Scale | Min replicas 0 today; cold start loads the cache from storage and the classifier models. Consider min 1 during business hours (**measure** cold start first). |
| Metrics | Export age, refresh success, cache hit rate, status counts, Matcha HTTP status counts, latency. |
| Alerts | Export age above 2 hours; refresh failing three times; more than one file in the folder; `RETRY_LATER` rate above a set share. |
| Logging | Identifiers and counts only; never ticket text, names or keys. |

## 10. Tests required before cutover

1. Replay a labelled set of past calls against past exports.
2. Synthetic PHI corpus: patient names, MRN, DOB beside clinician callers (`PHI_POLICY_V2.md`).
3. Export fault injection: truncated file, wrong columns, empty file, two files, 403 from Matcha, replace during download.
4. Load: a batch of calls arriving right after an hourly replace.
5. Daylight-saving week: rows around the repeated hour.
