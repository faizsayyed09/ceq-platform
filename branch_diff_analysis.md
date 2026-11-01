# Cross-Branch Diff Analysis

## Architecture versus main

Architecture adds the maintained FastAPI, services, contracts, CEQ v3 specifications, Docker/Compose preflight, security controls, and Phase 0-8 implementation. Main lacks the architecture branch's repository work and must not be treated as the canonical release branch.

## Architecture versus transcriber-rewrite

`transcriber-rewrite` contains a separate transcription rewrite line. It must be tested against the current `TranscriptionService` and v2 audio modules before removal. No evidence currently establishes full parity for audio validation, silence detection, output segments, or model configuration.

## Architecture versus security-fix

The security-fix branch contains auth hardening with region allowlists and bounded manual token behavior. The architecture branch has equivalent test coverage and is closer to current canonical code, but branch-level delta review is required before deleting the security branch.

## Architecture versus infrastructure branch

The infra branch predates the maintained Bicep modules and Container Apps configuration on the architecture branch. It is an archive candidate only; its historical assets have no confirmed deployment dependency.

## Documentation drift

- Multiple maintained and legacy architecture documents describe components/flows as runtime structure.
- CEQ v3 documents are the source of truth per `docs/ceq-v3/00_INDEX.md`.
- Duplicate deployment documentation exists in root docs and CEQ v3.
- Duplicate phase documents and `_1`/`_2` naming indicate downloaded revisions rather than maintained sources.

## Configuration and deployment drift

- Docker is the single maintained runtime packaging path.
- Azure deployment remains split across manual PowerShell deployment, GitHub ACR workflows, and Bicep definitions.
- The canonical environment set is incomplete for Matcha credentials, SNOW folders, and service keys; these remain configuration gaps.
