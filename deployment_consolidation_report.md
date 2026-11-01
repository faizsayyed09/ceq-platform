# Deployment Consolidation Report

## Supported path

- Application image: `docker/Dockerfile`.
- Local runtime: `docker/docker-compose.yml`.
- Infrastructure: `infra/main.bicep` plus modules.
- Release automation: `.github/workflows/release.yml`; CI remains `.github/workflows/ci.yml`.

## Consolidation findings

- `.github/workflows/acr-build-publish.yml` duplicates registry/image build behavior and should be retired after release workflow parity.
- `scripts/deploy-azure.ps1` is a manual deployment accelerator, not the single maintained automated path.
- Bicep is production infrastructure definition; the manual script can remain as a helper only while deployment parity is undocumented.
- Docker Compose includes Langflow and FastFlow assets, but the CEQ v3 architecture classifies Langflow as compatibility rather than authoritative workflow.

## Deletion gate

No deployment file is deleted until release/ACR/Bicep parity and clean-host replay are verified. Experimental paths are archived first.
