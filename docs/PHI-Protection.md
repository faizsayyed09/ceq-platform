# CEQ PHI Protection Architecture

## Policy

CEQ protects patient health information (PHI) without treating operational Service Desk data as generic PII. Canonical audit evidence is not permanently rewritten for names, contact details, employee identifiers, ticket/KB references, departments, locations, devices, systems, or caller/agent accountability.

Protected categories include patient names, MRNs, FINs, encounter identifiers, dates of birth, SSNs, insurance/member identifiers, patient account identifiers, and clinical notes or diagnoses.

## Modes

- `OFF`: No PHI transformation. Use only in an authorized, restricted environment.
- `AUDIT_MODE`: Default. Preserve canonical text while recording detected PHI categories and evidence offsets as metadata.
- `LLM_MODE`: Produce a projection for external LLM/provider boundaries with patient PHI replaced by typed placeholders. Operational audit identifiers remain available.
- `STRICT`: Block a selected destination or route to manual QA if protected data is detected.

The current transcriber defaults to `AUDIT_MODE`. The deprecated `redact_pii` flag is retained for compatibility: `true` maps to `LLM_MODE`, while `false` maps to `OFF`. New integrations should use `protection_mode` explicitly.

## Data flow

1. Recording and transcription preserve authorized canonical audio/transcript data.
2. Fingerprinting and ticket matching retain operational names, contacts, ticket references, issue excerpts, and location evidence.
3. Ticket and KB matching use operational context separately from unnecessary patient details.
4. Audit payload construction exposes canonical evidence for authorized internal processing and an LLM-safe projection for external providers.
5. Reports and exports apply destination-specific policy and retention controls.

## Storage and access

PHI protection does not replace encryption, access control, retention, deletion, audit logging, or secure storage requirements. Production object storage and provider integrations must enforce those controls independently.
