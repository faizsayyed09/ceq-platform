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

`audio_validation.py`
- Validates file existence, size, FFprobe metadata, stream presence, duration, and codec metadata.

`whisper_engine.py`
- Owns the pinned model runtime, transcription options, segment normalization, and engine metadata.

`silence_detection.py`
- Derives dead-air gaps from normalized transcription segment boundaries.

`transcript_builder.py`
- Builds canonical segment and utterance structures and preserves uncertainty metadata.

`phi_protection.py`
- Compatibility wrapper around the canonical runtime-neutral PHI service.

`service.py`
- Orchestrates validation, transcription, silence analysis, PHI projection, and transcript assembly.

`service_desk_qa_transcriber_v2.py`
- Provides a framework-neutral Python entry point; Matcha/Langflow runtime imports are not used.

The implementation uses container-provided binaries and packages. It performs no runtime package installation or process worker locking.

The canonical transcript is preserved for audit operations. PHI protection is explicit and mode-based:
`OFF`, `AUDIT_MODE`, `LLM_MODE`, or `STRICT`. Operational identifiers, names, contacts, ticket/KB references,
and locations must not be treated as generic PII.
