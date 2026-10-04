# Tutoring Flow Fixes, Hint Lifecycle, and Personalization Review

**Date:** 2026-10-04. Covers issue reproduction, root causes, fixes, and remaining limitations for the tutoring-flow/hint-lifecycle/personalization/verifier work in this pass. All findings below were independently reproduced against the current code or a live run in this pass, not assumed from an earlier report.

## A1 — Broad curriculum question handling ("Addition of 3 digit")

**Reproduced live:** confirmed — a broad method question (`is_math=False`, nothing for the verifier to extract) produced only a one-sentence analogy, no worked example, because `controller._d_teach_invite`'s directive explicitly said *"NO numbered steps"* and *"ONE tiny everyday example... in a sentence"* — regardless of whether there was a specific answer to protect.

**Root cause:** the directive text did not distinguish "teach me a method" (no specific answer to protect — a worked example doesn't give anything away) from "solve my specific problem" (an answer to protect, by design).

**Fix:** `scripts/llm/controller.py` — `_d_teach_invite` now branches on `state.is_math`. When `is_math=False` (broad/conceptual opening), the directive requires naming the method and showing one complete worked example with real steps, using the tutor's own chosen numbers. When `is_math=True` (a specific computable problem), the original withhold-and-invite behavior is unchanged.

**Verified live:** "Addition of 3 digit" now produces a genuine column-addition worked example (units → tens → hundreds, with carrying named) before inviting an attempt.

**Regression tests:** `eval/controller_walk.py` scenario 17.

## A2 — "Show me how"

**Reproduced live:** confirmed — "Show me how" maps to the `SOLVE` intent (`frontend/app.py::_LABEL_TO_INTENT`); on a fresh episode with zero attempts, `controller._handle_solve` takes the "cold" branch (`MODE_REDIRECT`), whose directive said only *"explain the key idea a DIFFERENT, simpler way"* — no requirement to actually demonstrate the method.

**Fix:** `_d_redirect` now also branches on `is_math`. For a broad/conceptual opening there is no specific answer to protect, so the request is honoured directly with the same worked-example directive as A1. For a specific computable problem, the redirect still protects that problem's own answer, but now requires an actual worked numeric example with different numbers, not a vague rephrasing.

**Verified live:** "Show me how" on "Addition of 3 digit" now produces a real worked demonstration (method name + steps). **Residual observation, not fixed:** the content of this response and A1's teach_invite response were quite similar in the live smoke test (both use the same conceptual directive) — a child who gets this explanation twice in a row (once unprompted, once via "Show me how") may see largely the same worked example twice. Not addressed in this pass (would need the directive to track "already shown a worked example this episode" — a larger state change than this pass's scope).

**Regression tests:** `eval/controller_walk.py` scenario 18.

## A3 — "I don't understand"

**Reproduced live — and found a more fundamental root cause than expected.** Reading `frontend/app.py::advance_episode` confirmed: once an episode is active (not brand new), the student's free text is classified ONLY by `scripts/llm/intent.py`'s 5-label classifier (ATTEMPT/HINT/SOLVE/GIVE_UP/NEW_QUESTION) — `conversation_resolver`'s CONFUSION/CORRECTION/CONCEPT_FOLLOWUP routing (and the directive text strengthened below) is **only ever reached when starting a brand-new episode**, never for a turn inside an already-open one.

Worse: `intent.py`'s own `_SYSTEM` prompt explicitly listed *"don't understand"* as a `GIVE_UP` trigger. A live smoke-test turn of "I dont understand" was classified `GIVE_UP`, which **ends the episode** via `MODE_CO_SOLVE` — a full worked solution using *different* numbers, nothing to do with what the child was confused about. This is a worse failure mode than "restarts a generic explanation" — it silently closes the conversation.

**Fix (two parts):**
1. `scripts/llm/intent.py` — `_SYSTEM` prompt and few-shot examples updated to explicitly classify confusion ("I don't understand", "I don't get it", "I'm confused") as `HINT` (keep going, more help), distinct from genuine stop-trying phrases ("I don't know", "this is too hard"), which remain `GIVE_UP`.
2. `_KEYWORDS` (the deterministic fallback used only if the LLM call fails) updated the same way, checked before `GIVE_UP` so overlapping phrasing resolves to the keep-going reading.
3. `scripts/llm/pipeline.py`'s `_conversation_directive` CONFUSION-mode text was also strengthened (isolate the specific step, offer a smaller example, ask a targeted clarifying question if genuinely unclear) — but per the finding above, **this code path is only reached for the first turn of a new episode**, not for confusion expressed mid-episode. That gap is documented, not fixed, below.

**Verified live:** re-running the smoke test's "I don't understand" turn after the fix classifies it as `HINT` (confirmed via the deterministic keyword-fallback regression test; the live-LLM path depends on the model honoring the updated system prompt, which was not independently re-verified beyond the one live smoke-test turn already captured before the fix — see Known limitations).

**Regression tests:** `scripts/llm/test_pipeline.py::test_intent_keyword_fallback` (new, 10 assertions; `intent.py` previously had zero test coverage anywhere in this project).

**Known limitation, not fixed in this pass:** mid-episode confusion now gets routed to `HINT` (a real, grounded next-level hint, per `hints.py`'s existing escalation design) rather than ending the episode — a genuine improvement — but it does **not** specifically "isolate the likely difficult step" from the child's own wording the way the strengthened CONFUSION directive does; it just advances the normal hint ladder. Building a true confusion-aware re-explanation reachable mid-episode would require a new controller mode and directive, which is a larger change than this pass's "fix only the smallest justified part" scope. Flagged for a future pass.

## B — Hint lifecycle (A4–A8)

**Reproduced:** confirmed exactly as described. `controller.step()`'s old `HINT` branch did `state.hints_given += 1` unconditionally, then capped only the *displayed* `hint_number` at `min(state.hints_given, 3)`. Every click past the 3rd re-requested "Hint 3 of 3" from the model forever — a wasted live call each time, producing a near-duplicate of the same "final step" hint.

**Fix (`scripts/llm/controller.py`):**
- New `MAX_HINTS = 3` constant and `MODE_HINT_EXHAUSTED` mode.
- `step()`'s `HINT` branch now checks `state.hints_given >= MAX_HINTS` **before** incrementing; once exhausted, returns `MODE_HINT_EXHAUSTED` with a **fixed, non-generated** message (`HINT_EXHAUSTED_MESSAGE`) and buttons `["I'll try", "Just show me"]` — `"Another hint"` is dropped. `hint_number` is now always exactly `state.hints_given` (A4: state-driven, never LLM-influenced, and now correctly bounded).
- `scripts/llm/pipeline.py::generate_turn` and `frontend/app.py::_run_generation` updated so `MODE_HINT_EXHAUSTED` never reaches the LLM (A6/A7).
- `frontend/app.py::render_turn` renders the exhaustion message.

**A8 (repeated clicks):** the existing commit-only-after-success pattern (`advance_episode`'s `trial_state` copy) already prevents a failed/duplicate submission from double-incrementing `hints_given`; verified by a regression test rather than assumed.

**Verified live:** the smoke test's Hints 1→2→3→exhausted sequence showed real escalating hints ("think about what's being asked" → "set up the columns" → "add the hundreds, including the carry") followed by the fixed exhaustion message with no further model call.

**Regression tests:** `eval/controller_walk.py` scenarios 15–16 (pure controller: numbering, progression, exhaustion, idempotent repeat, failure+retry state integrity); `frontend/test_app.py::test_hint_lifecycle_integration` (integration-level: H1/H2/H3 text, exhaustion with an instrumented `hints.generate_hint` proving zero further LLM calls, repeated click, hint-specific generation failure + retry).

## C — Shortcuts

Inspected per the task's instruction before adding anything. The controller's `step()` only recognizes five intents (`ATTEMPT/HINT/SOLVE/GIVE_UP/NEW_QUESTION`); there is no existing mechanism for "explain more simply," "check my answer" (redundant with `ATTEMPT`), "another example" (no example-generator exists — the same documented gap as the existing, deliberately-unimplemented "Practice problem" button), or "why does this work" (would need new conceptual-explanation plumbing). **No new shortcuts were added.** Each candidate either duplicates an existing intent or requires a real new capability beyond this pass's scope — exactly the condition under which the task says not to add one.

## D — Personalization

Re-inspected the actual current mechanism (not assumed from the dataset's existence):

- **Storage:** `data/students.json`, one record per `student_id`, written atomically (`scripts/llm/student_tracker.py::_save`).
- **Update:** `student_tracker.record()`, called from `frontend/app.py::_record_outcome` only for genuine graded attempts (confirmed correct and already tested).
- **Level determination:** `student_tracker.classify()` — a recent-window (last 5 attempts, minimum 3 before leaving "intermediate") rule, fully deterministic.
- **Consumption:** `pipeline.resolve_level()` → `prompt_registry`'s per-level style blocks (explanation depth/terminology) and `controller._COSOLVE_AFTER` (co-solve threshold: beginner/intermediate=2, advanced=3).
- **Connected to the live path:** yes, confirmed by direct execution (not just code reading) in the preceding evaluation pass's `personalization_eval.py` — 4/4 deterministic mechanism checks pass again in this pass, unchanged.

**Findings from this pass's re-inspection:**
- `state.level` is fixed once at episode `start()` and never re-read mid-episode. This is a deliberate design (avoids jarring tone changes mid-conversation), not a bug — verified by reading `step()`, which never reassigns `state.level`.
- `STUDENT_ID = "session_user"` is still a single hardcoded constant (`frontend/app.py`), so personalization state is shared across all open chat tabs in the same browser session. This is the already-documented single-user MVP scope limitation, not a new finding, and authentication/multi-student separation is explicitly out of scope for this pass.
- No genuine current-path propagation bug was found (no incorrect level being used, no lost context across turns within the mechanism actually wired up). The task's suspicion of "learner context being lost across turns" did not reproduce against the current code for the wired-up mechanism; the real personalization gap remains what the preceding pass already documented — 10 of 14 personalization dataset items describe prose-level differences that need live generation plus rubric judgment, preserved in `eval/results/personalization_eval_*_rubric_queue.json`, not invented as a deterministic score.

## E — Verifier fraction-vs-division disambiguation

**Reproduced:** confirmed exactly as previously found — `verifier._grade_appropriate_answer` withholds any bare `"int/int"`-shaped expression as a non-exact division (quotient+remainder framing), with no way to tell "Convert 7/20 to a decimal" apart from "Share 20 toffees among 3 children" once both have reduced to a bare fraction string — because the function never saw the original question text.

**Fix (`scripts/llm/verifier.py`):** `_grade_appropriate_answer` now accepts an optional `question` parameter; `solve()` passes the real question text through. A new `_looks_like_fraction_conversion()` keyword check (`decimal`, `as a fraction`, `convert`, `simplify`, etc.) exempts genuine fraction/decimal-conversion questions from the withholding rule. `eval/component_eval/scoring_helpers.py::score_trusted_computation` updated to pass the item's actual `question` field (previously it only had the bare expression) so the fix also applies in component evaluation, not just the live app.

**Verified:** `ar-020` and `cb-158` (and generalized phrasing patterns, not the literal case IDs) now resolve correctly; ordinary exact and non-exact division word problems are unaffected (explicitly regression-tested).

**Known limitation, documented not fixed:** this is a keyword heuristic, not semantic understanding. An adversarial phrasing like *"Share 45 rupees among 8 people. Round to 2 decimal places if needed."* contains "decimal" in an unrelated sense (rounding instructions) and is incorrectly treated as a conversion question. Narrowing the regex to exclude this one case risks new false negatives elsewhere; not attempted. Covered by a regression test that documents the limitation explicitly rather than hiding it.

## F — HCF/LCM and scorability semantics

No change needed beyond what the preceding evaluation pass already established: `eval/component_eval/scoring_helpers.py` already distinguishes `verifiable` (ground truth independently confirmed, possibly outside the production verifier) from `system_scorable` (the live verifier can compute it today) as a **scoring-time classification**, not a dataset field. HCF/LCM items remain `verified_not_system_scorable` in every result artifact — never counted toward `answer_accuracy`, never reported as "verifier-supported." The verifier's arithmetic grammar was **not** extended to cover HCF/LCM in this pass (that would require a separate, explicitly justified implementation task, not a metric-improvement shortcut).

## G — Retrieval / corpus issues

No code change in this pass (retrieval code was not touched, so `retrieval_eval.py` was not re-run — its last result from the preceding pass stands unchanged). Reviewed as instructed:
- The two corpus discrepancies (Class 2 3D-shape terminology appearing only at grade 5 in this corpus; Class 4 Data Handling/pictograph terminology absent entirely) remain open evidence-quality questions, not resolved here, and the curriculum taxonomy (`docs/verified_ncert_class_1_5_topics.md`) was **not** modified, per instruction.
- Curriculum validity, corpus support, and retrieval success remain three separately tracked attributes (per `docs/curriculum_coverage_matrix.md` and `docs/metric_definitions.md`) — not conflated.

## H — Legacy baseline (`eval/run_eval.py` / `eval/eval_set.py`)

Inspected, not executed. Findings (consistent with, and re-confirmed independently of, the earlier audit):
- `eval/run_eval.py` calls `prompt_registry.build_messages()` and `llm_client.chat()` **directly** — it does not go through `scripts.llm.controller` at all. It predates the controller-driven architecture (commit `b3b2a03`, before the controller-integration stabilization).
- It therefore does **not** exercise the current live tutoring path (`frontend.app` → `controller.step()` → `pipeline.generate_turn`) that this pass's fixes (hint lifecycle, teach_invite/redirect branching, intent classification) all live in.
- **It cannot be reused as-is for a controller-aware baseline.** A fresh baseline harness that drives the real `frontend.app`/`controller` path (not a reimplementation of the old single-shot prompt flow) would be needed before any full-system comparison is meaningful. This is **not** attempted in this pass, per the explicit instruction not to start the baseline experiment.

## Live evaluation completed vs. pending

- **Completed:** `question_to_expression` extraction (14 items, Groq free tier, `openai/gpt-oss-120b`) — see `eval/results/extraction_eval_20261004T115716Z_788406afa9.json`. Result: 13/14 value-equivalent match; the sole miss (`ex-007`) is the already-documented follow-up-resolution limitation, not a new defect. **A genuine bug in the evaluator's own comparison logic was found and fixed during this run** (see `docs/metric_definitions.md`): the first attempt reported exact_match=3/14 purely from whitespace formatting differences ("2 + 3" vs "2+3"), not real extraction failures; corrected by adding `normalized_match`/`value_equivalent_match` metrics.
- **Completed:** a ~9-turn manual smoke test of the live backend (`frontend.app`, real Groq calls) replicating the task's listed walkthrough steps — see the checkpoint report for observations. This environment has no browser, so this is the backend-level equivalent of the UI walkthrough, not literal browser clicks.
- **Still pending (not attempted, per the stop condition):** any live-LLM evaluation of the 10 prose-dependent personalization items or the 70 rubric-queued curriculum-benchmark items; any full-system baseline run.
