# Power Automate SNOW Export Flow

New FlowBuilder implementation. This flow is not an MDS/Langflow flow.

## Configuration inputs

Supply these through secure inputs, environment variables, or a secure configuration store:

- `MATCHA_HOST`
- `SNOW_FOLDER_ID`
- `SNOW_MISSION_ID`
- `SNOW_FILE_ID`
- `SNOW_FILENAME`
- `MATCHA_KEY`
- `AZURE_REFRESH_URL`
- `AZURE_REFRESH_KEY`
- `ALERT_TO`
- `MIN_ROWS`

No secret or production identifier belongs in this export directory.

The production workbook validator is `validate_export.ts`. It returns JSON with `ok`, `rows`, `latest_updated`, and `reason`. The Office Script receives the workbook and `minRows`; the flow must reject missing configuration before invoking the replace action.

## Required behavior

1. Trigger on one new report email attachment and enforce concurrency of one.
2. Require exactly one `.xlsx` attachment.
3. Validate headers and row minimum before replacement.
4. Keep the old file when validation fails.
5. Replace the permanent file in place using the legacy Matcha file API.
6. Send browser-style User-Agent and `MATCHA-API-KEY`.
7. Honour `retry-after` and use bounded exponential retries.
8. Wait 30 seconds, then notify Azure `/snow/refresh`.
9. Preserve the permanent-file and no-normal-delete rules.
10. Disable Matcha dispatcher cleanup for this folder before go-live.

Production folder, Mission, and dispatcher cleanup values remain blocked until section 7 items 17 and 18 are resolved.
