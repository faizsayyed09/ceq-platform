# SNOW_EXPORT_FLOW_SPEC (v1, 2026-11-01)

A new Power Automate flow, separate from the KB sync flow. It keeps exactly one SNOW export file in the Matcha mission folder and replaces it in place every hour. Behaviour only; no code.

## 1. Goals and rules

1. Exactly one file in the folder, always. No deletes in normal operation.
2. A bad, empty or partial export never replaces a good one.
3. Every export is self-sufficient: it covers a rolling **72 hours** (opened or updated), so audits never need an older export and replacing the file never strands an audit.
4. Freshness is `updated_at` of the file, not its name.
5. Everything environment-specific is configuration.

## 2. Configuration (environment variables or a small SharePoint list)

| Name | Value | Note |
|---|---|---|
| `MATCHA_HOST` | `https://matcha.harriscomputer.com` | Legacy host (file API) |
| `SNOW_FOLDER_ID` | 31790 | Taken from the pre-match component defaults: **confirm** |
| `SNOW_MISSION_ID` | 50641 | Same: **confirm** |
| `SNOW_FILE_ID` | set by bootstrap | Stored after the first upload |
| `SNOW_FILENAME` | `SNOW_TICKETS_EXPORT.xlsx` | Chosen once; replace keeps the name |
| `MATCHA_KEY` | secure input or Key Vault reference | Never in the flow body |
| `AZURE_REFRESH_URL`, `AZURE_API_KEY` | Azure `/snow/refresh` | Secure inputs |
| `ALERT_TO` | distribution list | Failure and staleness emails |
| `MIN_ROWS` | set after reading a normal export | Floor below which an export is rejected |

## 3. ServiceNow report (owner: ServiceNow admin)

- Hourly schedule, delivered by email with an `.xlsx` attachment to a dedicated mailbox or folder.
- Window: records opened **or** updated in the last 72 hours; Service Desk groups; Eastern time.
- Columns (from the sample): Number, Opened, Updated, Opened by, Email, Company, Contact, Parent, State, Description, `KA number`, plus any short description, work-notes and comments columns the audit needs. Column names never change without notice; the flow validates them.
- Prefer UTC or an explicit offset if ServiceNow can export it. If not, see section 8 (daylight saving).
- Size below 60 MB (the replace limit).

## 4. Bootstrap (run once, manually)

1. Confirm the folder is empty or holds only the file to keep.
2. Upload the first valid export with `POST /rest/api/v1/file?folder_id=<SNOW_FOLDER_ID>` under `SNOW_FILENAME`.
3. Read the file ID from the folder listing by name (do not parse it from reply text; the KB flow does and that is fragile). Store it as `SNOW_FILE_ID`.
4. Check the listing shows one file and `ingestion_status` Completed.

## 5. Hourly run: action by action

| # | Action | Detail |
|---|---|---|
| 1 | Trigger | New email in the report mailbox, sender and subject filters, "only with attachments", attachment `.xlsx`. Concurrency control = 1 so runs never overlap. |
| 2 | Pick attachment | Exactly one `.xlsx`; otherwise stop and alert. |
| 3 | Validate (Office Script) | Header names present and in any order; rows ≥ `MIN_ROWS`; dates parse; no fully blank key columns. Return `ok`, `rows`, `latest_updated`, `reason`. |
| 4 | Stop if invalid | Send an alert with the reason; **do not replace**; log the run. The old file stays. |
| 5 | Replace | `PUT {host}/rest/api/v1/file/{SNOW_FILE_ID}?folder_id={SNOW_FOLDER_ID}` as `multipart/form-data` with a browser-style `User-Agent` and the key header. Retry policy exponential, 4 attempts, 30 s start, 5 min cap. |
| 6 | Recovery branch | If the PUT returns 404 (file lost): list the folder, find by name, update `SNOW_FILE_ID`, retry once; if absent, `POST` as in bootstrap, then alert that the ID changed. |
| 7 | Settle wait | Wait 30 seconds (the file's `updated_at` moved up to three times in about 20 s in testing). |
| 8 | Notify Azure | `POST /snow/refresh` with `expected_rows` and `expected_size` (Power Automate has no built-in file hash). Azure downloads, validates, computes the hash and returns rows, size, hash, `updated_at`. |
| 9 | Compare | If Azure's rows differ from `expected_rows`, alert: the file Matcha holds is not the file that was sent. |
| 10 | Keep inbound copy | Save the attachment to SharePoint for 48 hours (it may contain PHI); a retention label or a daily cleanup removes older copies. |
| 11 | Log | Run record: timestamp, rows, latest updated, Azure result, duration. |

## 6. Failure handling

| Condition | Result |
|---|---|
| No email this hour | Nothing replaced. Azure's export-age alert fires if the file is older than 2 hours. |
| Invalid export | Alert; old file kept. |
| PUT fails after retries | Alert; old file kept; next hour tries again. |
| Azure refresh fails | Alert; Azure's own 30-minute check will still pick the new file up. |
| 429 from Matcha | Honour `retry-after`; the budget here is about 72 calls a day, so only shared use can cause this. |
| Duplicate or redelivered email | Harmless: the same content replaces itself. |
| File ID changed | Recovery branch above. |

## 7. Why one file works with in-flight audits

An audit reads the file when it runs. Replace is atomic from a reader's view: tests showed no failed or partial reads, and the new content is readable at once. Each export holds 72 hours, so an audit of a call from the last 72 hours finds its ticket in whichever export is current. An audit of an older call gets `OUT_OF_WINDOW` (see `AZURE_PREMATCH_SERVICE_SPEC.md`), not `NOT_FOUND`, and goes to review rather than being scored as unmatched. The audit backlog must be shorter than 72 hours; confirm the longest expected backlog (open item).

## 8. Daylight saving (today is the fall-back day)

ET clocks repeat 1:00 to 2:00 on 1 November 2026. Local timestamps in that hour are ambiguous. If the report cannot give UTC, Azure interprets ET using `America/New_York` with the "second occurrence" rule only for rows whose `Updated` is earlier than the previous export's latest value; the flow does not alter timestamps.

## 9. Request cost

About 72 requests a day (24 PUTs, 24 Azure refresh reads of two calls each counted on Azure's side, plus alerts). Recovery branches add a few.

## 10. Acceptance

1. Bootstrap leaves one file and a stored ID.
2. 24 consecutive hourly replacements with matching Azure row counts.
3. A malformed attachment is rejected and the old file stays.
4. Killing the PUT mid-way (network) leaves the old file readable.
5. Deleting the file triggers the recovery branch.
6. A stale-export alert arrives within 15 minutes of crossing 2 hours.

## 11. Rollback

Disable the flow and upload an export by hand with the same PUT. The Matcha pre-match component keeps working because it reads the same single file.
