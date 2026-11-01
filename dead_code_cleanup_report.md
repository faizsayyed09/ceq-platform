# Dead Code Cleanup Report

## Immediate removal evidence

- Tracked and regenerated `*.pyc` files have no source/runtime value and are not executed directly.
- `.pytest_cache` and test bytecode are generated build/test artifacts.

## Uncertain or reference-dependent code

- `components/`, Langflow JSON exports, legacy providers, and old matching logic are referenced by compatibility paths, documentation, or existing tests. They remain archived candidates, not immediate deletes.
- `providers/knowledge.py` has provider implementations but external provider wiring is deployment-specific; it is not demonstrably dead.
- `services/matching.py` is referenced by `/ticket-match`, workflow, MCP, and unit tests. It is not dead.
- Legacy PHI implementations are referenced by transcriber compatibility paths. RETIRE requires labelled policy parity.

## Actions taken

Tracked bytecode will be removed and cache directories excluded by existing `.gitignore`/`.dockerignore`.
