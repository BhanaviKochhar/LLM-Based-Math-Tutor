"""eval/rating_agreement.py -- quality and agreement of the blind human
ratings in eval/blind_ratings/ (two raters, the same 150 replies).

Quality checks that do not depend on trusting either rater:
  - completeness (blank cells);
  - straight-lining (one value dominating a 1-5 column);
  - objective accuracy: on numeric items the correct answer is known, so a
    rater's "answer correct?" is compared with eval/answer_extraction.py's
    verdict where the code could decide;
  - contradictions ("answer correct = No" with correctness 5; a
    hallucination flag without a quoted claim).
Agreement: Cohen's kappa for categorical columns, quadratic-weighted kappa
for the 1-5 rubric columns. Gate: kappa at least 0.6 between the raters on
the hallucination flag, weighted kappa at least 0.5 on rubric scores.

    python -m eval.rating_agreement
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

from openpyxl import load_workbook

from eval import answer_extraction
from eval.baseline_runner import _item_id, load_items
from eval.component_eval.results import write_result, write_summary_markdown
from eval.score_transcripts import _load_checkpoint, ground_truth_candidates

ROOT = Path(__file__).resolve().parent.parent
HR = ROOT / "eval" / "blind_ratings"
COLS = ["row", "class", "msg", "convo", "truth", "reply", "committed", "correct", "key_idea",
        "teaches", "correctness", "grade_fit", "clarity", "restraint", "halluc", "quote", "notes"]
RUBRIC = ["correctness", "grade_fit", "clarity", "restraint"]


def load_sheet(rater: str) -> list[dict]:
    """Rows in sheet-row order. A rater may have re-sorted the sheet, so rows
    are matched by their 'row' number, never by position."""
    ws = load_workbook(HR / f"rating_sheet_rater_{rater}.xlsx", data_only=True)["Ratings"]
    rows = [dict(zip(COLS, r)) for r in ws.iter_rows(min_row=2, values_only=True) if r and r[0] is not None]
    return sorted(rows, key=lambda x: int(x["row"]))


def norm(v) -> str:
    return str(v).strip().lower() if v not in (None, "") else ""


def cohen_kappa(a: list, b: list) -> float | None:
    pairs = [(x, y) for x, y in zip(a, b) if x != "" and y != ""]
    if not pairs:
        return None
    n = len(pairs)
    po = sum(x == y for x, y in pairs) / n
    ca, cb = collections.Counter(x for x, _ in pairs), collections.Counter(y for _, y in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def weighted_kappa(a: list, b: list, k: int = 5) -> float | None:
    pairs = [(int(x), int(y)) for x, y in zip(a, b) if str(x).strip() and str(y).strip()]
    if not pairs:
        return None
    n = len(pairs)
    w = lambda i, j: ((i - j) ** 2) / ((k - 1) ** 2)
    obs = sum(w(x, y) for x, y in pairs) / n
    ca, cb = collections.Counter(x for x, _ in pairs), collections.Counter(y for _, y in pairs)
    exp = sum(ca[i] * cb[j] * w(i, j) for i in ca for j in cb) / (n * n)
    return 1.0 if exp == 0 else 1 - obs / exp


def code_verdicts(key_rows: list[dict]) -> dict[int, bool | None]:
    """eval/answer_extraction.py's verdict for each numeric-stratum row."""
    datasets = {g: {_item_id(i): i for i in load_items(ROOT / f"eval/datasets/curriculum_benchmark_class{g}.jsonl")}
                for g in range(1, 6)}
    out = {}
    for k in key_rows:
        if k["stratum"] != "numeric":
            continue
        g = next(g for g, d in datasets.items() if k["item_id"] in d)
        item = datasets[g][k["item_id"]]
        ck = _load_checkpoint(ROOT / f"eval/results/{k['condition']}_runs/curriculum_benchmark_class{g}.jsonl")
        text = ck[k["item_id"]]["turns"][-1].get("response") or ""
        out[k["row"]] = answer_extraction.judge(answer_extraction.committed_answer(text),
                                                ground_truth_candidates(item), item["question"])
    return out


def main() -> None:
    key = json.load(open(HR / "rating_key.json", encoding="utf-8"))["rows"]
    sheets = {r: load_sheet(r) for r in "AB"}
    verdicts = code_verdicts(key)
    lines, metrics = ["# Human rating quality and agreement", ""], {}

    for r, rows in sheets.items():
        m = {"rows": len(rows)}
        m["blank_cells"] = sum(norm(x[c]) == "" for x in rows for c in COLS[6:15])
        m["dominant_share"] = {c: round(collections.Counter(norm(x[c]) for x in rows).most_common(1)[0][1] / len(rows), 2)
                               for c in RUBRIC}
        decided = [(x, verdicts[x["row"]]) for x in rows if verdicts.get(x["row"]) is not None
                   and norm(x["correct"]) in ("yes", "no")]
        m["objective_agreement"] = (sum((norm(x["correct"]) == "yes") == v for x, v in decided), len(decided))
        m["contradictions"] = [x["row"] for x in rows if norm(x["correct"]) == "no" and norm(x["correctness"]) == "5"]
        m["flag_without_quote"] = [x["row"] for x in rows if norm(x["halluc"]) == "yes" and not norm(x["quote"])]
        m["hallucination_flags"] = sum(norm(x["halluc"]) == "yes" for x in rows)
        metrics[f"rater_{r}"] = m
        a, n = m["objective_agreement"]
        lines += [f"## rater {r}",
                  f"- blank cells: {m['blank_cells']}; most common value share per rubric column: {m['dominant_share']}",
                  f"- 'answer correct?' agrees with the code's verdict on {a}/{n} numeric replies",
                  f"- contradictions (correct = No but correctness 5): {m['contradictions'] or 'none'}",
                  f"- hallucination flags: {m['hallucination_flags']}; flags without a quote: {m['flag_without_quote'] or 'none'}", ""]

    A, B = sheets["A"], sheets["B"]
    agree = {c: cohen_kappa([norm(x[c]) for x in A], [norm(x[c]) for x in B])
             for c in ("correct", "key_idea", "teaches", "halluc")}
    agree.update({c: weighted_kappa([x[c] for x in A], [x[c] for x in B]) for c in RUBRIC})
    metrics["agreement"] = agree
    lines.append("## agreement between the raters (Cohen's kappa; rubric: quadratic-weighted)")
    for c, v in agree.items():
        lines.append(f"- {c}: {v:.2f}" if v is not None else f"- {c}: n/a")
    disagree = [(a["row"], a["halluc"], b["halluc"], a["quote"] or b["quote"]) for a, b in zip(A, B)
                if norm(a["halluc"]) != norm(b["halluc"])]
    metrics["hallucination_disagreements"] = disagree
    lines += ["", "## rows where the raters disagree on hallucination"] + \
             [f"- row {r}: A={x}, B={y}; quote: {str(q)[:120]}" for r, x, y, q in disagree]
    print("\n".join(lines))
    path = write_result("rating_agreement", dataset_sources=[{"path": str(HR)}], config={},
                        per_example_results=[], aggregate_metrics=metrics,
                        notes="Human rating quality checks and inter-rater agreement.")
    write_summary_markdown(path, lines)
    print(f"\nRaw: {path}")


if __name__ == "__main__":
    main()
