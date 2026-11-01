# Documentation Audit

## Maintained source

- CEQ v3 source of truth: `docs/ceq-v3/00_INDEX.md` and linked programme documents.
- Root README and `docs/` maintained documents will describe the current implementation and deployment path only.

## Contradictory or redundant groups

- Legacy architecture guides describe components as the primary architecture while CEQ v3 defines `services/` and Azure/Matcha boundaries.
- Multiple development/deployment workflow guides repeat Docker and startup instructions.
- Historical PDFs and flow exports are not runtime documentation.
- Component inventory text files are build artifacts/history rather than maintained architecture contracts.

## Action

Redundant legacy documents are archived, not deleted, until the maintained documentation pass is reviewed. CEQ v3 documents remain authoritative.
