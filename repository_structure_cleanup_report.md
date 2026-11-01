# Repository Structure Cleanup Report

## Target structure

- `api/`, `services/`, `modules/`, `contracts/`, and `providers/`: maintained application implementation.
- `components/`, `flows/`: compatibility/adaptation assets only; candidates for archive after parity.
- `docker/`, `infra/`, `.github/workflows/`: one maintained deployment path.
- `scripts/`: operational tools with tests.
- `tests/unit/`: maintained test suite.
- `docs/ceq-v3/`: architecture source of truth.
- `docs/`: concise maintained documentation.
- `archive/`: recovered, superseded, and historical assets.

## Current issue

The repository mixes maintained implementation, compatibility components, historical exports, duplicate guides, generated artifacts, and old flow JSON exports. Cleanup will separate maintained content from archived compatibility assets.
