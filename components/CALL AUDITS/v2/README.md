# Transcriber V2

Goals

- Remove fcntl
- Remove dynamic pip installs
- Remove worker locks
- Remove Matcha assumptions
- Add safe file deletion
- Add file size limits
- Add duration limits
- Add secure cache handling
- FastAPI compatible
- Docker compatible
- Azure Container Apps compatible

Architecture

audio_validation.py
    ?
whisper_engine.py
    ?
transcript_builder.py
    ?
phi_protection.py (compatibility wrapper only)
    ?
service.py

The canonical transcript is preserved for audit operations. PHI protection is explicit and mode-based:
`OFF`, `AUDIT_MODE`, `LLM_MODE`, or `STRICT`. Operational identifiers, names, contacts, ticket/KB references,
and locations must not be treated as generic PII.
