# Context the specifications do not spell out

Why this repo is being re-architected: it grew duplicated matchers, PHI engines and transcribers; the Azure workflow never called a Mission. We reviewed the architecture end to end and agreed the split in HYBRID_ARCHITECTURE.md.

Changes of direction, in order (the later one wins):
1. Hybrid split: Matcha orchestrates and judges; Azure does media, PHI and now SNOW pre-match.
2. PHI must detect patients but NOT clinician or staff callers, so tickets still match. We keep the SLM together with regex and Presidio (an earlier design had retired it; that was reversed). The owner's own SLM and regex rules are still to be supplied (open item 16): this repo's LocalSLMDetector and PHI regexes are the best clue. Report what they do before replacing them.
3. SNOW export: one permanent file replaced in place hourly by Power Automate (tested), rolling 72 h window, nothing deleted.
4. SNOW pre-match moves from a Matcha component to an Azure service that downloads the file from the Matcha folder, caches it briefly (needs approval, D12), scores on raw rows, sanitizes only the top candidates, and returns them with the call fingerprint. The Matcha component runs in shadow mode until a gate passes.
5. KB lookup: the single KB mission hit the 200-file cap. Move to about 12 per-client missions with a code router and one parameterized Power Automate flow; two-stage lookup (search, then read chosen articles in full); confidence computed in code.
6. Speech recognition: faster-whisper large-v3-turbo is under review against Parakeet TDT 0.6B v3; decide by a bake-off on real calls, behind an adapter (ASR_MODEL_EVALUATION.md).
7. The final service must ship as a portable container image with documented prerequisites (DOCKER_PACKAGING_AND_PORTABILITY.md), built last (Phase 8).
8. MatchaOS Mission folder/file create, list, upload, and delete routes are live-tested. Download, replacement, and indexing behavior remain untested; Azure storage remains authoritative.

Things the owner cares about most: ticket matching must not fail because a caller is a clinician; no duplicate or confusing SNOW files; audits must finish before data is replaced; no secrets in repos or flow exports; everything environment-specific is configuration so we can move to the new MatchaOS later.

Not yet decided: see SECURITY_OPERATIONS_AND_OPEN_ITEMS.md section 7.

Working repo: this repo (ceq-platform) on branch feature/ceq-v3-architecture. A separate empty repo CEQAuditsPipeline exists but is not used.