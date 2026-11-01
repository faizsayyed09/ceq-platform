# CEQ v3 programme (read before any change)

This repo is being re-architected per docs/ceq-v3/. Read docs/ceq-v3/00_INDEX.md first, then docs/ceq-v3/HANDOFF_CONTEXT.md. Those documents are the source of truth; the decision log (D1 to D12) lists what is settled. All paths in them that start with docs/ mean docs/ceq-v3/ here.

Architecture: Matcha/MatchaOS = intelligence, workflow, Missions, dashboard, governance. Azure = compute, storage, PHI processing. Power Automate feeds SNOW exports and KB articles into Matcha Mission Storage, which is authoritative. Matcha decides, Azure processes. Azure never calls a Mission.

Hard facts (tested; docs/ceq-v3/MATCHA_API_TEST_REPORT.md):
- Legacy Matcha API (https://matcha.harriscomputer.com/rest/api/v1, key mk_live_ in header MATCHA-API-KEY, integer IDs) has file endpoints. The new MatchaOS API (https://matchaos.harriscomputer.com/api, key mos_sk_live_, UUIDs) has none. Keys do not cross over. The two environments are not synced. File work stays on legacy for now.
- Host, folder IDs, mission IDs and keys are configuration, never constants.
- Always send a browser-style User-Agent to Matcha; default agents get 403.
- Client-side rate limiter on every Matcha caller (new key 120/min; legacy documented 500/min, 2,000/day). Honour retry-after.
- One permanent SNOW file, replaced in place hourly. Freshness = updated_at; settle 30 s.

Rules:
- Never write, print, log or commit secrets, keys, recordings, transcripts, ticket exports or PHI. If you find a secret in code, flows or history, report file and line only; do not copy the value. Secrets come from Key Vault, secure inputs or mounted files (VAR_FILE form).
- Never log ticket text, transcript text or names; log identifiers and counts.
- PHI: doctors, nurses, staff, requesters and contacts are workforce, not PHI; patients are. The SLM may add protection; it may lift it only for a workforce-field name above threshold with no patient identifier nearby. Fail safe. See docs/ceq-v3/PHI_POLICY_V2.md.
- Existing behaviour is the baseline: before changing a module, run its tests, record the result, and keep them green or explain every change. Mark each module KEEP, ADAPT, REWRITE or RETIRE per docs/ceq-v3/MISSION_OWNERSHIP_MATRIX.md; do not delete anything until its replacement passes parity or shadow tests.
- One phase at a time per docs/ceq-v3/IMPLEMENTATION_PLAN.md. Show a plan and wait for approval before large changes. One branch per change off feature/ceq-v3-architecture; never commit to main.
- Update the relevant doc in the same change as the code. Label claims Tested, Documented, Observed, Proposed or Unknown. Do not invent thresholds, targets or retention values: ask.
- No new dependency without the reason, licence and pinned version.