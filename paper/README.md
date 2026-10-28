# Paper tables and figures

Everything in this folder is generated from saved results; nothing here is typed by hand. To rebuild it (no API calls):

```
python -m eval.paper_metrics        # reads transcripts, judge verdicts and ratings; writes eval/results/paper_metrics_<time>_<commit>.json + .md
python -m eval.make_paper_outputs   # reads the newest result files below; writes paper/tables/*.tex and paper/figures/*.pdf|png
```

`make_paper_outputs` always reads the newest file of each kind in `eval/results/`. The numbers in the paper come from tag `paper-results`, whose files are listed here.

## Sources

| Output | Built by | Reads |
|---|---|---|
| `tables/datasets.tex` | `eval/make_paper_outputs.py` | fixed set sizes (see `eval/datasets/`) |
| `tables/main_results.tex` | `eval/make_paper_outputs.py` | `eval/results/paper_metrics_20261028T044505Z_e2af2ef29b.json` |
| `tables/rubric.tex` | `eval/make_paper_outputs.py` | the same paper metrics file |
| `tables/scope.tex` | `eval/make_paper_outputs.py` | the same paper metrics file |
| `tables/reading_pedagogy.tex` | `eval/make_paper_outputs.py` | the same paper metrics file |
| `tables/agreement.tex` | `eval/make_paper_outputs.py` | the paper metrics file; `eval/results/judge_calibration_20261025T071302Z_d6f9d81bfb.json` |
| `tables/components.tex` | `eval/make_paper_outputs.py` | the paper metrics file; `eval/results/retrieval_eval_20261023T180901Z_eec1643166.json`, `curriculum_benchmark_eval_20261024T083156Z_e55f69912c.json`, `arithmetic_eval_20261024T083152Z_e55f69912c.json`, `controller_eval_20261024T083233Z_e55f69912c.json`, `personalization_eval_20261024T083237Z_e55f69912c.json` |
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
| Judge verdicts (`qwen/qwen3.8-27b`) | `eval/results/judge_runs/` |
| Blind ratings by two team members | `eval/blind_ratings/` |
| Held-out ambiguous and everyday reading | `eval/results/held_out_ambiguous_reading.json` |
| Pilot interaction log | `data/llm_runs.jsonl` |

Item-by-item readings cited in the text: `eval/results/verifier_wrong_value_reading.json`, `eval/results/cosolve_timing_reading.json`, `eval/results/retrieval_miss_reading.json`.

`eval/reference_v1_vs_v2.py` and its result files are for the team's reference only and feed no table or figure.
