# Technical Debt Report

## High-priority debt

1. Duplicate matching, PHI, knowledge, and workflow implementations retain parallel behavior.
2. Live cutover and retirement gates remain unproven.
3. Deployment paths are split across Compose, Bicep, PowerShell, and workflows.
4. Documentation mixes v2/legacy component terminology with CEQ v3 architecture.
5. Generated artifacts have been tracked in source.
6. Runtime dependencies and dev dependencies share one manifest.
7. Branch/topic-branch sprawl is substantial.

## Mitigation

Canonical docs, architecture-boundary enforcement, parity gates, one Docker/Bicep release path, pinned dependencies, and branch deletion only after merged/unused evidence.
