# KB_LOOKUP_V2_SPEC (v1, 2026-11-01)

Makes KB lookup more robust and smarter while keeping Matcha Missions as the intelligence and code as the guard. Behaviour only; no code.

## 1. Inputs and outputs

Input (from the verified ticket and the call projection): client (SNOW Company), short description, sanitized description, `KA number` if present, issue terms, channel.

Output JSON: `kb_status` (`FOUND`, `WEAK`, `NONE`, `ERROR`), `confidence` (`HIGH`, `MEDIUM`, `LOW`, computed in code), `articles` (ids, titles, scores), `kb_gap` (true when the call needed an article that does not exist), `cited_by_agent`, `reasons`, `shard_used`, `fallback_used`.

## 2. Steps

1. **Route.** Normalise the ticket's Company through the alias table (`KB_SYNC_AND_SHARDING_SPEC.md`, section 4) to a shard. Unknown client: use the generic shard and cap confidence at LOW.
2. **Build the query** in code from the ticket facts: problem phrase, product or application name, error text, with client-specific terms removed (the shard is already the client). One query normally; one extra variant when the first result is weak.
3. **Stage 1: search** the shard with sources included, up to 20 passages (API cap). Each source carries file ID, folder ID, score and chunk.
4. **Stage 2: read in full.** For the top one to three articles, call the mission with the file ID so the article is read whole (articles are single-chunk, so this is cheap). The Mission judges which article answers the issue.
5. **Validate in code** (section 3).
6. **Compute confidence in code** from retrieval score, the Mission's judgement, agreement between stage 1 and stage 2, and whether the agent's cited `KA number` matches.
7. **Return** to the payload builder, which applies the existing KB policy: HIGH without a gap is enforceable; lower confidence is advisory unless the agent cited that article in the ticket.

## 3. Code-side checks

| Check | Failure result |
|---|---|
| Every article ID the Mission cites was among the retrieved sources | Drop the citation; lower confidence |
| The article belongs to the resolved client's shard (or the generic shard) | Drop; flag a cross-client citation |
| Article state is Active | Drop retired articles |
| The ticket's `KA number`, if any, is looked up directly in the shard | If found, promote it as "cited by agent" |
| JSON has required keys | Fallback JSON with `kb_status: ERROR`; manager review |
| Confidence stated by the Mission is ignored | Code value wins |

## 4. Thresholds

Retrieval score cut-offs for "weak" and "strong" start from the mission's own settings (rerank 10, knn 85, match 40) and are tuned on the evaluation set. No number here is final. The API parameter `allowLessRelevance` stays off by default and is used only on the retry variant.

## 5. Request budget

Typical 2 to 3 calls per audit (search, read, sometimes one more query). A cache by (shard, query hash) inside a run avoids repeats. The client limiter and `retry-after` rules from the boundary document apply.

## 6. Failure behaviour

| Condition | Result |
|---|---|
| Mission fails or returns bad JSON | `ERROR`, manager review, audit continues |
| Shard unavailable | Fall back to the generic shard, LOW confidence, flag |
| Matcha 429 | Honour `retry-after`; retry within the item budget |
| No articles found | `NONE`; `kb_gap` computed by the Mission and checked against the ticket's own text |

## 7. Evaluation (Proposed)

Build a set from past audits where a manager corrected the KB result. For each case store the ticket facts, the correct article, and the client. Metrics: hit at 1 and at 3, false HIGH rate (HIGH with a wrong article), cross-client citation count (must be zero), gap precision. Run it before every prompt, shard or threshold change, and compare with mission 47043 for parity before retiring it.

## 8. Logging

Per lookup: query text, shard, retrieved IDs and scores, chosen IDs, confidence components, validation outcomes. No ticket text beyond the sanitized query.

## 9. MCP (Phase 6, optional)

`kb_search` and `kb_get_article` expose the same router and validation to analysts and the Teams bot, read-only. The batch pipeline calls the same functions directly, not through MCP.

## 10. Prompt management

Per-client prompts are generated from one master template; the template is versioned. The client-isolation rule stays in every prompt as a backstop to routing.
