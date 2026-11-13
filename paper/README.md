# Paper tables and figures

Everything in this folder is generated from saved results; nothing here is typed by hand. To rebuild it (no API calls):

```
python -m eval.paper_metrics        # reads transcripts, judge verdicts and ratings; writes eval/results/paper_metrics_<time>_<commit>.json + .md
python -m eval.make_paper_outputs   # reads the newest result files below; writes paper/tables/*.tex and paper/figures/*.pdf|png
```

`make_paper_outputs` always reads the newest file of each kind in `eval/results/`; each result file name ends with the commit it was built from, so the paper's numbers trace to one commit.

## Sources

| Output | Built by | Reads |
|---|---|---|
| `tables/datasets.tex` | `eval/make_paper_outputs.py` | fixed set sizes (see `eval/datasets/`) |
| `tables/main_results.tex` | `eval/make_paper_outputs.py` | the newest `eval/results/paper_metrics_*.json` |
| `tables/rubric.tex` | `eval/make_paper_outputs.py` | the same paper metrics file |
| `tables/scope.tex` | `eval/make_paper_outputs.py` | the same paper metrics file |
| `tables/reading_pedagogy.tex` | `eval/make_paper_outputs.py` | the same paper metrics file |
| `tables/agreement.tex` | `eval/make_paper_outputs.py` | the paper metrics file; the newest `eval/results/judge_calibration_*.json` |
| `tables/components.tex` | `eval/make_paper_outputs.py` | the paper metrics file; the newest `retrieval_eval_*`, `curriculum_benchmark_eval_*`, `arithmetic_eval_*`, `controller_eval_*` and `personalization_eval_*` results |
| `figures/fig_main_outcomes.*` | `eval/paper_figures.py` | the paper metrics file |
| `figures/fig_out_of_scope.*` | `eval/paper_figures.py` | the paper metrics file |
| `figures/fig_rubric.*` | `eval/paper_figures.py` | the paper metrics file |
| `figures/fig_controller.*` | `eval/paper_figures.py` | the paper metrics file |
| `figures/fig_latency.*` | `eval/paper_figures.py` | the paper metrics file |

## What the paper metrics file is built from

| Input | Location |
|---|---|
| Baseline transcripts (tag `paper-eval-v1`) | `eval/results/baseline_runs/` |
| Tiny Thinker transcripts (tag `paper-eval-v2`) | `eval/results/system_runs_v2/` |
| Judge verdicts (`qwen/qwen3.8-27b`; on SVAMP only for the replies the rules scored wrong or found no answer in) | `eval/results/judge_runs/` |
| Blind ratings by two team members | `eval/blind_ratings/` |
| Held-out ambiguous and everyday reading | `eval/results/held_out_ambiguous_reading.json` |
| Pilot interaction log | `data/llm_runs.jsonl` |

Item-by-item readings cited in the text: `eval/results/verifier_wrong_value_reading.json`, `eval/results/cosolve_timing_reading.json`, `eval/results/retrieval_miss_reading.json`.

`eval/reference_v1_vs_v2.py` and its result files are for the team's reference only and feed no table or figure.

## Extra standard measures (`tables/extra/`, `figures/extra/`)

```
python -m eval.retrieval_ablation     # local only: the retriever with each part removed
python -m eval.extra_metrics          # reads the newest paper_metrics result plus transcripts, verdicts and ratings
python -m eval.make_extra_outputs     # writes paper/tables/extra/*.tex and paper/figures/extra/*.pdf|png
```

| Output | Reads |
|---|---|
| `tables/extra/accuracy_breakdown.tex`, `figures/extra/fig_accuracy_by_class.*` | `eval/results/extra_metrics_*.json` (accuracy) |
| `tables/extra/effect_sizes.tex` | extra metrics (effect sizes) |
| `tables/extra/scope_classifier.tex` | extra metrics (scope classifier) |
| `tables/extra/controller_per_action.tex`, `figures/extra/fig_controller_confusion.*` | extra metrics (controller) |
| `tables/extra/agreement_extended.tex` | extra metrics (agreement) |
| `tables/extra/rubric_effects.tex` | extra metrics (rubric effects) |
| `tables/extra/latency_detail.tex`, `figures/extra/fig_latency_split.*` | extra metrics (latency) |
| `tables/extra/mathdial_damr.tex`, `figures/extra/fig_mathdial_damr.*` | extra metrics (MathDial); mistake location and actionability from `eval/results/judge_runs/*_mathdial_extra.jsonl` (`eval/judge_mistake_extra.py`) |
| `tables/extra/retrieval_measures.tex`, `tables/extra/retrieval_by_group.tex`, `figures/extra/fig_retrieval_variants.*` | `eval/results/retrieval_ablation_*.json` |
