# Duplicate Removal Report

## Confirmed duplicates

1. Generated Python bytecode duplicated source files and is removed.
2. Test caches duplicate generated test state and are removed.
3. Legacy architecture/development/deployment guides duplicate canonical CEQ v3 and root maintained docs.
4. Duplicate dispatcher/transcriber/PHI implementations exist in `components/`, `modules/`, and `services/`. They provide compatibility paths and do not meet current deletion criteria.

## Canonical rule

One capability may retain compatibility adapters, but only the maintained implementation named in `canonical_implementation_report.md` is the release source. Legacy component parity and live cutover remain blockers for deletion.
