# GitHub Branch, PR, Release, and Tag Strategy

## Branches

- `main`: protected, deployable history only. Direct pushes are prohibited.
- `transcriber-rewrite`: temporary integration branch for the current transcriber/V2 stabilization. Delete after its reviewed merge to `main`.
- `feature/<topic>`: new components, API routes, workflow, or documentation.
- `fix/<topic>`: focused defects.
- `security/<topic>`: security fixes and dependency remediation.
- `release/<x.y.z>`: optional stabilization branch; normal development does not require it.

Create branches from the latest `main` unless explicitly integrating `transcriber-rewrite` work.

## Protection

Protect `main` and require:

- At least one approving review.
- `CEQ CI / test` status to pass.
- Linear history or rebase/squash merge.
- Current branch relative to `main`.
- No bypass except repository administrators when explicitly authorized.

## Commits

Use Conventional Commits:

```text
feat(transcriber): add segment grouping
fix(genesys): reject malformed region values
test(api): cover transcription limits
docs(workflow): add local setup commands
chore(docker): pin Langflow image
ci(github): add compose validation
```

Keep commits atomic. AI-assisted commits include the repository-required co-author trailer.

## Pull requests

- Target `main`, except for a documented stabilization PR from `transcriber-rewrite`.
- Keep each PR scoped to one workflow or behavior change.
- Link an issue when applicable.
- Do not include secrets, recordings, transcripts containing real PHI, generated reports, caches, or database files.
- Complete the pull request template and include Langflow screenshots or flow exports only when visual behavior changed.

## Releases and tags

Use Semantic Versioning `vMAJOR.MINOR.PATCH`.

```text
v0.x.x  Pre-1.0 stabilization
v1.0.0  First documented production-ready release
v1.1.0  Backward-compatible component/API capability
v2.0.0  Breaking API/flow contract
```

Create tags only from merge commits on `main`. The release workflow:

1. Runs the repository test suite.
2. Builds the `ceq-api` image for the Linux target.
3. Publishes it to GHCR when registry credentials are available.
4. Creates a GitHub Release for the tag.

Example:

```powershell
git switch main
git pull --ff-only origin main
git tag -a v2.0.0 -m "CEQ Platform v2.0.0"
git push origin v2.0.0
```

Do not manually edit or recreate an existing release tag.
