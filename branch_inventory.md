# Branch Inventory

Evidence labels follow `docs/ceq-v3/00_INDEX.md`: Tested, Documented, Observed, Proposed, Unknown.

| Branch | Purpose | Status | Last meaningful contribution | Recommended action |
|---|---|---|---|---|
| `feature/ceq-v3-architecture` | Canonical CEQ v3 implementation and documentation | Active | Phase 0-8 repository baselines | **Keep as active integration branch** |
| `feature/repository-wide-cleanup` | Repository-wide cleanup topic branch | Active | Current cleanup work | **Keep until cleanup PR is reviewed** |
| `feature/ceq-v3-phase2-kb-sync` through `feature/ceq-v3-phase8-container-release` | Individual implementation phases | Fully merged topic branches after Phase 6, with Phase 7/8 reviewed against architecture | Phase-specific scaffolds | Delete only after PR/history confirmation; no unique runtime work is expected |
| `main` | Former default branch | Legacy/partially merged | Generic upload baseline | Do not delete; merge governance pending while architecture branch is canonical |
| `transcriber-rewrite` | Transcription rewrite line | Legacy/partially merged | Merge with main and rewrite work | Compare parity; archive candidate, retain until transcript rewrite tests prove supersession |
| `security-fix/genesys-auth-ssrf` | Security fixes for Genesys auth | Partially merged | Region allowlist, token/cache/error hardening | Port any missing delta into canonical branch, then archive/delete |
| `faizsayyed09-Infra-Dev` | Azure/Bicep infrastructure experiment | Experimental/legacy | Azure Bicep development | Archive candidate; do not delete until infra parity is confirmed |
| `docs/repository-cleanup` | Documentation cleanup experiment | Experimental/partially merged | Trailing whitespace documentation edit | Archive/delete after conflict review |
| `agents/featureceq-v3-task-implementation-plan` | Agent worktree mirror | Recovery/archive | Architecture merge PR | Archive/delete local/remote mirror if no automation references it |
| `agents/test-suite-report-and-documentation` | Agent worktree mirror | Recovery/archive | Architecture merge PR | Archive/delete local/remote mirror if no automation references it |

`feature/ceq-v3-phase7-cutover` and `feature/ceq-v3-phase8-container-release` are ancestors of the architecture branch (Tested). Older phase topic branches should be confirmed as merged before remote deletion.
