"""eval/reference_v1_vs_v2.py -- REFERENCE ONLY, not used in the paper: the
system's first full run (tag paper-eval-v1, eval/results/system_runs/) against the
final system (paper-eval-v2, eval/results/system_runs_v2/) on the same items.

The paper compares baseline with the final system only (decided 2026-10-28).
This file keeps the before-and-after numbers for the team's own reference, so
they can be reported later if that decision changes. Its output goes to
eval/results/reference_v1_vs_v2_*.json + .md and feeds no paper table or figure.

Run:  python -m eval.reference_v1_vs_v2
"""
from __future__ import annotations

import json
from collections import Counter

from eval.component_eval.results import write_result, write_summary_markdown
from eval.paper_metrics import (CURRICULUM, DATA, RUNS, _action_match, expected_oos_behavior, items_of, paired_binary,
                                rate, refused, score_item)
from eval.score_transcripts import _load_checkpoint


def v1_runs(stem: str) -> dict:
    return _load_checkpoint(RUNS / "system_runs" / f"{stem}.jsonl")


def v2_runs(stem: str) -> dict:
    return _load_checkpoint(RUNS / "system_runs_v2" / f"{stem}.jsonl")


def correctness(stem: str) -> dict:
    items, a, b = items_of(stem), {}, {}
    for src, dst in ((v1_runs(stem), a), (v2_runs(stem), b)):
        for i, it in items.items():
            j = src.get(i)
            if j and j.get("turns"):
                s = score_item(it, j)
                if s.get("correct") is not None:
                    dst[i] = bool(s["correct"])
    # paired_binary labels its sides baseline/system; here they mean v1/v2.
    return paired_binary(a, b)


def main() -> None:
    res = {"note": "baseline/system keys inside each paired row mean v1/v2 here"}
    res["correctness"] = {stem: correctness(stem) for stem in CURRICULUM + ["out_of_scope"]}
    allv1 = {f"{s}/{i}": v for s in CURRICULUM for i, v in
             {i: bool(score_item(it, v1_runs(s)[i])["correct"]) for i, it in items_of(s).items()
              if i in v1_runs(s) and v1_runs(s)[i].get("turns") and score_item(it, v1_runs(s)[i]).get("correct") is not None}.items()}
    allv2 = {f"{s}/{i}": v for s in CURRICULUM for i, v in
             {i: bool(score_item(it, v2_runs(s)[i])["correct"]) for i, it in items_of(s).items()
              if i in v2_runs(s) and v2_runs(s)[i].get("turns") and score_item(it, v2_runs(s)[i]).get("correct") is not None}.items()}
    res["curriculum_all"] = paired_binary(allv1, allv2)
    oos = items_of("out_of_scope")
    res["out_of_scope_outcomes"] = {
        label: {exp: dict(Counter(score_item(it, rr[i]).get("outcome") for i, it in oos.items()
                                  if i in rr and rr[i].get("turns") and expected_oos_behavior(it) == exp))
                for exp in ("answer", "gloss", "decline")}
        for label, rr in (("v1", v1_runs("out_of_scope")), ("v2", v2_runs("out_of_scope")))}
    fr = {}
    for label, loader in (("v1", v1_runs), ("v2", v2_runs)):
        flags = [refused(loader(s)[i]) for s in CURRICULUM for i in items_of(s) if i in loader(s) and loader(s)[i].get("turns")]
        fr[label] = rate(sum(flags), len(flags))
    res["false_refusal_curriculum"] = fr
    convs = {c["conversation_id"]: c for c in json.load(open(DATA / "multi_turn.json", encoding="utf-8"))["conversations"]}
    res["controller_action_match"] = {"v1": _action_match(convs, v1_runs("multi_turn"))["overall"],
                                      "v2": _action_match(convs, v2_runs("multi_turn"))["overall"]}

    pct = lambda r: f"{100 * r['rate']:.1f}% ({r['k']}/{r['n']})"
    c = res["curriculum_all"]
    lines = ["# REFERENCE ONLY -- system v1 vs v2 (not used in the paper)", "",
             f"- Curriculum correctness: v1 {pct(c['baseline'])}, v2 {pct(c['system'])}, McNemar p = {c['mcnemar_p']:.3f}"]
    for stem, r in res["correctness"].items():
        lines.append(f"  - {stem}: v1 {pct(r['baseline'])}, v2 {pct(r['system'])}")
    lines += [f"- Out-of-scope outcomes: {res['out_of_scope_outcomes']}",
              f"- Curriculum false refusals: v1 {pct(fr['v1'])}, v2 {pct(fr['v2'])}",
              f"- Controller expected action taken: v1 {pct(res['controller_action_match']['v1'])}, "
              f"v2 {pct(res['controller_action_match']['v2'])}"]
    print("\n".join(lines))
    path = write_result("reference_v1_vs_v2", dataset_sources=[{"path": str(DATA)}], config={"reference_only": True},
                        per_example_results=[], aggregate_metrics=res,
                        notes="REFERENCE ONLY: system v1 vs v2; not used in the paper.")
    write_summary_markdown(path, lines)
    print(f"\nRaw: {path}")


if __name__ == "__main__":
    main()
