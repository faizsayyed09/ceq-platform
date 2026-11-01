# CEQ Platform V2 Service Contracts

## Shared limits

- Maximum file size: `500 MB` (`MAX_FILE_SIZE_MB`)
- Maximum audio duration: `14,400 seconds` (`MAX_AUDIO_DURATION_SECONDS`)
- Secrets: environment variables or Azure Key Vault; no hard-coded credentials
- Storage: local implementation for development, Azure/object storage implementation for production

## GenesysAuthService

- Validates an allowlist of supported Genesys regions.
- Accepts client credentials from environment configuration or managed secret providers.
- Manual bearer tokens are allowed only when `ALLOW_MANUAL_TOKEN_TESTING=true` and never in production configuration.
- Token cache entries are region/client bounded and expire using the OAuth `expires_in` value.

## RecordingService

- Inputs: validated conversation UUID, bearer token, region, and safe filename.
- Polls Genesys recordings without worker locks or shared local state.
- Rejects missing, unauthorized, forbidden, processing, and invalid recordings with structured errors.
- Streams downloads in bounded chunks and rejects Content-Length or accumulated content above the configured limit.
- Writes only through the `ArtifactStore` abstraction.

## TranscriptionService

- Validates file existence, size, FFprobe availability, duration, and media metadata.
- Uses a pinned `faster-whisper` dependency installed in the container image; it never installs packages at runtime.
- Emits canonical text, timestamped segments, segment count, size, and duration.
- Uses the PHI protection policy instead of generic PII redaction. Patient identifiers and clinical details may be detected or projected by destination, but agent/caller names, emails, phones, ticket references, KB IDs, departments, locations, devices, and systems remain available.
- Supports `OFF`, `AUDIT_MODE`, `LLM_MODE`, and `STRICT` protection modes.
- `AUDIT_MODE` preserves canonical transcript text and reports PHI findings as metadata. `LLM_MODE` adds a provider-safe projection. `STRICT` blocks protected destinations when PHI is detected.

## ReportService

- Requires a validated audit UUID and escaped report content.
- Generates HTML in the configured artifact store under a safe filename.
- The production implementation must use external object storage instead of local container state.

## API error contract

All application errors use a JSON response with:

```json
{"error":"ValidationError","message":"Human-readable safe message"}
```

Status mapping:

- `400` for general CEQ errors
- `403` for security/authorization errors
- `404` for missing resources
- `422` for validation errors
