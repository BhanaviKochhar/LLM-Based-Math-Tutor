# Component Evaluation Framework

**Date:** 2026-10-04. Covers `eval/component_eval/*`, built to measure the current system's components reliably before any full-system baseline comparison (that comparison is explicitly a later, separate stage — see `eval/run_eval.py` and the "Not in scope" section below).

## What this is, and what it is not

| | This framework (`eval/component_eval/`) | Deterministic regression tests | Full-system baseline |
|---|---|---|---|
| Example | `arithmetic_eval.py` | `eval/controller_walk.py`, `scripts/llm/test_pipeline.py`, `frontend/test_app.py`, `eval/validate_datasets.py` | `eval/run_eval.py` |
| Measures | How well a real component performs against labelled data | Whether specific code behaves as designed (pass/fail assertions) | Full pipeline (retrieval + controller + generation + verification) vs. a baseline, on the same questions |
| Output | A timestamped result artifact with metrics, per-example results, exclusions | Pass/fail count, no persisted artifact | A result artifact (pre-existing convention) |
| A passing run means | The component scored well on this data | The code behaves as its author intended | — |
| Treated as | Component evaluation result | Regression test result | Formal research experiment |

**These three are never conflated.** A regression test passing is never reported as evidence a component is "effective" — it only means the code does what its own author asserted it does. Component evaluation results are the actual measurements against labelled data.

## Evaluators

| Evaluator | Measures | Dataset(s) consumed | Live LLM? |
|---|---|---|---|
| `arithmetic_eval.py` | Verifier computation+gating correctness, given a known-good expression | `arithmetic/v1_starter.jsonl`, `v2_phaseB_extension.jsonl` | No |
| `curriculum_benchmark_eval.py` | Same, across the 175-item Class 1-5 benchmark; preserves rubric items | `curriculum_benchmark/v1_class1..5.jsonl` | No |
| `extraction_eval.py` | `response_to_answer` parsing (deterministic); `question_to_expression` extraction (live, gated) | `extraction/v1_starter.jsonl`, `v2_extended.jsonl` | Only `question_to_expression`, and only with `--live-confirm` |
| `retrieval_eval.py` | Recall@1/3/5, MRR, grade-scope leakage | `retrieval/v1_starter.jsonl`, `v2_extended.jsonl` | No (local BM25+ChromaDB) |
| `controller_eval.py` | Deterministic controller state-machine correctness | `controller/v1_scenarios.json` + real execution of `eval/controller_walk.py` / `frontend/test_app.py` | No |
| `personalization_eval.py` | 4 mechanism-verifiable personalization facts; queues the rest | `personalization/v1_starter.jsonl` | No |

## Exact commands

```bash
# C1 — trusted computation (deterministic, offline)
python -m eval.component_eval.arithmetic_eval
python -m eval.component_eval.curriculum_benchmark_eval

# C1 — extraction: deterministic stage runs; live stage only plans by default
python -m eval.component_eval.extraction_eval
python -m eval.component_eval.extraction_eval --live-confirm   # spends real API calls -- see cost plan first

# C2 — retrieval (deterministic, local-only, no API key needed)
python -m eval.component_eval.retrieval_eval

# C3 — controller (deterministic; runs the real existing test suites as subprocesses/direct calls)
python -m eval.component_eval.controller_eval

# C4 — personalization (deterministic subset only)
python -m eval.component_eval.personalization_eval

# Tests of the evaluators themselves (not the tutor)
python -m eval.component_eval.test_component_eval
```

## Metrics produced

See `docs/metric_definitions.md` for the exact definition, numerator/denominator, and known limitations of every metric. Metrics are never combined across components into one "overall accuracy."

## How unscorable/ambiguous cases are handled

Every item is classified before scoring, using `eval/component_eval/scoring_helpers.classify_item`:
- **`system_scorable`** — has a `trusted_expression`; scored normally.
- **`verified_not_system_scorable`** — `verifiable=true` but no `trusted_expression` (e.g. HCF/LCM); excluded from accuracy, reported in its own count, never silently dropped.
- **`requires_human_rubric_evaluation`** — `verifiable=false` (conceptual/comparison/real-life items); preserved in a `*_rubric_queue.json` artifact alongside the main result, for a future rubric-based pass, never discarded.

Retrieval queries with `category` in `{grade_scope_mismatch, out_of_corpus_topic}`, or with no labelled `relevant_chunks`, are excluded from Recall@k/MRR (this is the CORRECT outcome for those categories, not a miss) and reported separately.

Controller scenarios requiring a live LLM call, or with no implementation yet, are excluded with a stated reason, never silently skipped.

## Where results are stored

`eval/results/<evaluator_name>_<UTC timestamp>_<short commit>.json`, plus a same-stem `.md` human-readable summary, and (for evaluators with a rubric queue) a same-stem `_rubric_queue.json`. Filenames are never reused — `results.write_result()` raises `FileExistsError` rather than overwrite an existing path (tested in `test_component_eval.py` by forcing a real collision, not simulating one).

Every result JSON contains: `evaluator_name`, `run_timestamp_utc`, `git` (commit, branch, dirty flag), `environment` (Python version, platform), `dataset_sources` (path + version + item count for every file read), `config` (model/provider if applicable, retrieval config, `live_llm_used` flag), `aggregate_metrics`, `exclusions` (with reasons), `execution_errors`, `notes`, and the full `per_example_results`.

## What configuration is captured

- Git commit hash, branch, and whether the working tree was dirty at run time.
- Python version and platform.
- Exact dataset file paths, their version (filename stem), and item counts actually read.
- Whether any live LLM call was made (`config.live_llm_used`), and if so, model/provider/call count.
- The retrieval configuration used (retriever module, `top_k`).

## What remains outside the scope of component evaluation

- **Full-system baseline comparison** (baseline LLM vs. the complete system on the same questions) — a separate, later stage; `eval/run_eval.py` already exists for this and was not modified or re-run here.
- **Live-LLM question-to-expression extraction accuracy** — the runner exists (`extraction_eval.py --live-confirm`) but was not executed in this pass; see the checkpoint report for the cost/scope plan pending approval.
- **Personalization prose quality** (10 of 14 items) — requires live generation plus human or LLM-judge rubric scoring, not attempted here; preserved in a queue artifact.
- **Curriculum-benchmark rubric items** (70 of 175 items: conceptual/comparison/real-life/misconception/ambiguous) — preserved in a queue artifact, not scored.
- **Ablation studies, evidence-driven implementation changes, deployment, or paper claims** — none of these were started, per the task's explicit stop condition.
