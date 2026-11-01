# Power Automate KB Sync and Sharding

The implementation remains manual until the Matcha API capability and service-key owner are confirmed (section 7 items 2 and 3).

## Configuration

- `flows/power-automate/kb-sync/client-map.json` is the route and capacity source.
- Production `folder_id` and `mission_id` values are intentionally unset (`null`).
- No key, production host, ticket text, transcript, or PHI belongs in this directory.
- Legacy file calls require the browser-style User-Agent and `MATCHA-API-KEY` header.

## Required behavior

1. Read the `Matcha_Index` and `DeltaActions` tables.
2. Normalize each article/client name through the client map.
3. Fail loudly and exclude unmapped clients.
4. Route Upload, Replace, and Delete to the resolved old/new folders.
5. For an inactive article that is published again, upload rather than replace.
6. Decode HTML entities after stripping tags; preserve nested list indentation and image alt text.
7. Keep each action bounded by retries, count failures, and always send the summary.
8. Retry failed items on the next run.
9. Store the file ID from the upload response; if reply parsing fails, resolve it by exact filename in the folder listing.
10. Keep concurrency at 1 and batch backfill at no more than 300 legacy requests per day.

The planning thresholds in the map come from `KB_SYNC_AND_SHARDING_SPEC.md` and are Proposed until tuned. Mission 47043 remains unchanged until Phase 5 parity.
