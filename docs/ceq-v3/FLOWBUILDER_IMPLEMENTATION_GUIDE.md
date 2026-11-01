# FLOWBUILDER_IMPLEMENTATION_GUIDE (v2, 2026-11-01)

## 0. Prerequisite check (verify before building)

The supplied "MatchaOS Explained" text is an AI-generated answer, not product documentation. The new API documentation settles part of it: **flow runs are documented** (start a run, run and wait up to 90 seconds, poll a run; runs appear in Run History). Still to verify: (a) HTTP steps with header secrets, (b) calling Missions with model options from inside a flow, (c) polling loops, branches and error paths, (d) reaching the Azure ingress, (e) **who can run a flow**: only the flow's owner can start it or read its runs, so the owner must be a service account, not a person. If any check fails, the same design runs in the existing MDS (Langflow) flow, which already provides these through custom components.

## 1. Recommended flow

```
Trigger (dispatcher: conversation_id, channel, agent, run_id)
  1  Azure: POST /jobs/interaction            -> job_id
  2  Poll GET /jobs/{id}                      -> DONE | RETRY_LATER | FAILED
  3  Attestation check (PHI policy version)   -> block to Manual QA if absent
  4  SNOW pre-match: provider switch          -> matcha | shadow | azure
        azure  : job result already holds snow_status + sanitized candidates
        shadow : run both, log both, use the Matcha result
  5  SNOW Ticket Mission (Mission Caller)     -> ticket proposal JSON (candidates only)
  6  Ticket gate (code)                       -> verified ticket / NOT_FOUND / OUT_OF_WINDOW
  7  KB router + query builder (code)         -> shard, query
  8  KB lookup v2 (search, read, validate)    -> confidence, articles, kb_gap
  9  Payload builder (code)                   -> VERIFIED FACTS + procedure policy
 10  CEQ Audit Mission (Mission Caller)       -> attribute results JSON
 11  Audit result parser (code)               -> score, verdict, review reasons, HTML, row
 12  Azure: POST /evidence/{conversation_id}  -> archive reference
 13  Output: email package, dashboard row, review queue
 14  Azure: POST /purge/{conversation_id}; Matcha purges run messages
```

## 2. Step notes

- **Steps 1 and 2.** One composite job replaces separate download and transcribe calls. Poll every 30 to 60 seconds; stop at the item budget. `RETRY_LATER` reschedules through the dispatcher.
- **Step 3.** Reject transcripts lacking `phi_policy_version`. Route to Manual QA; never send to a Mission.
- **Step 4.** The provider switch is configuration. In `azure` mode the job result carries status and candidates; Matcha does not read the SNOW file. In `shadow` mode the Matcha component still decides.
- **Steps 5 and 6.** The Mission only disambiguates among the candidates it is given. The gate overrides any Mission answer not among the code candidates. `OUT_OF_WINDOW` and `PENDING_EXPORT` go to hold or review, never to an unmatched score.
- **Steps 7 and 8.** Router, two-stage lookup and validation as in `KB_LOOKUP_V2_SPEC.md`.
- **Steps 5, 8 and 10.** All use one Mission Caller component: model chain with circuit breaker, required-JSON-key validation, fallback JSON, PHI sentence gate on ticket and KB text, cost log, **client-side rate limiter and 429 handling**, browser-style User-Agent, host and key from configuration. Replace the three identical copies. Mission answers arrive as a JSON string inside the answer text: parse and validate it.
- **Step 9.** Encodes KB policy: HIGH confidence without a gap is enforceable; lower confidence is advisory unless the agent cited that article in the ticket.
- **Step 11.** The Mission judges each attribute; code computes the weighted all-or-nothing score and the verdict (96 percent target, critical-failure override, `RETRY_LATER` when the SNOW export is pending). The SNOW check "PHI in client-visible field" reads the flags from Azure.
- **Step 12.** Archive projected evidence plus the final JSON. The reviewer report stays the MatchaOS-hosted HTML.

## 3. Error and branch design

| Condition | Route |
|---|---|
| Azure job `FAILED` (validation, duration cap) | Mark failed, reason in dashboard row |
| Azure `RETRY_LATER` | Requeue with grace window |
| PHI attestation missing or `STRICT` hit | Manual QA queue; no Mission call |
| Mission fatal (401, 403, mission not found) | Pause dispatcher, alert operator |
| Matcha 429 | Honour `retry-after`; retry within item budget |
| Matcha 403 from the edge | Check the User-Agent setting first, then alert |
| All models fail, fallback JSON used | Continue with `mission_error`; force manager review |
| SNOW `PENDING_EXPORT` | Hold or `RETRY_LATER` (keep the freshness gate) |
| SNOW `OUT_OF_WINDOW` | Manager review with reason; not scored as unmatched |
| Parse error or missing attributes | `PARSE_ERROR` or `INCOMPLETE`, manager review |

## 4. Where state lives

Dispatcher and daily-cap state: Matcha. Job state, artifacts and the SNOW cache: Azure. The current Matcha dispatcher keeps state in local files with a file lock and a daemon-thread worker, and detects completion by searching the response text for a marker. Prefer a native flow-run result (documented in the new API) if the platform supports it. Keep the single-writer lease until then.

## 5. Build order

1. Stand up the Azure job API on a test environment with synthetic audio.
2. Build steps 1 to 3 and verify the attestation path with PHI test calls.
3. Add the pre-match provider switch; run `shadow` for the trial period.
4. Rewire steps 5 to 11 by reusing existing components, consolidated.
5. Run old and new pipelines in parallel on the same conversations; compare tickets, scores and verdicts.
6. Cut the dispatcher over per channel (calls first, then emails). Email has no Azure media step but can still use the pre-match endpoint with a Matcha-supplied fingerprint.

## 6. MCP placement

**Good candidates** (an agent chooses these): SNOW ticket lookup, KB search and article tools, "re-run or explain this audit", read-only prompt and Mission governance (version, last change), read-only audit evidence lookup (projection only).

**Poor candidates:** Whisper, FFmpeg, recording download, Blob storage, transcription. They are deterministic, long-running, binary or large, and have no tool-selection decision for a model. MCP adds latency, schema tokens and an auth surface without benefit.

**Inside the pipeline**, call Missions and Azure directly. MCP lets a model pick tools, which is the wrong property for a deterministic audit run. Any MCP tool exposing audit evidence needs authentication, projection-only data and write actions behind human approval.

## 7. Acceptance checks

- No canonical transcript reaches any Matcha log or run message.
- The same conversation produces the same ticket, score and verdict as today (within Mission variance).
- Azure outage never loses a conversation: it requeues.
- Cost per audit (from the routing logs) does not rise; request counts stay under the limits in the plan.
- Shadow mode shows no unexplained disagreement before cutover.
