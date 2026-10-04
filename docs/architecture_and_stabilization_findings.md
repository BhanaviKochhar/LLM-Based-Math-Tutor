# Architecture and Stabilization Findings

**Date:** 2026-10-04
**Branch:** `final-development`
**Scope:** pre-benchmark stabilization pass — user-facing behavioral audit and fixes, not the 175-question end-to-end benchmark (explicitly not run in this pass).

This document is a fresh, code-read audit of the CURRENT branch (not inherited from `docs/current_state_evaluation.md` or `docs/stabilization_audit.md`, both of which are snapshots from earlier passes and are now partially stale — e.g. both the conceptual-tutoring graduation fix and the `MODE_DIAGNOSE_CORRECT` post-check gap they flag as open are confirmed fixed and committed as of this branch's HEAD before this pass began).

---

## 1. Authoritative live path

```
Student (Streamlit UI, frontend/app.py)
  -> submit_turn -> start_episode / advance_episode
  -> intent.classify_intent (open episode)  OR  pipeline.resolve_conversation (new episode / MATH_FOLLOWUP)
  -> scripts.retrieval.retrieve_with_metadata (gated: only when the router says the turn needs it)
  -> verifier.solve (compute-first; gated: only for a new/modified mathematical problem)
  -> controller.step / controller.start / controller.start_followup (pure state machine)
  -> pipeline.generate_turn -> llm_client.stream (Groq -> HF/nscale -> HF/deepinfra)
  -> verifier.check (trusted-answer check, 3 modes) + verifier.check_self_consistency (all modes, new)
  -> student_tracker.record (gated: only genuine graded attempts)
  -> common.log_run (data/llm_runs.jsonl)
```

## 2. LIVE vs LEGACY vs IMPLEMENTED-BUT-NOT-CONSUMED vs KNOWN LIMITATION vs DEFERRED

### LIVE (what the real app calls now)
- `frontend/app.py`: `start_episode`, `advance_episode`, `_advance_math_followup` (new), `submit_turn`, `_apply_action`, `_post_check`, `_record_outcome`, `clear_chat`/`reset_learning_progress` (new, split out of one inline block).
- `scripts/llm/controller.py`: pure state machine — `start`, `start_followup` (new), `step` (now also handles `CONFUSION`/`CORRECTION`/`CLARIFY`).
- `scripts/llm/intent.py`: classifies open-episode turns; label set expanded from 5 to 9 (added `CONFUSION`, `CORRECTION`, `MATH_FOLLOWUP`, `CLARIFY`).
- `scripts/llm/conversation_resolver.py`: classifies new-episode turns AND, now, `MATH_FOLLOWUP` turns on an open episode (previously only reached at episode start).
- `scripts/llm/verifier.py`: `solve`/`compute`/`check` (trusted-answer path) + `check_self_consistency` (new, bounded guardrail).
- `scripts/llm/hints.py`, `scripts/llm/student_tracker.py`, `scripts/llm/memory.py` (now actually populated — see §3), `scripts/llm/prompt_registry.py`, `scripts/llm/response_parser.py`, `scripts/llm/llm_client.py`, `scripts/retrieval.py`.

### LEGACY (present, not called by the live app)
- `scripts/llm/pipeline.py`: `TutorTurn`, `prepare()`, `resume()`, `ask_tutor()` — the pre-controller Tier A single-shot path. Now explicitly docstring-marked LEGACY; retained only because `scripts/llm/smoke_live.py` still exercises the retrieval/compute/generate/verify round-trip through it as a plumbing smoke test.
- `eval/run_eval.py` + `eval/eval_set.py` — baseline-vs-system comparison that calls through the legacy `TutorTurn` path, not the controller-driven flow. Now explicitly docstring-marked LEGACY, pointing to `eval/component_eval/*` as the authoritative current evaluation entry points.
- `scripts/llm/smoke_live.py` — a plumbing smoke test (retrieval → generation → verify round-trip), not a controller/UX test. Not mistaken for one; it never claimed to be.

### IMPLEMENTED BUT NOT CONSUMED (fixed this pass) / (still not consumed)
- `scripts/llm/memory.py` (`thread_notes`) — **fixed this pass.** Confirmed by a repo-wide grep before any change: `thread_notes` was defined, capped, and rendered into the system prompt by `prompt_registry.build_messages`, but no caller in `frontend/app.py` ever populated or passed it — every live episode's `thread_notes` was always `None`/empty. `_apply_action` now appends a note on every terminal action and threads `chat["thread_notes"]` into `generate_turn`, so a chat's second-and-later episodes get real continuity ("earlier in this session..."). Scope: within one chat/session only; not persisted across chats or app restarts (see Deferred).
- `student_tracker.py`'s `weak_topics` — **still not consumed, left deferred, see §5.** Written and exposed via `stats()`, but nothing reads it to shape tutoring (only the beginner/intermediate/advanced level classification is actually consumed).
- `controller._BTN_AFTER_SOLVED`'s "Practice problem" button — pre-existing, unchanged, already correctly excluded from `_ACTIONABLE_LABELS` (no generator exists to back it; documented known limitation, not a new finding).

### KNOWN LIMITATIONS (intentional, not fixed this pass)
- `verifier.check_self_consistency` only catches an EXPLICIT `"A op B = C"` statement; prose arithmetic with no `=` sign is not checked. Conservative by design (skip, don't guess).
- `retrieval.py`'s RRF fusion always returns top-k with no relevance-score floor; a `use_rag=False` gate (via the router) is what actually prevents garbage retrieval on conversational-repair turns, not a score threshold on retrieval itself. Verified this is sufficient for every path actually exercised (new episode, math follow-up); not rebuilt, per the instruction not to redesign RAG wholesale.
- The division-word-problem-vs-fraction-conversion heuristic in `verifier._looks_like_fraction_conversion` (pre-existing, documented in its own code comment and in `docs/tutoring_fixes_and_limitations.md`) — unaffected by this pass.

### DEFERRED (explicit decision, with justification)
- **`weak_topics` consumption** (Problem 7). The values stored are raw, truncated (30-char) question text, not canonical topic labels — there is no topic taxonomy mapping in the live path today. Wiring this into prompts would be a new feature (deciding what to say, how often, and verifying it doesn't make responses worse) requiring its own evaluation pass, not a bounded bug fix, and the task explicitly asks for the smallest change and no speculative feature additions. Level-based personalization (which IS consumed) already adapts tone/depth. Recommendation for a future pass: canonicalize topics at record time (e.g. map to the NCERT taxonomy in `docs/verified_ncert_class_1_5_topics.md`) before deciding how to surface them.
- **`CONCEPT_FOLLOWUP` as its own routed intent on an open episode.** `intent.py`'s expanded label set covers `CONFUSION`/`CORRECTION`/`MATH_FOLLOWUP`/`CLARIFY` (the four confirmed-broken cases) but not a fifth `CONCEPT_FOLLOWUP` label; a "why does carrying work?" follow-up on an open episode still routes through the existing ATTEMPT path (`diagnose()` returns `"engaged"` → `MODE_ACK_CONCEPTUAL`), which is serviceable (it doesn't invent a new problem or lose context) but doesn't get `conversation_resolver`'s richer "build directly on the previous explanation" directive. Deferred because adding a 10th intent label risks diluting the classifier's accuracy on the already-fixed four without a dedicated evaluation pass to confirm it helps rather than regresses.
- **Cross-chat / cross-restart `thread_notes` persistence.** Fixed within a single chat session (see above); a brand-new chat, or restarting the app, starts with an empty thread. Persisting this would mean a new storage design (today chats live only in `st.session_state`); out of scope for a stabilization pass.
- **Literal in-browser Enter-key confirmation.** The ask bar now uses `st.form` (Streamlit's `enter_to_submit=True` default, confirmed via the installed library's own signature and via a real `AppTest` run showing the `FormSubmitter` button in the render tree). A full browser/Playwright keystroke simulation was not available in this environment (no `chromium-cli`/Playwright installed, Windows host, no project-specific run skill); verified as far as practical without installing a new browser-automation dependency mid-pass.
- **The full 175-question end-to-end benchmark.** Explicitly out of scope for this pass per instructions.

---

## 3. The 12 problem areas — final status

| # | Problem | Present before this pass? | Fixed? | Evidence |
|---|---|---|---|---|
| 1 | No Class 1-5 selector; grade not fully propagated | **Yes** — `ss.grade` hardcoded to 3, no UI control anywhere in `frontend/app.py`; `conversation_resolver`'s router system prompt hardcoded "Class 3" regardless of actual grade | **Yes** | Grade selectbox added to the name/onboarding page; selecting a different class resets any open episode (no stale cross-grade episode survives); `conversation_resolver.resolve_question`/`_llm_route` now take `grade` and the router prompt is templated, not hardcoded. Verified live via `AppTest` (grade selection → `ss.grade` propagates) and via `test_conversation_resolver_deterministic_paths`. |
| 2 | Split conversational routing: new episodes via `conversation_resolver`, open episodes via `intent.py` only (no `MATH_FOLLOWUP` concept) | **Yes** — confirmed by code read; live-reproduced (a value-change mid-episode fell through to ATTEMPT and asked "what answer did you get?") | **Yes** | `intent.py` label set expanded (`CONFUSION`/`CORRECTION`/`MATH_FOLLOWUP`/`CLARIFY`); `advance_episode` routes `MATH_FOLLOWUP` to a new `_advance_math_followup` helper that calls `conversation_resolver` + `controller.start_followup`. Live-verified end to end (real Groq calls) in the mandatory walkthrough, Step 10: the tutor recomputed 245+150=395 and explicitly named the connection to the prior 245+136 problem. |
| 3 | No clarification state for genuinely ambiguous input | **Yes** — no `CLARIFY` concept existed in the live controller-driven path | **Yes** | `controller.MODE_CLARIFY` + `_d_clarify` added; routed from `intent.CLARIFY`. Regression-tested (`test_confusion_correction_clarify_do_not_mutate_state`, `eval/controller_walk.py` scenario 19). |
| 4 | Confusion handled as a generic hint (consumes hint budget) | **Yes** — `intent.py` mapped "I don't understand" to `HINT`, consuming `hints_given` | **Yes** | New `CONFUSION` label + `controller.MODE_CONFUSION`/`_d_confusion`, which re-explains the specific sticking point without touching `hints_given`/`attempts`/phase. Live-verified, Step 9: hints_given stayed at 3 before and after the confusion turn; the tutor re-explained the ones-place carry specifically, without revealing the answer. |
| 5 | "Clear this chat" also erased the persistent learner profile | **Yes** — confirmed by code read (`reset_student()` called directly inside the Clear-chat button handler) | **Yes** | Split into `clear_chat()` (visible chat + episode + in-chat thread notes only) and `reset_learning_progress()` (explicit, requires a Yes/Cancel confirmation step). Verified via `AppTest` (Clear chat does not set the confirmation flag; Reset does) and a unit test asserting `clear_chat` never calls `reset_student`. |
| 6 | UI "Level" and the real backend level are different things sharing one label | **Yes** — right panel's "Level N" was `1 + solved_in_this_chat // 3`; backend `student_tracker.classify()` (beginner/intermediate/advanced) is a separate, real signal that actually drives tutoring | **Yes** | Relabeled to "Chat Progress" (honest about what it measures) and added a new, honestly-labeled "Tutor Level" row sourced directly from `pipeline.resolve_level` (the same function the live pipeline itself uses, so it cannot drift). Verified via `AppTest`. |
| 7 | Weak-topic tracking may be written but never consumed | **Confirmed: written, never consumed** | **Deferred**, see §2 | `student_tracker.weak_topics` is recorded and exposed via `stats()`, but no prompt/hint/retrieval path reads it. Level-based personalization (separate signal) IS consumed. |
| 8 | Cross-episode memory (`thread_notes`) may be disconnected from the live app | **Confirmed disconnected** (repo-wide grep: zero references in `frontend/app.py` before this pass) | **Yes**, within a chat session | `_apply_action` now builds and stores a note on every terminal action; it is forwarded into `generate_turn` for subsequent episodes in the SAME chat. Cross-chat/restart persistence deferred (§2). |
| 9 | Hints may repeat expensive work; fixed-3 vs "real step count" contract was inconsistent | **Yes** — every hint click re-ran `conversation_resolver` + the arithmetic extractor against the ORIGINAL question, even though the open episode already had the resolved question and trusted answer | **Yes** | `pipeline.generate_turn`'s `MODE_HINT` branch now reads `state.question`/`state.computed_answer` directly instead of calling `get_hint()` (which re-resolves). `get_hint()` itself is kept for `smoke_live.py`, now docstring-marked as to why. The "N steps" framing was aspirational, not real (nothing ever computes a per-problem step count); docs/prompts now honestly describe a fixed `MAX_HINTS=3` budget. Also fixed a live-observed truncation bug: `max_tokens=220` was cutting hints off mid-sentence on the reasoning model; raised to 500 and empirically re-verified (Step 6 of the walkthrough, before/after). |
| 10 | Numerical claims outside the 3 verified modes (teach_invite, redirect, hints, diagnose_wrong, ...) are never checked | **Confirmed** — `_post_check` only covers `CO_SOLVE`/`REVEAL`/`DIAGNOSE_CORRECT` | **Yes, bounded guardrail added** | `verifier.check_self_consistency()`: scans generated text for explicit `"A op B = C"` statements the model invented itself and flags (non-blocking) any that don't add up, independent of mode. Wired into `_apply_action` for every mode; surfaced in the UI as a distinct, non-blocking warning tag. Live-verified: ran clean (no false positives) across 12 real model-generated worked examples in the walkthrough; also unit- and live-walkthrough deliberately exercised against a planted wrong equation. |
| 11 | Retrieval may feed irrelevant context on short/ambiguous turns | **Checked, found already correct by construction** | **No fix needed** | `use_rag` is gated by the router at the point RAG would be invoked (new episode and, now, `MATH_FOLLOWUP`); `CONFUSION`/`CORRECTION`/`CLARIFY` on an open episode never call retrieval at all (verified by `test_confusion_correction_clarify_skip_retrieval`, mocking `retrieve_with_metadata` and asserting zero calls). |
| 12 | Legacy/stale paths could be mistaken for the current system | **Confirmed** — `TutorTurn`/`prepare`/`resume`/`ask_tutor`, `eval/run_eval.py`, `eval/eval_set.py` | **Yes, marked (not deleted)** | All five now carry explicit LEGACY docstrings naming the authoritative live/current path. A new regression test (`test_live_app_never_calls_legacy_tier_a_path`) greps `frontend/app.py` for these symbols so a future edit can't silently reintroduce a call to the legacy path without the test suite catching it. |

---

## 4. Two additional defects found ONLY by the mandatory live walkthrough (not visible from code reading or deterministic tests)

Both were found running the real 12-step scenario against the live Groq-backed pipeline (not mocked), fixed, and then **re-run live a second time** to confirm the fix:

1. **Hint 2 truncated mid-sentence** ("Add the ones: 5 + 6 = 11, so write" — nothing after it). Root cause: `hints.py`'s `max_tokens=220` was too small for the reasoning model's hidden "thinking" tokens before its visible answer (the same failure class `verifier.py`'s extractor hit previously at `max_tokens=24`, already fixed there). Fixed: raised to 500. Confirmed on re-run: hint 2 was a complete sentence.
2. **CORRECTION mode leaked the answer.** After "No, that's not what I meant" on a freshly-started follow-up problem (0 attempts, 0 hints — the child had not earned a reveal), the model solved the problem in full and stated the final answer, because `_d_correction`'s directive never told it not to. Fixed: `_d_correction` now explicitly forbids solving/revealing the answer, matching the same explicit prohibition already present in the teach_invite/redirect directives. Confirmed on re-run: the corrected reply walked through the place-value steps but stopped short of stating the combined final number, inviting the child to try it.

---

## 5. Test totals

| Suite | Before this pass | After this pass |
|---|---|---|
| `scripts.llm.test_pipeline` | 91 | **109** |
| `eval.controller_walk` | 47 | **68** |
| `frontend.test_app` | 52 | **91** |
| `eval.validate_datasets` | 74 | 74 (unaffected) |
| **Total** | **264** | **342** |

All four deterministic/offline suites pass with 0 failures at the end of this pass. The mandatory live walkthrough (12 scripted steps, real Groq calls, real retrieval index) was run twice — once establishing the two defects in §4, once confirming both fixes — and is not part of the deterministic suite (it costs real API calls and is not reproducible byte-for-byte due to model sampling).
