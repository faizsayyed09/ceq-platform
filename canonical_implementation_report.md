# Canonical Implementation Report

## Canonical selection

| Capability | Canonical implementation | Duplicate/experimental implementation | Obsolete decision |
|---|---|---|---|
| Recording | `services/recording.py` | Langflow `components/CALL AUDITS/genesys_recording_downloader.py` | KEEP compatibility adapter until component parity is proven |
| Transcription | `services/transcription.py` + `components/CALL AUDITS/v2/modules/*` | Legacy component and alternate transcriber modules | KEEP both during shadow/parity; `components/CALL AUDITS/v2` is v2 implementation |
| PHI protection | `services/phi_protection.py` | `modules/phi_protection.py`, component v2 PHI modules, component-compatible implementation | ADAPT; consolidate only after policy parity tests |
| Reporting | `services/report.py` | HTML component report adapter | KEEP compatibility adapter |
| Storage/artifacts | `services/artifact_store.py` + `providers/artifact.py` | Component/report artifact behavior | KEEP provider abstraction; archive ad hoc paths only after migration evidence |
| Workflow | `services/audit_workflow.py` and `services/dispatcher.py` | Langflow JSON and custom components | KEEP compatibility; no deletion until workflow parity |
| Audit | `services/audit.py` + `api/main.py` | Component audit payload/result parsers | KEEP compatibility adapters |
| KB | `services/knowledge.py` + `providers/knowledge.py` + CEQ v3 shard design | Legacy mission/KB component paths | KEEP legacy until Phase 5 parity and live shard configuration |
| Ticket matching | `services/ticket_matching_service.py` and `services/fingerprint_service.py` for SNOW pre-match; `services/matching.py` compatibility API for simple supplied-ticket calls | Component SNOW/fingerprint implementations | ADAPT API layer to select one canonical implementation; no deletion until labelled parity |

Selection is based on maintained tests, the API boundary, contracts, and CEQ v3 ownership rules. Evidence currently supports KEEP/ADAPT, not RETIRE, for legacy paths.
