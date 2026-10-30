# CEQ Platform

AI-powered call auditing platform.

## Components

### CALL AUDITS

- Service Desk QA Transcriber
- CEQ Auditor
- Audit Payload Builder
- Audit Result Parser
- KB Lookup
- Snow Ticket Finder
- Call Fingerprint
- HTML Report Download

### CEQ DISPATCHER

- New Calls Dispatcher
- Audit Roster
- Genesys Cloud Auth

### EMAIL AUDITS

- Genesys Email Fetcher
- Prompt Template
- Audit Result Parser
- Call Fingerprint

## Runtime Targets

- Langflow Desktop
- Langflow Server
- Docker
- FastAPI
- Azure Container Apps

## Development Workflow

See [docs/Development-Workflow.md](docs/Development-Workflow.md) for VS Code setup, Langflow component mounting, Docker volumes, Git branching, testing, releases, and component/MCP conventions. Tracked VS Code configuration is under `.vscode/`; local secrets belong in `.env.local` and must not be committed.
