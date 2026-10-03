# Latency, Reliability, and Provider Evaluation

## 1. What the existing logs can and cannot support

`data/llm_runs.jsonl` has 331 total entries. Of these, **314 are from the actual production call sites** (`model` field = `tutor-pipeline` or `tutor-turn`, i.e. real generation calls made by `pipeline.TutorTurn`/`pipeline.TurnStream`); the remaining 17 are from a one-off model-pilot comparison (`gpt-oss-120b`, `llama3.3-70b`, `qwen3-32b` called directly, not through the tutor pipeline) and are **excluded** from the figures below, since they reflect a different, standalone comparison exercise, not the live tutor's generation latency.

**Important architectural caveat, stated explicitly rather than assumed:** the controller-integration work (this and the prior session) changed *which* action/directive gets sent to `pipeline.generate_turn` and *who* calls it, but did not change the underlying generation call mechanics (`llm_client.stream()`, the Groq/HF-router targets, or how `common.log_run` records the result). So, unlike a metric that depends on *how many calls happen per turn* (which the controller change could plausibly affect), the **per-call latency distribution below is not expected to be materially different pre- vs. post-integration**, and mixing dates for this specific metric is a low, explicitly-reasoned risk — not an oversight. Per-*stage* latency (resolver, extractor, intent classifier) is a different matter and is **not** measurable from these logs at all (see §3).

## 2. Measured generation latency (real data, filtered)

314 entries, 2026-08-08 to 2026-10-03, `tutor-pipeline`/`tutor-turn` only:

| Metric | Value |
|---|---|
| Sample size (n) | 314 (311 with a recorded latency) |
| Median | 1.258 s |
| P90 | 2.207 s |
| P95 | 3.273 s |
| Min / Max | 0.393 s / 31.657 s |
| Provider split | `groq-direct`: 303 (96.5%), `hf-nscale` (fallback): 8 (2.5%), unknown/failed: 3 (1.0%) |
| Error rate | 3/314 (0.96%) have a non-null `error` field |
| Success rate | 311/314 (99.0%) have `ok: true` |

**Cross-check against the paper's own reported pilot figures** (as reviewed in conversation, not from a repo file): the paper's preliminary-results section (as last seen) reports a median latency of 1.28s and a single 31.7s outlier from a 266-call sample window. This session's independently filtered, larger (314-call), longer-window figures (median 1.258s, max 31.657s) are extremely close — a reassuring consistency check between two independently derived numbers, though this should not be read as a formal reproduction (different sample windows, different filtering logic, and this session did not have access to the paper's exact filtering criteria).

## 3. Missing instrumentation (confirmed, not assumed)

Checked directly: only `pipeline.TutorTurn._log()` and `pipeline.TurnStream._log()` call `common.log_run`. `conversation_resolver._llm_route`, `verifier._default_extractor`, and `intent._llm_classify` each call `llm_client.chat()` directly, with **no logging call at all**. This means:

- Per-stage latency (resolution vs. extraction vs. intent-classification vs. generation) **cannot currently be computed** from any existing data.
- The number of LLM calls per user turn is known **qualitatively** from code reading (up to 3: resolver + extractor + generator for a new math question; fewer when `use_rag`/`use_verifier` is false, e.g. for CONFUSION/CORRECTION/FRAGMENT turns) but has **not been counted empirically** across real traffic.

**Proposed instrumentation** (not implemented in this pass, per the task's "implement only minimal instrumentation... propose otherwise" guidance): have the three un-logged call sites call `common.log_run` with a `"stage"` discriminator, identical in form to the existing two call sites. This is additive logging only — it does not alter tutoring behaviour — and is a concrete, ready-to-implement next step.

## 4. Reliability / controlled-failure testing

Per the task's explicit instruction not to trigger an artificial real-provider outage, controlled failure testing was done with deterministic mocks, which is the correct methodology for this (already covered in depth by the controller-stabilization work, cross-referenced here rather than duplicated):

| Failure condition | Test | Result |
|---|---|---|
| Generation raises an exception mid-episode | `frontend/test_app.py::test_generation_failure_rolls_back_state` | Controller state correctly rolled back, not advanced; retry succeeds exactly once (no duplication) |
| Generation returns empty text, no exception (silent provider outage) | `test_empty_generation_treated_as_failure` | Treated identically to an exception (raises `GenerationFailed` internally) — rolled back |
| Generation fails on the very first turn of a new episode | `test_start_episode_does_not_commit_on_failure` | No episode is silently started; `chat['episode']` remains `None` |
| Real provider fallback (Groq → HF router) | `scripts/llm/test_pipeline.py::test_client_fallback`, `test_client_skips_missing_keys` | Fallback ordering correct; missing-key case degrades to "not ok" rather than crashing |

**Not tested in this pass** (named explicitly, not silently skipped): retrieval/ChromaDB failure, database/file-write failure for `data/students.json`, malformed-but-non-empty model output (e.g. valid text that nonetheless breaks `response_parser`), and session-interruption recovery. These are real gaps in the failure-mode coverage the original MVP plan's Phase 10 describes, not yet closed.

## 5. Log privacy review

`data/llm_runs.jsonl` records the full message list sent to the LLM (including the student's question text and conversation history) and the full generated response, per entry. It does **not** record: API keys, `.env` contents, or any student-identifying field beyond the fixed, non-identifying `STUDENT_ID = "session_user"` string (which is identical for every user in the current single-user MVP, so it carries no actual identifying information). This matches the original plan's §3.13 concern (logging privacy/retention) being still **open** — no retention policy, access control, or redaction has been implemented; this review only confirms what is and isn't currently logged, it does not add any control.

## 6. Limitations

- Latency figures mix the pre- and post-controller-integration period for the reason explained in §1; this is judged low-risk for this specific metric but is stated, not hidden.
- No cold-start-vs-warm-run split was computed (would require knowing which calls were the first in a fresh process, which isn't recorded in the logs).
- No token-usage/cost figures are reported: `llm_client.stream()`'s own docstring states token counts are not captured while streaming ("providers differ on `stream_options` support"), so `prompt_tokens`/`completion_tokens` are null for the vast majority of these streamed entries — confirmed by direct inspection, not assumed.
