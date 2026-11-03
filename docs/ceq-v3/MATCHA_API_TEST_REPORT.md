# MATCHA_API_TEST_REPORT (2026-10-31 to 2026-11-03)

All tests ran from your side because my sandbox cannot reach Matcha (CONNECT 403). Keys, folder contents and identifiers are omitted or shortened. Times are Eastern.

## 1. Results

| # | Test | Where | Result | What it proves |
|---|---|---|---|---|
| T1 | List and download on the legacy host with an `mk_live_` key | PC (PowerShell, `curl.exe`) | 200 | Key type and header are correct |
| T2 | First key (55 characters, `mos_sk_`) on the legacy host | PC | 401 | Wrong key family; legacy needs `mk_live_` plus 64 hex (72 characters) |
| T3 | Upload v1, probe every 5 s, replace in place with v2, probe, delete | PC | See section 2 | Replace-in-place is safe |
| T4 | List and download | Azure Cloud Shell | 200 | Azure-side network can reach Matcha |
| T5 | List and download from inside `ca-ceq-dev-api`, Python default User-Agent | Container | **403** | The edge blocks default client agents |
| T6 | Same, browser-style User-Agent | Container | **200** (list 430 bytes; download 23,704 bytes starting `PK`) | Azure can pull the SNOW export |
| T7 | Key used from two unrelated networks | PC and Cloud Shell | Worked | No IP whitelist on the key |
| T8 | Container Apps network inspection | Cloud Shell | Shared outbound pool of about 300 addresses; environment static IP separate; min replicas 0, max 1 | An IP allow-list is not an option without a NAT gateway |
| T9 | Listing with an empty folder ID | PC | HTTP 500 | Always validate IDs; the API does not return 400 |
| T10 | New key on `GET /api/v1/models` | PC | 200, 21 models | New key authenticates |
| T11 | Legacy `/files` route on the new host | PC | 404 "Unknown route" | The legacy route was not sufficient; folder/file Mission routes discovered later were tested separately |
| T12 | New key on the legacy host | PC | 401 | Keys do not cross over |
| T13 | `POST /api/v1/completions` on the new SNOW mission (empty folder) | PC | 200; mission persona answered with the ticket-match JSON (`NOT_FOUND`); model reported `gemini-3.8-flash`; `sources` empty | Prompts migrated; Missions endpoint works; the answer is a JSON string inside `text` |
| T14 | Five calls, 60-second wait, one more | PC | Remaining 119 (first call), 118, 117, 116, then 119, then 119 after the wait | Limit 120 per minute; window did not slide gradually (a token bucket would have refilled before the second call); consistent with a fixed 60-second window from the first request |
| T15 | MatchaOS mission folder listing, completion, folder/file lifecycle | PC | Tested: mission folders listed; completion returned READY; synthetic folder created; file uploaded with HTTP 201; file and folder deleted; both GET lookups returned 404 | UUID-based Mission folders and files are supported by live routes |

## 2. Replace-in-place detail (T3)

| Moment | Observation |
|---|---|
| First upload | First probe: `status=Loading`, ingestion `Initial`, `updated_at` empty; download already worked. Within 6 s: `Uploaded`, `Completed`, `updated_at` set (it moved once more about 1 s later, then stayed). |
| Replace (PUT) | First probe after the PUT: `status=Loading`, ingestion stayed `Completed`, download already returned the **new** content hash. About 5 s later: `Uploaded`. `updated_at` moved three times (at the PUT, 3 s later, and about 19 s later), then stayed. |
| Downloads | About 30 reads across the replace: none failed, none returned stale or partial content. |
| After | File ID and original filename unchanged. Test file deleted. |

Consequences: freshness is `updated_at`, not the filename; treat the export as settled when `updated_at` is unchanged for 30 seconds or the downloaded hash matches the value the producer reported; validate every download (`PK` header, expected columns).

## 3. Not tested

- The actual limits on your legacy key (read them on the API Keys page); the new key's daily limit.
- Whether the new host also blocks default User-Agents (assume yes; set one).
- A replace while Matcha's search index is actively used; whether each replace re-indexes the file.
- File size and row count of the real export; the 60 MB replace limit.
- Behaviour when Matcha is down mid-replace.
- Whether per-client missions and prompts can be created through an API.
- MatchaOS file download and replacement endpoints.
- Re-indexing behavior and completion latency after MatchaOS upload or replacement.

## 4. Commands (without secrets)

Set the key at a prompt, never inside a saved script:
```powershell
$k  = Read-Host "Paste key"
$ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
```
- Legacy list: `curl.exe -sS -A $ua -H "MATCHA-API-KEY: $k" "https://matcha.harriscomputer.com/rest/api/v1/files?folder_id=<ID>"`
- New models: `curl.exe -sS -A $ua -H "Authorization: Bearer $k" "https://matchaos.harriscomputer.com/api/v1/models"`
- New mission: `Invoke-WebRequest -UseBasicParsing -Method Post -Uri "https://matchaos.harriscomputer.com/api/v1/completions" -UserAgent $ua -Headers @{ "matcha-api-key" = $k } -ContentType "application/json" -Body '{"mission_id":"<UUID>","input":"ping"}'`

Clean up afterwards: `Remove-Item Env:MATCHA_API_KEY` and delete test keys in Matcha.

## 5. Findings that changed the design

1. A browser-style User-Agent is mandatory for Azure calls.
2. MatchaOS folder/file lifecycle is now proven for create, list, upload, and delete; legacy file replace/download behavior remains separately relevant until its replacement/download paths are proven in MatchaOS.
3. Replace in place is reliable, so one permanent file replaces the delete-and-upload pattern.
4. 120 per minute on the new key, with the daily limit unknown, forces a client-side limiter and a request budget.
5. An IP allow-list is not available, so authentication, not network position, protects Azure and Matcha access.
