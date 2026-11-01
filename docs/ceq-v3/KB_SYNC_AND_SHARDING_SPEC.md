# KB_SYNC_AND_SHARDING_SPEC (v1, 2026-11-01)

Covers the existing KB Power Automate flow, the fixes it needs, and the move from one mission (47043, at the 200-file cap) to per-client missions. Behaviour only; no code.

## 1. What exists (Observed in export)

- Trigger: ServiceNow KB export email. Office Scripts read the attachment, compare it with the Excel index workbook (tables `Matcha_Index` and `DeltaActions`) and produce a delta list of Upload, Replace and Delete actions.
- A sequential loop (concurrency 1) calls the legacy file API: `POST /rest/api/v1/file?folder_id=30903` (upload), `PUT /file/{id}?folder_id=30903` (replace), `DELETE /file/{id}?folder_id=30903`. The new file ID is parsed from reply text between parentheses. A summary email runs only after the condition succeeds.
- The production `mk_live_` key is written into three HTTP actions.
- KB articles are single-chunk files with a metadata line such as `[ METADATA: … | KB: <client> | State ]`.
- Mission 47043: max hits 25, rerank 10, knn 85, match 40, model Gemini 3.5 Flash. The API option `max_hits` is capped at 20.

## 2. Defects to fix (Proposed)

| # | Defect | Fix |
|---|---|---|
| 1 | A retired article that is published again is replaced, not uploaded; the file no longer exists | If the index entry is inactive, upload again and store the new ID |
| 2 | HTML tags stripped without decoding entities, so placeholders such as `<username>` vanish | Decode entities after stripping tags |
| 3 | Nested lists and image alt text lost | Keep nesting as indented text; keep alt text |
| 4 | Single folder ID, hard-coded | Folder per client from a client map (section 4); unmapped client fails loudly |
| 5 | A client change on an article leaves a stale copy | Delete in the old folder, then upload to the new one |
| 6 | One failure aborts the loop and suppresses the summary | Scope with retries around each item; count failures; always send the summary; failed items retry the next run |
| 7 | New file ID parsed from reply text | After upload, find the file by name in the folder listing if parsing fails; store the ID |
| 8 | Bodies built by string concatenation | Build multipart bodies with proper encoding |
| 9 | Backfill in one run | Batches (section 6) |
| 10 | Key in the flow | Secure input or Key Vault (Phase 0) |
| 11 | Browser User-Agent not set | Set one on every call |

## 3. Shards (from the August export, by each article's own `KB:` field)

| Shard (proposed) | Articles | Note |
|---|---|---|
| Marin General A | about half of 205 | Split main hospital |
| Marin General B | about half of 205 | B Clinics and Ambulatory |
| Generic: Service Desk | 144 | |
| Generic: other | 43 | Managed Services 30, Centralized 7, others |
| Comanche | 100 | |
| York | 96 | |
| SUNY | 80 | |
| Daviess | 73 | |
| K2 | 44 | |
| Wyckoff | 40 | |
| Monadnock | 34 | |
| Small clients | about 58 | Rome, Tuba City, Wrightington, Springhill |

That is 12 missions (11 if the small-client shard merges with a generic one). Total about 917 articles. The August generic group was 187 in one mission, too close to the cap, hence the split. Planning cap per shard: **180**, alert at 170, refuse an upload at 195 (the platform limit is 200 in the legacy environment; confirm the limit in the new one).

## 4. Client map (data, owned by the KB team, under change control)

One table drives the flow, the router and the capacity check.

| Column | Meaning |
|---|---|
| `client_key` | Normalised name (lowercase, punctuation stripped) |
| `aliases` | Variants seen in the SNOW Company field and in the article `KB:` field (for example "Marin General", "Marin General Hospital") |
| `shard_id` | Short code of the shard |
| `folder_id`, `mission_id` | Legacy integers (and the new UUIDs once the environments sync) |
| `active` | Whether new uploads are allowed |
| `article_count`, `cap` | Maintained by the flow |

An article whose client has no row fails loudly and appears in the summary email. A SNOW Company with no row routes to the generic shard at low confidence (see `KB_LOOKUP_V2_SPEC.md`).

## 5. Parameterized flow

One flow, not twelve. For each action in `DeltaActions`: look up the folder by client key, run upload / replace / delete against that folder, write the result back to the index. Concurrency stays 1. The daily trigger and summary email stay.

Index workbook columns (Proposed): KB number, title, `client_key`, `folder_id`, `matcha_file_id`, content hash, state (Active, Retired), last synced, last error.

## 6. Backfill

About 917 uploads. At the legacy default of 2,000 requests a day shared per key owner, backfill at most 300 a day, or use a business-unit key. Run shard by shard; verify counts after each against the export.

## 7. Creating a shard mission (manual until an API is confirmed)

1. Create the mission and folder; copy settings from mission 47043 (max hits, rerank, knn, match, model).
2. Generate the prompt from the master template: client name, aliases, the client-isolation rule, output schema. The isolation rule stays as a backstop even though routing already separates clients.
3. Record `folder_id` and `mission_id` in the client map.
4. Upload one article, run a test query, check the cited file ID.
5. Backfill.

## 8. Parity and cutover

Keep mission 47043 untouched until KB lookup v2 passes its evaluation (Phase 5). Compare answers per client; roll back by setting the router to the old mission.

## 9. Migration note

Shards live in the legacy environment today. The new environment is not synced; when it is, the same client map holds the new mission UUIDs and files are re-uploaded by whatever route Matcha provides.

## 10. Acceptance

- Every shard is within its cap and counts match the export.
- A second run with no source changes performs no calls except listing.
- A retired then republished article ends up present once.
- A client change moves the article and leaves no copy behind.
- A forced failure on one item still produces the summary and retries next run.
