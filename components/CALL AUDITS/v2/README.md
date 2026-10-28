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
pii_redaction.py
    ?
service.py
