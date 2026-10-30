# Security and PHI Protection

## Security Scope

CEQ processes operational Service Desk data, audio recordings, transcripts, ticket information, knowledge sources, reports, and potentially protected health information. Security controls must cover source, storage, processing, provider transfer, logs, and deletion.

## Secrets

- Store credentials in environment variables, Azure Key Vault, Container Apps secrets, managed identity, or another approved secret provider.
- Never commit client IDs used as secrets, client secrets, bearer tokens, API keys, passwords, audio, transcripts, or reports.
- Keep manual Genesys bearer tokens disabled unless explicitly approved for testing through `ALLOW_MANUAL_TOKEN_TESTING=true`.
- Production configuration should default manual testing to false and gate it independently from code defaults.
- Sanitize exception messages, HTTP errors, logs, and API responses before returning data.

## Genesys Access

Genesys region values are allowlisted and normalized. Recording and auth requests validate identifiers and reject unsupported regions. Bearer tokens belong in request metadata or approved secret handling and must not be persisted in flow exports, logs, tests, or documentation.

## PHI Policy

Protected information includes patient names, MRNs, FINs, encounter identifiers, dates of birth, SSNs, insurance/member identifiers, account identifiers, diagnoses, and clinical notes.

Canonical audit evidence is distinct from provider-safe content:

- `OFF`: Preserve content without transformation; restricted authorized environments only.
- `AUDIT_MODE`: Preserve canonical text and report findings as metadata. Default mode.
- `LLM_MODE`: Produce a provider-safe projection with protected values replaced by typed placeholders while retaining operational identifiers.
- `STRICT`: Block protected destinations/routes or route them to manual QA when protected data is detected.

The legacy `redact_pii` compatibility flag maps `true` to `LLM_MODE` and `false` to `OFF`; new integrations should use `protection_mode`.

Operational Service Desk identifiers such as employee/caller names, contacts, ticket/KB references, departments, locations, devices, and systems are not replaced solely because PHI protection is enabled. They remain available for authorized audit evidence.

## Storage and Retention

- Local artifacts are development support, not a production data store.
- Use external object storage, encryption, access control, retention, lifecycle, and deletion controls for production.
- Artifact keys use validated owner/type/filename segments.
- Recording and report lifecycle settings must match legal, organizational, and client retention requirements.
- Delete temporary audio and scratch files at the end of transcription operations where the caller owns those files.

## Network and Containers

- Recording media and provider URLs should use HTTPS.
- Outbound HTTP should use bounded timeouts, size limits, and explicit provider authorization.
- Container service accounts should have only the permissions needed for storage, secrets, and provider APIs.
- Do not run application containers as root.
- Pin base images and dependencies for production release builds when image reproducibility is required.
- Review ingress, CORS/authentication, Azure network controls, and cross-service trust before exposing FastAPI externally.

## Logging and Observability

- Log job identifiers, service status, byte counts, durations, and operational outcomes rather than transcripts or token values.
- Avoid raw exception bodies that may contain secrets or provider payloads.
- Redact authorization headers, request bodies, private ticket content, patient data, and upload filenames when those values are not operationally necessary.
- Use log retention appropriate to the application's approved audit policy.

## Testing Controls

Security regressions should be covered with unit and integration-style tests for:

- Region allowlists and manual-token gating
- SSRF/unsafe URL and filename rejection
- Content-length and streamed-byte size limits
- Path traversal and artifact-key validation
- PHI mode behavior and projection correctness
- Error-message redaction
- Credential and token handling

## Production Security Checklist

- [ ] Secrets loaded only from approved secret sources
- [ ] Managed identity or least-privilege provider credentials configured
- [ ] External artifact storage and encryption enabled
- [ ] PHI mode and destination policy approved
- [ ] Retention/deletion controls configured and tested
- [ ] Authentication and authorization applied at HTTP ingress
- [ ] Structured logging/redaction verified
- [ ] Vulnerability and dependency scan completed
- [ ] Backup/restore and incident response procedures documented
- [ ] Legacy components/flows reviewed for secrets and external callbacks
