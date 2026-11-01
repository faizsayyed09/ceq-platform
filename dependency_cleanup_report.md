# Dependency Cleanup Report

## Current dependencies

`requirements.txt` contains FastAPI, Uvicorn, Requests, NumPy, faster-whisper, CTranslate2, AV, multipart, aiofiles, orjson, pytest, and httpx.

## Assessment

- No unused dependency removal is safe without runtime import-to-manifest evidence and an environment re-test.
- NumPy, AV, CTranslate2, and faster-whisper support transcription.
- FastAPI/Uvicorn are the HTTP runtime.
- Requests is used by provider/auth/recording integrations.
- aiofiles, orjson, and multipart support artifacts, JSON, and uploads.
- pytest/httpx are test dependencies but are mixed into the runtime requirements file.

## Recommended action

Create a pinned `requirements-dev.txt` for pytest/httpx and keep runtime requirements limited to application dependencies. This remains pending until dependency-manifest tooling is added and lock evidence is available.
