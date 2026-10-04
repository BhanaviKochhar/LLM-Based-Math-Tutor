# Component Evaluation — Metric Definitions

**Date:** 2026-10-04. Defines every metric produced by `eval/component_eval/*`. Each metric is scoped to ONE component — this document deliberately does not define any single "overall system accuracy," per the explicit instruction not to mix fundamentally different tasks (controller transitions, retrieval recall, conceptual pedagogy, out-of-scope refusal) into one misleading number.

## Terminology resolution: `verifiable` vs. `system_scorable`

A prior dataset-expansion pass left an ambiguity flagged for resolution: the dataset field `verifiable` and the concept of "the live system can actually compute this" were not the same thing, most visibly for HCF/LCM items.

**Resolution (implemented in `eval/component_eval/scoring_helpers.py`, not by editing any dataset file):**

- **`verifiable`** (existing dataset field, unchanged): this item has one independently-confirmed correct value — a ground-truth claim about the item, checked at dataset-authoring time (via `scripts.llm.verifier._safe_eval` directly, or for HCF/LCM, a raw `sympy.gcd`/`sympy.lcm` call made outside the production verifier). It says nothing about whether the *live system* can currently compute that value.
- **`system_scorable`** (new, scoring-time-only classification, defined only in code — not a new dataset field): `trusted_expression` is non-null, i.e. `scripts.llm.verifier._safe_eval` can actually evaluate it today.
- **`verified_not_system_scorable`**: `verifiable=true` but `trusted_expression=null` — exactly the HCF/LCM case. Reported as its own category, never silently folded into "pass" or "fail."
- **`requires_human_rubric_evaluation`**: `verifiable=false` — conceptual/comparison/real-life items judged against `expected_key_idea`, never forced into a numeric score.

This was the smallest justified change: no dataset file needed editing, since the distinction is fully derivable from two fields every item already has.

---

## C1-A / curriculum-benchmark trusted-computation metrics
*(`arithmetic_eval.py`, `curriculum_benchmark_eval.py`)*

**What is scored:** `scripts.llm.verifier.solve()`'s computation+gating logic, given the item's own pre-recorded `trusted_expression` as a stand-in for a perfect extractor (`extract_fn=lambda q: trusted_expression`). This is **deterministic, offline, zero-cost** — it does NOT exercise the LLM-based extractor (see extraction below for that).

| Metric | Numerator / denominator | Correct means | Unscorable means |
|---|---|---|---|
| `answer_accuracy` | items where the gated computed answer matches `expected_answer` (via `verifier._close`, or string-equality for non-numeric `expected_answer` text) / all `system_scorable` items | Computed value equals expected (including the correct case of both being `None` — a correctly-withheld non-exact division) | n/a — this metric's denominator already excludes unscorable items |
| `parsing_success_rate` | items where `trusted_expression` parses under `verifier._safe_eval` without raising / all `system_scorable` items | No exception; may still mismatch | n/a |
| `by_grade`, `by_topic` / `by_question_type` | same match/n_scorable logic, grouped | — | excluded items are reported in their own `excluded` count per group, never silently folded into a misleadingly low group "n" (a bug caught and fixed during this pass's own development — see the checkpoint report) |

**Deterministic.** No model dependency.

**Known limitation found by this evaluator, not fixed in this pass:** any item whose `trusted_expression` is a BARE fraction string that happens to match the shape `^\d+/\d+$` (e.g. `"3/10"`, `"7/20"`) is caught by `verifier._grade_appropriate_answer`'s non-exact-division withholding rule (`_PLAIN_DIV`) and returns `None`, **even when the item is actually a fraction-to-decimal conversion question, not a division word problem**. This produced real, reproducible mismatches (`ar-020`, `cb-158`). The rule exists to correctly teach quotient+remainder for division word problems like "share 20 toffees among 3 children" — it cannot currently distinguish that framing from "convert 3/10 to a decimal" when both reduce to the identical bare-fraction string. Not fixed here per this task's explicit instruction not to modify the verifier merely to make the benchmark score higher.

---

## C1-B / C1-C — extraction metrics
*(`extraction_eval.py`)*

Two stages, reported separately, never combined into one "extraction accuracy":

| Stage | Dependency | Metric | Correct means |
|---|---|---|---|
| `response_to_answer` | None — deterministic | `exact_match` (numerator = `response_parser.final_number_str(input)` equals `expected_final_answer`) | String-exact match on the normalized token |
| `question_to_expression` | **Live LLM extractor** (`scripts.llm.verifier.compute()` → `llm_client.chat`) | `exact_match`, `normalized_match`, `value_equivalent_match`, `parse_success` | Three DISTINCT comparisons, never conflated: `exact_match` is raw string equality (strict, whitespace-sensitive); `normalized_match` strips whitespace before comparing (the model reliably writes `"2 + 3"`, the dataset records `"2+3"` — these are the same expression, not a mismatch); `value_equivalent_match` additionally accepts any expression that evaluates to the same value via `verifier._safe_eval`/`_close` (e.g. a reordered `"7*2"` vs `"2*7"`). `parse_success` credits a correct `NONE` classification for non-computable questions. |

**`question_to_expression` is never executed automatically.** Running it spends real API calls. `extraction_eval.py`'s default invocation only reports a cost/scope plan (model, call count, estimated latency) and stops; it requires `--live-confirm` to actually run.

**A real bug in this evaluator was caught by actually running it live, not assumed from a dry read:** the first live run reported `exact_match = 3/14` (21%), which looked like a serious extraction regression. It was not — the comparison was raw-string equality, and the model's `"2 + 3"` vs. the dataset's `"2+3"` differ only in whitespace. After adding `normalized_match`/`value_equivalent_match`, the real rate is 13/14 (92.9%), with the sole miss being `ex-007` — a already-documented, expected limitation (the follow-up-resolution case; this evaluator deliberately calls `verifier.compute()` directly, without the conversation-resolution step the live app applies first, so this exact miss is the known, correct behavior for this test harness, not a new defect).

---

## C2 — retrieval metrics
*(`retrieval_eval.py`)*

**What is scored:** `scripts.retrieval.retrieve_with_metadata()`, called live for every query against the real local index (BM25 + ChromaDB — **local compute, no API key, no per-call cost; this is not an LLM evaluation**).

| Metric | Definition | Denominator excludes |
|---|---|---|
| `recall_at_1` / `_3` / `_5` | Fraction of scored queries where a labelled-relevant `(grade, page)` chunk appears in the top-k | Queries with `category` in `{grade_scope_mismatch, out_of_corpus_topic}`, or with no `relevant_chunks` labelled at all |
| `mrr` | Mean of `1/rank` of the first relevant hit, 0 contribution for queries with no hit in the top 5 | Same exclusion set as Recall@k |
| `grade_scope_mismatch_cross_grade_leakage_count` | Of `grade_scope_mismatch` queries specifically, how many returned a chunk from OUTSIDE the grade window `{g, g-1}` | n/a — this is the dedicated check for that excluded category, not folded into Recall@k |
| `needs_review_count` | Queries whose `ambiguity_notes` field contains `NEEDS_REVIEW` | Reported, not excluded — these ARE scored, just flagged |

**Explicitly distinguished, per the task's requirement:**
1. Relevant chunk exists, retrieval finds it → counted in the Recall@k numerator.
2. Relevant chunk exists, retrieval misses it → counted in the Recall@k denominator but not numerator (a real retrieval miss).
3. No relevant chunk exists (`out_of_corpus_topic`) → excluded entirely; "nothing returned" here is success, not a miss.
4. Grade-scope mismatch → excluded from Recall@k; checked separately for cross-grade leakage.
5. Ambiguous/weak query (`NEEDS_REVIEW`) → scored, but flagged in its own count rather than silently blended in.

**A retrieval miss is not a model-correctness failure, and a retrieval hit is not proof of grounded generation** — this evaluator measures retrieval only, as instructed; it has no visibility into what the LLM eventually does with a retrieved chunk.

---

## C3 — controller metrics
*(`controller_eval.py`)*

**What is scored:** DETERMINISTIC controller/state-machine correctness only — never generated prose quality. Method: cross-references `eval/datasets/controller/v1_scenarios.json`'s 25 `scenario_id`s against REAL execution of the project's existing reviewed test suites (`eval/controller_walk.py` via subprocess + output parsing by scenario header; named functions in `frontend/test_app.py` via direct call with an instrumented `check()`). This evaluator does not reimplement controller assertions in a third place.

| Metric | Definition |
|---|---|
| `deterministic_pass_rate` | pass / (pass + fail), among scenarios actually run |
| `excluded_live_llm_required` | Scenarios whose `evidence_type` is `"real provider call"` (ctl-019..023) — not run, not scored pass/fail |
| `excluded_not_implemented` | Scenarios whose `test_reference` is `"none (proposed future work)"` (ctl-024, ctl-025) |

A scenario's pass/fail is "all of its underlying real check() calls passed," traced to the actual named test function or scenario number — not a restatement of the dataset's own `status` field (which this evaluator treats as a claim to verify, not a result to copy).

---

## C4 — personalization metrics
*(`personalization_eval.py`)*

**What is scored:** of the 14-item personalization dataset, exactly 4 items (`pz-003`, `pz-004`, `pz-006`, `pz-014`) describe a mechanism this module can execute directly against `scripts.llm.controller`/`frontend.app` and check deterministically (the level-tuned co-solve threshold difference, hint-vs-reveal independence from level, and give-up handling independence from level). These are **real controller executions**, not assertions copied from the dataset's own claims.

The remaining 10 items describe a **prose-level** difference (explanation depth, terminology register, scaffolding amount) that cannot be checked without live generation plus a human or LLM-judge rubric pass. **No metric is invented for these** — they are preserved in a `*_rubric_queue.json` artifact alongside the result, for a future rubric-evaluation stage, exactly as the task instructs.

| Metric | Definition |
|---|---|
| `pass` / `fail` | Of the 4 deterministically-checked items only |
| `requires_live_generation_and_rubric_judgment` | Count of items deferred to the queue (10 of 14) |

"Personalization quality" in the full sense (does the pedagogical intent actually land) is **not** claimed to be measured by this evaluator for the queued items — only the narrow mechanism facts that happen to be code-verifiable.

---

## Cross-cutting rules applied by every evaluator here

- **No single combined "accuracy" number** is ever computed across components.
- **Exclusions are always itemized with a reason**, never silently dropped from a denominator.
- **A result is "deterministic" only if it genuinely required zero LLM/API calls** — this is recorded explicitly as `config.live_llm_used` in every result artifact.
- **Unit/regression test passing is never reported as a research evaluation result** — `eval/component_eval/test_component_eval.py` tests the EVALUATORS; `arithmetic_eval.py` etc. evaluate the SYSTEM. These are different documents, in different parts of the output, and this distinction is repeated in `docs/component_evaluation.md`.
