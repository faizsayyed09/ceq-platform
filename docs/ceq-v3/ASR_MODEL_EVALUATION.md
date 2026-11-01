# ASR_MODEL_EVALUATION (v1, 2026-11-01)

Question: replace faster-whisper `large-v3-turbo` with a newer, lower-compute model that is more accurate? Short answer: **worth a bake-off, not a blind swap.** The leading candidate is NVIDIA Parakeet TDT 0.6B v3 on CPU. The decision must come from your own calls, because published numbers are clean-audio English and your audio is telephony.

## 1. What published sources say (third-party; treat with care)

| Model | Reported accuracy | Compute | Languages | License |
|---|---|---|---|---|
| Parakeet TDT 0.6B v3 | About 6.3 percent average WER on the Open ASR Leaderboard (English); the English-only unified variant about 5.9 | INT8 ONNX of about 630 to 680 MB, runs on CPU through sherpa-onnx; reported energy use roughly 8 to 10 times lower than Whisper per hour of audio (one third-party benchmark) | 25 (v3); English-only variant | CC-BY-4.0 (attribution) |
| Whisper large-v3-turbo (current) | About 7.75 percent (large-v3 about 7.4) | 1.6 GB; fine on CPU through whisper.cpp or faster-whisper, slower than Parakeet | 99+ | MIT |
| Distil-Whisper large-v3 | Close to large-v3, English | Lighter than turbo | English | MIT |
| Canary Qwen 2.5B, Granite Speech 3.3 8B | Best reported (about 5.6 to 5.9) | **GPU** (about 8 GB or more) | English (Granite adds a few European languages) | CC-BY-4.0 / Apache 2.0 |
| Moonshine | Not reported in the sources I could read | Edge devices | Limited | Not stated |

Caveats: the spread among the top models is about 1.5 WER points, small next to telephony noise. Several sources are from vendors that ship these models. The leaderboard is English and clean. Whisper's known weakness is inventing text during silence, which matters on calls with long holds; one source says Parakeet is less prone to this. I could not confirm timestamp quality, long-audio handling or custom-vocabulary support from those sources: verify each.

## 2. What matters for this pipeline (more than WER)

1. **Entity accuracy**: phone digits, extensions, ticket and KB numbers, person names, product and application names. Ticket matching depends on these, not on overall WER.
2. **Telephony audio**: 8 kHz narrowband upsampled to 16 kHz; two channels (caller, agent) already separate speakers, so diarization is not needed.
3. **Silence and hold behaviour**: no invented text; word timestamps good enough to align with Genesys hold events.
4. **Vocabulary**: healthcare and IT terms (system names, ticket vocabulary).
5. **Compute**: real-time factor on the target CPU (today 1 vCPU, 2 Gi), peak memory, cold start.
6. **Languages**: English only, or Spanish and others (open item 12).
7. **Data location**: stay on a self-hosted model; audio must not leave Azure (open item 14).

## 3. Recommendation

1. Treat Parakeet TDT 0.6B v3 (INT8 ONNX on CPU) as the challenger; keep faster-whisper large-v3-turbo as the baseline and as the fallback for languages the challenger lacks.
2. Put ASR behind an adapter in the job so the engine is configuration, with the same output contract (speaker-labelled lines, word timestamps, confidence).
3. Skip GPU-only models unless you decide to run a GPU.
4. Add a model-independent correction layer (known names, systems and spoken-digit normalisation) so accuracy does not depend on one engine's vocabulary handling.

## 4. Bake-off plan

| Step | Detail |
|---|---|
| Sample | 100 to 200 real calls, stratified: clear, noisy, accented, short, long, long holds, many digits. Genesys stereo kept. |
| Reference | Human-corrected transcripts for a subset (about 40 to 60 calls), including every entity above. |
| Candidates | Current turbo configuration, Parakeet v3, optional Distil-Whisper. Same VAD and resampling for all. |
| Metrics | WER; entity accuracy per type; silence-hallucination count per hour of hold; word-timestamp error against Genesys holds; real-time factor and peak memory on the target CPU; cold start; cost per audio hour. |
| Decision rule (Proposed) | Adopt if entity accuracy is not worse than the baseline on any type, overall WER is lower, silence handling is no worse, and compute fits the target without raising cost. The owners confirm the thresholds before the test. |
| Shadow | Run the challenger on live audio beside the baseline; compare the downstream effect (match status, ticket, score) before switching. |
| Rollback | A configuration value; the baseline stays packaged until the shadow period ends. |

## 5. Sequencing

Decide the ASR engine **before** labelling the PHI corpus and before tuning match thresholds, because both depend on the transcript text. Run the bake-off in parallel with Phase 3 and finish it before Phase 4 starts its corpus.

## 6. Packaging notes

Bake the chosen model into the image (see `DOCKER_PACKAGING_AND_PORTABILITY.md`); CC-BY-4.0 requires attribution in the image's license notices; pin the model version by checksum.

Sources: [Parakeet vs Whisper vs Nemotron (OpenWhispr)](https://openwhispr.com/blog/parakeet-vs-whisper-vs-nemotron), [Best open-source STT models in 2026 (Northflank)](https://northflank.com/blog/best-open-source-speech-to-text-stt-model-in-2026-benchmarks). The Open ASR Leaderboard page I tried returned no data; check the Hugging Face leaderboard directly before the bake-off.
