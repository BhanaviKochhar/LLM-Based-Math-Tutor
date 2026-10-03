# Evaluation Plan

This is the execution plan for evaluating Tiny Thinker's mathematical correctness, retrieval quality, controller behaviour, and tutoring effectiveness. It operationalizes `LLM_Math_Tutor_MVP_to_Final_Capstone_Plan.md` Phases D-F and `LLM_Math_Tutor_Paper_First_Execution_Priority.md` Phases D-G against the controller-integration baseline established in this checkpoint (see `docs/development_test_log.md`).

**This document defines the protocol and the starter datasets. It does not itself contain final results.** The only existing real experimental evidence is the preliminary 36-question arithmetic comparison in `data/eval_baseline_vs_system.json` (`eval/eval_set.py`) plus the diagnostic observations recorded in this checkpoint. Running the full protocol below against a frozen configuration is the next phase of work, not something this document claims has happened.

---

## 1. Dimensions and existing evidence

| Dimension | Existing evidence | This checkpoint's contribution |
|---|---|---|
| Arithmetic correctness | 36-question baseline-vs-system comparison (preliminary; `eval/eval_set.py`) | `eval/datasets/arithmetic/v1_starter.jsonl` — 15 new cases targeting gaps the 36-set doesn't cover (equivalent-fraction acceptance, remainder framing, an explicitly unverifiable case) |
| Expression extraction | None (not previously isolated from final-answer correctness) | `eval/datasets/extraction/v1_starter.jsonl` — 14 cases across the extractor (`verifier.compute`) and the response parser (`response_parser.final_number_str`), separately. 2 of 7 `response_to_answer` cases **already fail** against the current implementation — see §2.2. |
| Retrieval quality | None (no labelled benchmark existed) | `eval/datasets/retrieval/v1_starter.jsonl` — 10 queries, each independently verified against the real corpus and the live retriever; see §2.3 for the small-sample Recall/MRR figures and their explicit limitations |
| Controller/disclosure | `eval/controller_walk.py` (27 deterministic checks, pre-existing) + 7 new deterministic/mocked tests from this checkpoint (`frontend/test_app.py`) | `eval/datasets/controller/v1_scenarios.json` — traceability index over all 25 scenarios (deterministic, mocked, live-smoke, and known-gap) |
| Conceptual tutoring / reasoning recognition | None | `eval/datasets/conceptual/v1_starter.jsonl` — 9 cases with a rubric (§3), seeded from an observed live conversation; 2 cases have documented live observations showing the current system does NOT meet the rubric |
| Multi-turn tutoring | None | `eval/datasets/multi_turn/v1_starter.json` — 6 full conversations, 4 live-smoke-tested, 1 fully reconstructed from the observed "fractions" conversation |
| Latency/reliability | `data/llm_runs.jsonl` (331 entries, mixed architectures/models, no per-stage breakdown) | §4 below: gap analysis + a concrete, not-yet-implemented instrumentation proposal |

---

## 2. Deterministic and automatable metrics

### 2.1 Arithmetic correctness

Run via a script in the style of `eval/run_eval.py`, against `eval/datasets/arithmetic/v1_starter.jsonl` (new) and `eval/eval_set.py` (existing, kept as-is — **not replaced**).

- **Metric:** exact-match rate against `expected_answer` (or any of `accepted_equivalents`), using `verifier._close` for numeric equivalence (so `3/9` and `1/3` compare equal, etc.).
- For `verifiable: false` cases: metric is "did the system correctly decline to assert a single checkable value", not correctness of a number.
- Report separately: (a) the existing 36-question baseline-vs-system comparison (label it "preliminary", as already done in `data/eval_baseline_vs_system.json`), (b) the new starter set, by `topic`.

### 2.2 Expression / answer extraction

Two sub-metrics, kept separate per the task's own instruction not to let a correct final answer conceal a wrong intermediate extraction:

- **Expression-extraction accuracy** (`question_to_expression` rows): extracted expression (via `verifier.compute`, with the real `_default_extractor`) matches `expected_expression` or one of `expected_expression_equivalents`, evaluated for mathematical equivalence (not string equality) via `verifier._close`.
- **Response-parsing accuracy** (`response_to_answer` rows): `response_parser.final_number_str(input)` matches `expected_final_answer`.

**Already measured in this checkpoint** (deterministic, no LLM needed — `response_to_answer` cases don't call the extractor): 5/7 correct. The 2 failures (`ex-009`, `ex-010`) reproduce the documented `response_parser.py` fallback defect — when there is no explicit `Answer:` line, `final_number_str` falls back to the *first* number anywhere in the text rather than the actual final/last one. This is a real, quantified instance of the gap flagged in the original repository audit, not a new finding, but it is now measurable:

```
python -c "
from scripts.llm import response_parser as rp
import json
rows = [json.loads(l) for l in open('eval/datasets/extraction/v1_starter.jsonl', encoding='utf-8') if l.strip()]
rows = [r for r in rows if r['stage'] == 'response_to_answer']
correct = sum(1 for r in rows if rp.final_number_str(r['input']) == r['expected_final_answer'])
print(f'{correct}/{len(rows)} correct')
"
```
→ `5/7 correct` (run on this checkpoint's commit).

`question_to_expression` rows require a live LLM call to `verifier.compute`'s extractor and were **not** run in this checkpoint (would consume API calls and the task explicitly asked not to spend resources beyond what's needed to stabilize the checkpoint) — flagged as the next concrete action.

### 2.3 Retrieval (small starter sample — explicitly not representative)

Metrics: Recall@1, Recall@3, MRR, computed only over queries with a non-empty `relevant_chunks` list and category NOT in `{grade_scope_mismatch, out_of_corpus_topic}` (see dataset schema's scoring convention).

**From the 8 scorable queries in `v1_starter.jsonl`** (ran live in this checkpoint, see `docs/development_test_log.md`):

| Metric | Value (n=8) |
|---|---|
| Recall@1 | 3/8 = 0.375 |
| Recall@3 | 5/8 = 0.625 |
| MRR | 3.83/8 ≈ 0.479 |

**This is a diagnostic sample, not a benchmark result.** It is 8 hand-picked queries chosen specifically to span query-specificity categories (bare word, short conceptual, specific conceptual, paraphrase, curriculum-specific) after a single topic (fractions) was flagged by the behavioural review — it is not a random or stratified sample of curriculum queries, and must not be cited as "the system's retrieval recall." Its value is in the *pattern* it demonstrates: the 2 misses (`rq-001`, `rq-002`) are both single-word-or-short conceptual queries, while the 2 perfect hits (`rq-003`, `rq-004`) are longer, more specific phrasings of the same underlying topic — motivating the recommendation in §5 to measure retrieval performance *as a function of query length/specificity*, not just as one aggregate number. A properly stratified, larger (target: ≥50 query) benchmark across grades and topics is Phase D3/E4 future work, not delivered here.

### 2.4 Controller state-transition correctness

Already fully deterministic and passing: `eval/controller_walk.py` (27/27) + `frontend/test_app.py` (34/34, of which `ctl-012` through `ctl-018` in the scenario catalog are the new ones from this checkpoint). No further dataset work needed here beyond keeping `eval/datasets/controller/v1_scenarios.json` updated as new scenarios are added. Intent-classification accuracy against a labelled free-text set (as opposed to button-bypassed, deterministic intents) is a **named gap** (`ctl-025`) with no dataset yet.

---

## 3. Conceptual tutoring rubric

Used for `eval/datasets/conceptual/v1_starter.jsonl` and the conversation-level scoring of `eval/datasets/multi_turn/v1_starter.json`. This is a **manual or model-assisted** rubric, not a deterministic check — a generated response cannot be scored by exact string match. Keep ratings for the same response from multiple raters (or rater + model-assisted check) to compute agreement before trusting a score.

| Dimension | 1 (low) | 3 (medium) | 5 (high) |
|---|---|---|---|
| `mathematical_correctness` | States or implies a false mathematical claim. | Mathematically correct but misses a relevant subtlety (e.g. doesn't flag an equivalent-but-different-form answer). | Fully correct and precise, including handling equivalent forms correctly. |
| `relevance_to_latest_input` | Response could have been generated without reading the student's last message at all. | Response engages with the general topic of the last message but not its specific content/numbers. | Response directly references the specific content of the student's last message. |
| `recognition_of_demonstrated_reasoning` | Ignores or contradicts correct reasoning the student just demonstrated. | Implicitly consistent with the student's reasoning but doesn't name it. | Explicitly names and confirms/builds on the student's specific reasoning. |
| `appropriate_scaffolding` | Either reveals the answer with no attempt required, or gives no usable help at all. | Gives generic help not tailored to where the student actually is. | Gives help precisely matched to the stated difficulty/misconception. |
| `context_preservation` | Response is inconsistent with or contradicts the established conversation (e.g. references the wrong prior turn). | Response doesn't contradict prior context but also doesn't use it. | Response correctly and specifically builds on prior turns. |
| `clarity_and_age_appropriateness` | Uses vocabulary/structure inappropriate for the stated grade. | Mostly appropriate with minor lapses. | Consistently simple, concrete, grade-appropriate language. |
| `avoidance_of_unnecessary_repetition` | Repeats a prior explanation/example near-verbatim. | Some overlap with a prior turn but adds something new. | Clearly distinct from every prior turn in this episode. |
| `appropriate_progression` | Conversation is stuck — no path toward resolution after several turns. | Some forward movement but slow/indirect. | Clearly advances toward a concrete, resolvable exercise or closure. |

**Protocol:** for each case, two independent raters (or one rater plus a documented LLM-as-judge pass, clearly labeled as such) score each `rubric_dimensions_most_relevant` dimension 1/3/5 against the case's `essential_elements` / `must_avoid` lists, then report simple agreement (exact match rate) before aggregating. **Do not rely on an LLM-as-judge score alone as evidence of tutoring quality** — if used, it must be validated against a human-rated subsample first, and that validation step must itself be reported.

---

## 4. Latency and reliability

### Current state (verified, not assumed)

`data/llm_runs.jsonl` has 331 entries (2026-07-20 to 2026-10-03; `python -c "import json; print(len(open('data/llm_runs.jsonl').readlines()))"` → 331) with `latency_s`, `provider`, `model_id`, `finish_reason`, and `attempts` (fallback trail) populated on 326/331 rows. But:

1. **Only two call sites are logged** (`common.log_run`, called from `pipeline.TutorTurn._log` and `pipeline.TurnStream._log`). The conversation resolver (`conversation_resolver._llm_route`), the expression extractor (`verifier._default_extractor`), and the intent classifier (`intent._llm_classify`) all call `llm_client.chat()` directly and are **not logged at all** — so per-stage latency (resolution vs. extraction vs. generation) cannot currently be computed from existing logs, only total generation latency.
2. **The log mixes architectures.** `model` values include `gpt-oss-120b`, `llama3.3-70b`, `qwen3-32b` (the one-off model-pilot comparison) alongside `tutor-pipeline`/`tutor-turn` (the actual production call sites) spanning a 2.5-month period that includes pre-controller-integration code. Any latency conclusion must filter to `model in ("tutor-pipeline", "tutor-turn")` and a specific date/commit range — not reported wholesale here, since doing so would conflate materially different architectures.

### Proposed instrumentation (not implemented in this checkpoint)

Minimal, additive change: have `conversation_resolver.resolve_question`, `verifier.compute`, and `intent.classify_intent` each call `common.log_run` (or a new, equally lightweight `common.log_stage` using the same JSONL file with a `"stage"` field) around their LLM calls, exactly mirroring the existing pattern in `pipeline.py`. This does not alter tutoring behaviour — it is pure logging — and is a concrete, ready-to-implement follow-up, deliberately not done in this checkpoint to keep this pass focused on controller stabilization and evaluation-framework preparation rather than new code changes.

### Protocol once instrumented

- Per-stage latency: resolver, retrieval, extraction, generation — mean/median/P95, filtered by `model` and commit/date.
- Number of LLM calls per user turn (currently: up to 3 — resolver, extractor, generator — for a new math question; fewer for follow-ups where `use_rag`/`use_verifier` is false).
- Error/timeout rate and retry behaviour: `llm_client`'s own fallback trail (`attempts` field) already provides this for the generation call; extend the same capture to the other two call sites once logged.
- Separate cold-start (first call after process start, e.g. ChromaDB connection) from warm-run measurements.

---

## 5. Recommended future improvements (not implemented here)

For each: the failure mode it addresses, the component responsible, the dataset/scenario that measures it, the primary metric, and required regression tests. **None of these are implemented or claimed as implemented in this checkpoint.**

| Improvement | Addresses | Component | Dataset | Primary metric | Regression tests needed |
|---|---|---|---|---|---|
| Query-length-aware retrieval (e.g. query expansion for short/bare-topic queries) | Cases `rq-001`, `rq-002` (short queries retrieve irrelevant chunks) | `scripts/retrieval.py` | `eval/datasets/retrieval` (expanded, stratified by query length) | Recall@3, MRR by query-length bucket | Existing `rq-003`/`rq-004` must not regress |
| `response_parser.final_number_str` fallback hierarchy (explicit Answer line → final equation → final numerical statement → unverifiable) | `ex-009`, `ex-010` (first-number fallback picks up an early distractor number) | `scripts/llm/response_parser.py` | `eval/datasets/extraction` (`response_to_answer` rows) | Response-parsing accuracy | All existing `test_pipeline.py` response_parser assertions |
| Equivalent-fraction vs. quantity-answer distinction | `co-001`, `ar-008` (3/9 vs 1/3 vs the quantity 3) | `scripts/llm/controller.py` (`diagnose`) and/or `verifier.py` | `eval/datasets/conceptual` co-001, `eval/datasets/arithmetic` ar-008 | Manual rubric: `mathematical_correctness`, `recognition_of_demonstrated_reasoning` | `eval/controller_walk.py` unaffected (pure addition, not a change to existing transitions) |
| Conceptual-episode progression (a path from a broad topic to a concrete, gradable exercise) | `co-003`, `co-007`, `co-008`, `ctl-012` | `scripts/llm/controller.py` (new state/mode), `scripts/llm/pipeline.py` | `eval/datasets/conceptual`, `eval/datasets/multi_turn` mt-004 | Manual rubric: `appropriate_progression` | All of `eval/controller_walk.py` (this changes state-machine structure, highest-risk item on this list) |
| Cross-turn attribution correctness (respond to the right prior turn) | `co-002` A/B comparison (new directive referenced the wrong turn) | prompt assembly / `active_turns` ordering in `prompt_registry.py` | `eval/datasets/multi_turn` mt-004 | Manual rubric: `context_preservation` | None identified yet; needs investigation before a fix is designed |
| Per-stage latency instrumentation | Missing telemetry, §4 | `common.py`, `conversation_resolver.py`, `verifier.py`, `intent.py` | N/A (infrastructure) | N/A | None (additive logging only) |

---

## 6. Execution procedure (for the next phase, once run)

For every evaluation run, record: git commit SHA, branch, model/provider configuration (`llm_client.DEFAULT_MODEL` and fallback target), dataset file + its own version (filename), evaluation script version (git SHA), environment, date, and raw per-item results alongside the summary — exactly the experiment-record shape already described in `LLM_Math_Tutor_MVP_to_Final_Capstone_Plan.md` §7. Write outputs to `eval/results/<dimension>.json` (directory does not yet exist — created on first real run, not pre-populated with placeholder files in this checkpoint).
