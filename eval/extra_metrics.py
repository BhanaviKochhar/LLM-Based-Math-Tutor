"""eval/extra_metrics.py -- standard measures beyond the headline paper metrics,
computed from the same saved transcripts, verdicts and ratings (no API calls):

  accuracy      scorable / strict accuracy, error rate, micro vs macro over
                classes, and accuracy by class and question type with a paired
                McNemar test per stratum (Holm-adjusted within each breakdown)
  effect_sizes  for every paired yes/no comparison: the 2x2 counts, the
                discordant odds ratio c/b with its log-normal 95% interval
                (0.5 added to both cells when one is 0), and Cohen's g
  scope_classifier  the scope gate as a binary classifier (positive = needs
                maths beyond Class 5, must be stopped): confusion matrix,
                precision, recall, specificity, false-positive rate, F1,
                balanced accuracy and MCC, on the main and held-out sets
  controller    expected action x action taken over the multi-turn turns:
                confusion matrix, per-action precision / recall / F1, macro-F1
  agreement     beside Cohen's kappa: percent agreement (exact and within one
                point), Gwet's AC1 (yes/no labels) and Krippendorff's alpha
                (nominal for yes/no, ordinal for 1-5 scores)
  rubric_effects  matched-pairs rank-biserial correlation for each Wilcoxon test
  latency       P50 / P90 / P95, time before vs during generation, model calls
                per turn (SVAMP clean turns)
  mathdial_damr the MRBench desired-annotation match rate on five dimensions;
                mistake location and actionability come from
                eval/judge_mistake_extra.py and are judge-only (exploratory)

Headline figures it re-uses (scope rates, the paired results) are read from the
newest eval/results/paper_metrics_*.json, so both files always agree.

Run:  python -m eval.extra_metrics
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict

import numpy as np
from scipy.stats import rankdata

from eval import answer_extraction
from eval.component_eval.results import write_result, write_summary_markdown
from eval.paper_metrics import (CURRICULUM, DATA, JUDGE, ROOT, RUNS, SVAMP_N, _expected_mode, correctness,
                                holm, items_of, median_ci, paired_binary, rate, runs, verdicts)
from eval.rating_agreement import RUBRIC, cohen_kappa, load_sheet, norm, weighted_kappa
from eval.score_transcripts import _load_checkpoint, ground_truth_candidates


def latest_paper_metrics() -> dict:
    return json.load(open(sorted(RUNS.glob("paper_metrics_2*.json"))[-1], encoding="utf-8"))["aggregate_metrics"]


# --------------------------------------------------------------------------- accuracy
def accuracy() -> dict:
    per = {"baseline": {}, "system": {}}
    how = {"baseline": Counter(), "system": Counter()}
    strata = {}
    for stem in CURRICULUM:
        c = correctness(stem)
        for cond in per:
            per[cond].update({f"{stem}/{i}": v for i, v in c["_per_item"][cond].items()})
            how[cond].update(c["decided_by"][cond])
        for i, it in items_of(stem).items():
            strata[f"{stem}/{i}"] = (int(stem[-1]), it.get("question_type") or "unknown")
    n_items = sum(len(items_of(s)) for s in CURRICULUM)
    pooled = paired_binary(per["baseline"], per["system"])
    out = {"items": n_items, "paired": pooled}
    for cond in per:
        scored = sum(v for k, v in how[cond].items() if k != "not_scorable")
        right = sum(per[cond].values())
        out[cond] = {"decided_by": dict(how[cond]), "scorable": rate(scored, n_items),
                     "accuracy_scorable": rate(right, len(per[cond])), "error_rate": 1 - right / len(per[cond]),
                     "strict_accuracy_all_items": rate(right, n_items)}
    for key, idx in (("by_class", 0), ("by_question_type", 1)):
        rows = {}
        for s in sorted({v[idx] for k, v in strata.items() if k in pooled_ids(per)}, key=str):
            ids = {k for k, v in strata.items() if v[idx] == s}
            rows[str(s)] = paired_binary({k: v for k, v in per["baseline"].items() if k in ids},
                                         {k: v for k, v in per["system"].items() if k in ids})
        holm(rows, key="mcnemar_p")
        out[key] = rows
    for cond in per:
        accs = [out["by_class"][g][cond]["rate"] for g in out["by_class"]]
        out[cond]["macro_accuracy_over_classes"] = float(np.mean(accs))
        out[cond]["micro_accuracy"] = pooled[cond]["rate"]
    # SVAMP by class (classes assigned by eval/svamp_prep.py)
    sv_ids = set(list(items_of("svamp"))[:SVAMP_N])
    sv = correctness("svamp", sv_ids)["_per_item"]
    sv_class = {i: it.get("grade") for i, it in items_of("svamp").items()}
    rows = {}
    for g in sorted({sv_class[i] for i in sv_ids if sv_class.get(i)}):
        ids = {i for i in sv_ids if sv_class.get(i) == g}
        rows[str(g)] = paired_binary({k: v for k, v in sv["baseline"].items() if k in ids},
                                     {k: v for k, v in sv["system"].items() if k in ids})
    holm(rows, key="mcnemar_p")
    out["svamp_by_class"] = rows
    return out


def pooled_ids(per: dict) -> set:
    return set(per["baseline"]) & set(per["system"])


# --------------------------------------------------------------------------- effect sizes for paired yes/no
def discordant_effects(p: dict, higher_is_better: bool = True) -> dict:
    b, c = p["only_baseline"], p["only_system"]
    bb, cc = (b + 0.5, c + 0.5) if (b == 0 or c == 0) else (b, c)
    odds = cc / bb
    se = math.sqrt(1 / bb + 1 / cc)
    g = abs(c / (b + c) - 0.5) if b + c else 0.0
    size = "negligible" if g < 0.05 else "small" if g < 0.15 else "medium" if g < 0.25 else "large"
    return {"n": p["n"], "both": p["both"], "only_baseline": b, "only_system": c, "neither": p["neither"],
            "discordant_odds_ratio_system_vs_baseline": odds,
            "odds_ratio_ci95": [math.exp(math.log(odds) - 1.96 * se), math.exp(math.log(odds) + 1.96 * se)],
            "zero_cell_correction": bb != b or cc != c, "cohens_g": g, "cohens_g_size": size,
            "mcnemar_p": p["mcnemar_p"], "higher_is_better": higher_is_better}


def effect_sizes(m: dict) -> dict:
    sv, md, hr = m["svamp"], m["mathdial"], m["human_ratings"]
    rows = {"curriculum_correct": (m["curriculum_all"], True),
            "svamp_correct": (sv["official_labels"], True),
            "svamp_correct_without_debatable": (sv["without_debatable"], True),
            "out_of_scope_handled": (m["out_of_scope"]["overall"], True),
            "mathdial_answer_handed_over": (md["answer_revealed_extractor"], False),
            "mathdial_names_mistake": (md["judge_mistake_identified"], None),
            "hallucination_flagged_by_both": (hr["hallucination_both"], False),
            "hallucination_flagged_by_either": (hr["hallucination_either"], False)}
    return {k: discordant_effects(p, hib) for k, (p, hib) in rows.items()}


# --------------------------------------------------------------------------- scope gate as a classifier
def classifier(tp: int, fn: int, fp: int, tn: int) -> dict:
    div = lambda a, b: a / b if b else None
    p, r = div(tp, tp + fp), div(tp, tp + fn)
    spec = div(tn, tn + fp)
    den = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    return {"tp": tp, "fn": fn, "fp": fp, "tn": tn, "precision": p, "recall": r, "specificity": spec,
            "false_positive_rate": div(fp, fp + tn), "f1": div(2 * p * r, p + r) if p is not None and r else 0.0,
            "balanced_accuracy": (r + spec) / 2 if r is not None and spec is not None else None,
            "mcc": (tp * tn - fp * fn) / den if den else 0.0,
            "accuracy": (tp + tn) / (tp + fn + fp + tn)}


def scope_classifier(m: dict) -> dict:
    out = {}
    for cond in ("baseline", "system"):
        s = m["scope"][cond]
        rec, fr = s["recall_out_of_scope"], s["false_refusal_all_in_scope"]
        out[cond] = classifier(rec["k"], rec["n"] - rec["k"], fr["k"], fr["n"] - fr["k"])
    ho = m["held_out"]["out_of_scope"]
    st, ans = ho["stopped_beyond_class_5"], ho["answered_in_scope_probes"]
    out["system_held_out"] = classifier(st["k"], st["n"] - st["k"], ans["n"] - ans["k"], ans["k"])
    return out


# --------------------------------------------------------------------------- controller confusion
def controller() -> dict:
    convs = {c["conversation_id"]: c for c in json.load(open(DATA / "multi_turn.json", encoding="utf-8"))["conversations"]}
    rr = runs("system", "multi_turn")
    pairs = []
    for cid, c in convs.items():
        j = rr.get(cid)
        if not j or not j.get("turns"):
            continue
        for exp_t, got in zip(c["turns"], j["turns"]):
            exp = _expected_mode(exp_t.get("expected_controller_action") or "")
            if exp is None:
                continue
            taken = got.get("mode") or "gloss"
            if {exp, taken} == {"reveal", "co_solve"}:   # accepted as each other, as in the headline score
                taken = exp
            pairs.append((exp, taken))
    labels = sorted({e for e, _ in pairs}, key=lambda x: -sum(1 for e, _ in pairs if e == x))
    taken_labels = labels + sorted({t for _, t in pairs} - set(labels))
    matrix = {e: {t: sum(1 for a, b in pairs if a == e and b == t) for t in taken_labels} for e in labels}
    per = {}
    for lab in labels:
        tp = matrix[lab][lab]
        support = sum(matrix[lab].values())
        predicted = sum(1 for _, t in pairs if t == lab)
        p = tp / predicted if predicted else 0.0
        r = tp / support if support else 0.0
        per[lab] = {"support": support, "predicted": predicted, "precision": p, "recall": r,
                    "f1": 2 * p * r / (p + r) if p + r else 0.0}
    big = [l for l in labels if per[l]["support"] >= 10]
    return {"turns": len(pairs), "accuracy": sum(1 for e, t in pairs if e == t) / len(pairs),
            "labels_expected": labels, "labels_taken": taken_labels, "confusion": matrix, "per_action": per,
            "macro_f1_all": float(np.mean([per[l]["f1"] for l in labels])),
            "macro_f1_support_10_plus": float(np.mean([per[l]["f1"] for l in big])),
            "weighted_f1": sum(per[l]["f1"] * per[l]["support"] for l in labels) / len(pairs)}


# --------------------------------------------------------------------------- agreement beyond kappa
def krippendorff_alpha(a: list, b: list, level: str) -> float | None:
    units = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not units:
        return None
    cats = sorted({v for u in units for v in u})
    idx = {c: i for i, c in enumerate(cats)}
    o = np.zeros((len(cats), len(cats)))
    for x, y in units:
        o[idx[x], idx[y]] += 1
        o[idx[y], idx[x]] += 1
    n_c = o.sum(axis=1)
    n = n_c.sum()

    def delta(i: int, j: int) -> float:
        if level == "nominal":
            return 0.0 if i == j else 1.0
        lo, hi = min(i, j), max(i, j)
        return (n_c[lo:hi + 1].sum() - (n_c[i] + n_c[j]) / 2) ** 2   # ordinal

    d = np.array([[delta(i, j) for j in range(len(cats))] for i in range(len(cats))])
    do = (o * d).sum() / n
    de = (np.outer(n_c, n_c) * d).sum() / (n * (n - 1))
    return float(1 - do / de) if de else None


def gwet_ac1(a: list, b: list) -> float | None:
    units = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not units:
        return None
    cats = sorted({v for u in units for v in u})
    if len(cats) < 2:
        return 1.0
    pa = sum(x == y for x, y in units) / len(units)
    pi = {c: (sum(x == c for x, _ in units) + sum(y == c for _, y in units)) / (2 * len(units)) for c in cats}
    pe = sum(p * (1 - p) for p in pi.values()) / (len(cats) - 1)
    return float((pa - pe) / (1 - pe)) if pe < 1 else None


def _score(v) -> int | None:
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def agreement_block(a: list, b: list, kind: str) -> dict:
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    out = {"n": len(pairs), "percent_agreement": sum(x == y for x, y in pairs) / len(pairs)}
    if kind == "binary":
        out.update({"cohen_kappa": cohen_kappa([x for x, _ in pairs], [y for _, y in pairs]),
                    "gwet_ac1": gwet_ac1(a, b), "krippendorff_alpha_nominal": krippendorff_alpha(a, b, "nominal")})
    else:
        out.update({"within_one_point": sum(abs(x - y) <= 1 for x, y in pairs) / len(pairs),
                    "weighted_kappa": weighted_kappa([x for x, _ in pairs], [y for _, y in pairs]),
                    "krippendorff_alpha_ordinal": krippendorff_alpha(a, b, "ordinal")})
    return out


def agreement() -> dict:
    key = {k["row"]: k for k in json.load(open(ROOT / "eval/blind_ratings/rating_key.json", encoding="utf-8"))["rows"]}
    sheets = [{int(x["row"]): x for x in load_sheet(r)} for r in ("A", "B")]
    a, b = ([s[row] for row in sorted(key)] for s in sheets)
    out = {"main_sheet": {"hallucination": agreement_block([norm(x["halluc"]) == "yes" for x in a],
                                                           [norm(x["halluc"]) == "yes" for x in b], "binary")}}
    for d in RUBRIC:
        out["main_sheet"][d] = agreement_block([_score(x[d]) for x in a], [_score(x[d]) for x in b], "ordinal")
    from eval.paper_metrics import _mathdial_sheet
    mkey = {k["row"]: k for k in json.load(open(ROOT / "eval/blind_ratings/mathdial_key.json", encoding="utf-8"))["rows"]}
    ms = [_mathdial_sheet(r) for r in ("A", "B")]
    yn = lambda v: str(v or "").strip().lower() == "yes"
    jv = {c: verdicts(c, "mathdial_sample") for c in ("baseline", "system")}
    md = {}
    for field, jf in (("mistake", "mistake_identified"), ("revealed", "answer_revealed")):
        hum = [[yn(s[row][field]) for row in sorted(mkey)] for s in ms]
        jud = [bool(jv[mkey[row]["condition"]].get(mkey[row]["item_id"], {}).get(jf)) for row in sorted(mkey)]
        md[jf] = {"members": agreement_block(hum[0], hum[1], "binary"),
                  "judge_vs_members": [agreement_block(jud, h, "binary") for h in hum]}
    hg = [[_score(s[row]["guidance"]) for row in sorted(mkey)] for s in ms]
    jg = [jv[mkey[row]["condition"]].get(mkey[row]["item_id"], {}).get("guidance") for row in sorted(mkey)]
    md["guidance"] = {"members": agreement_block(hg[0], hg[1], "ordinal"),
                      "judge_vs_members": [agreement_block(jg, h, "ordinal") for h in hg]}
    out["mathdial_sheet"] = md
    return out


# --------------------------------------------------------------------------- rubric effect sizes
def rank_biserial(a: dict, b: dict) -> dict:
    ids = sorted(set(a) & set(b))
    d = np.array([b[i] - a[i] for i in ids], dtype=float)
    d = d[d != 0]
    if not len(d):
        return {"n_pairs": len(ids), "n_nonzero": 0, "rank_biserial": 0.0}
    r = rankdata(np.abs(d))
    wp, wm = r[d > 0].sum(), r[d < 0].sum()
    rb = float((wp - wm) / (wp + wm))
    size = "negligible" if abs(rb) < 0.1 else "small" if abs(rb) < 0.3 else "medium" if abs(rb) < 0.5 else "large"
    return {"n_pairs": len(ids), "n_nonzero": int(len(d)), "rank_biserial": rb, "size": size}


def rubric_effects() -> dict:
    out = {}
    for label, stems in (("judge_curriculum", CURRICULUM), ("judge_multi_turn", ["multi_turn"])):
        out[label] = {}
        for dim in RUBRIC:
            a, b = {}, {}
            for stem in stems:
                a.update({f"{stem}/{i}": v["rubric"][dim] for i, v in verdicts("baseline", stem).items()})
                b.update({f"{stem}/{i}": v["rubric"][dim] for i, v in verdicts("system", stem).items()})
            out[label][dim] = rank_biserial(a, b)
    key = {k["row"]: k for k in json.load(open(ROOT / "eval/blind_ratings/rating_key.json", encoding="utf-8"))["rows"]}
    sheets = [{int(x["row"]): x for x in load_sheet(r)} for r in ("A", "B")]
    by = {"baseline": {}, "system": {}}
    for row, k in key.items():
        by[k["condition"]][k["item_id"]] = [s[row] for s in sheets]
    out["team_members"] = {}
    for dim in RUBRIC:
        mean = {c: {i: sum(float(r[dim]) for r in rs) / 2 for i, rs in by[c].items()
                    if all(str(r[dim]).strip() for r in rs)} for c in by}
        out["team_members"][dim] = rank_biserial(mean["baseline"], mean["system"])
    jv = {c: verdicts(c, "mathdial_sample") for c in ("baseline", "system")}
    out["judge_mathdial"] = {"guidance": rank_biserial({i: v["guidance"] for i, v in jv["baseline"].items()},
                                                       {i: v["guidance"] for i, v in jv["system"].items()})}
    return out


# --------------------------------------------------------------------------- latency detail
def latency_detail() -> dict:
    ids = set(list(items_of("svamp"))[:SVAMP_N])
    pct = lambda v, q: float(np.percentile(v, q)) if v else None
    out = {}
    for cond in ("baseline", "system"):
        turns = [t for i, j in runs(cond, "svamp").items() if i in ids and j.get("turns") for t in j["turns"]
                 if t.get("turn_wall_s") is not None and not t.get("noisy") and not t.get("rate_limited_attempts")]
        wall = [t["turn_wall_s"] for t in turns]
        ttft = [t["ttft_s"] for t in turns if t.get("ttft_s") is not None]
        block = {"clean_turns": len(turns),
                 "turn_wall_s": {"p50": pct(wall, 50), "p90": pct(wall, 90), "p95": pct(wall, 95),
                                 "median_ci95": median_ci(wall).get("median_ci95")},
                 "ttft_s": {"p50": pct(ttft, 50), "p90": pct(ttft, 90), "p95": pct(ttft, 95)},
                 "llm_calls_per_turn": {"mean": float(np.mean([t.get("llm_calls") or 0 for t in turns])),
                                        "counts": dict(Counter(int(t.get("llm_calls") or 0) for t in turns))}}
        if cond == "system":
            # A turn that starts a problem makes the scope and extraction calls
            # before generating; the scripted give-up turn makes only one call.
            first = [t for t in turns if t.get("pre_generation_s") is not None and (t.get("llm_calls") or 0) >= 2]
            pre = [t["pre_generation_s"] for t in turns if t.get("pre_generation_s") is not None]
            gen = [t["generation_wall_s"] for t in turns if t.get("generation_wall_s") is not None]
            block["before_generation_s"] = {"p50": pct(pre, 50), "mean": float(np.mean(pre)) if pre else None}
            block["generation_s"] = {"p50": pct(gen, 50), "mean": float(np.mean(gen)) if gen else None}
            fp = [t["pre_generation_s"] for t in first]
            fg = [t["generation_wall_s"] for t in first if t.get("generation_wall_s") is not None]
            block["new_problem_turns"] = {"n": len(first), "before_generation_p50": pct(fp, 50),
                                          "generation_p50": pct(fg, 50)}
        out[cond] = block
    return out


# --------------------------------------------------------------------------- MathDial: MRBench desired-annotation match rate
def mathdial_damr() -> dict:
    items = items_of("mathdial_sample")
    jv = {c: verdicts(c, "mathdial_sample") for c in ("baseline", "system")}
    extra = {c: {i: v["verdict"] for i, v in _load_checkpoint(JUDGE / f"{c}_mathdial_extra.jsonl").items()
                 if v.get("ok")} for c in ("baseline", "system")}
    revealed = {}
    for c in ("baseline", "system"):
        rr = runs(c, "mathdial_sample")
        revealed[c] = {i: answer_extraction.judge(answer_extraction.committed_answer(answer_extraction.reply_text(rr[i]["turns"][0])),
                                                  ground_truth_candidates(it), it.get("question") or "") is True
                       for i, it in items.items() if i in rr and rr[i].get("turns")}
    dims = {
        "mistake_identification": lambda c, i: jv[c][i]["mistake_identified"] if i in jv[c] else None,
        "mistake_location": lambda c, i: extra[c][i]["mistake_location"] == "Yes" if i in extra[c] else None,
        "revealing_the_answer_withheld": lambda c, i: (not revealed[c][i]) if i in revealed[c] else None,
        "providing_guidance": lambda c, i: jv[c][i]["guidance"] >= 4 if i in jv[c] else None,
        "actionability": lambda c, i: extra[c][i]["actionability"] == "Yes" if i in extra[c] else None,
    }
    out = {"desired": {"mistake_identification": "Yes", "mistake_location": "Yes",
                       "revealing_the_answer_withheld": "answer not stated (code)",
                       "providing_guidance": "judge guidance 4-5 of 5", "actionability": "Yes"}}
    for name, f in dims.items():
        vals = {c: {i: f(c, i) for i in items} for c in ("baseline", "system")}
        out[name] = paired_binary({i: v for i, v in vals["baseline"].items() if v is not None},
                                  {i: v for i, v in vals["system"].items() if v is not None})
    out["three_label_counts"] = {d: {c: dict(Counter(v[d] for v in extra[c].values())) for c in extra}
                                 for d in ("mistake_location", "actionability")}
    out["extra_judged"] = {c: len(extra[c]) for c in extra}
    return out


# --------------------------------------------------------------------------- main
def main() -> None:
    m = latest_paper_metrics()
    res = {"accuracy": accuracy(), "effect_sizes": effect_sizes(m), "scope_classifier": scope_classifier(m),
           "controller": controller(), "agreement": agreement(), "rubric_effects": rubric_effects(),
           "latency": latency_detail(), "mathdial_damr": mathdial_damr()}
    f = lambda x: "n/a" if x is None else f"{x:.3f}"
    acc, sc, ctl = res["accuracy"], res["scope_classifier"], res["controller"]
    lines = ["# Extra metrics", "",
             f"- Curriculum accuracy, paired (n={acc['paired']['n']}): baseline {f(acc['paired']['baseline']['rate'])}, "
             f"system {f(acc['paired']['system']['rate'])}; each condition on its own scorable items: "
             f"{f(acc['baseline']['accuracy_scorable']['rate'])} (n={acc['baseline']['accuracy_scorable']['n']}) vs "
             f"{f(acc['system']['accuracy_scorable']['rate'])} (n={acc['system']['accuracy_scorable']['n']}); strict over all {acc['items']}: "
             f"{f(acc['baseline']['strict_accuracy_all_items']['rate'])} vs {f(acc['system']['strict_accuracy_all_items']['rate'])}; "
             f"macro over classes {f(acc['baseline']['macro_accuracy_over_classes'])} vs {f(acc['system']['macro_accuracy_over_classes'])}",
             "- By class: " + "; ".join(f"{g}: {f(r['baseline']['rate'])} vs {f(r['system']['rate'])} (p_holm {f(r.get('p_holm'))})"
                                         for g, r in acc["by_class"].items()),
             "- Effect sizes: " + "; ".join(f"{k}: OR {v['discordant_odds_ratio_system_vs_baseline']:.2f}, g {v['cohens_g']:.2f} ({v['cohens_g_size']})"
                                            for k, v in res["effect_sizes"].items()),
             f"- Scope classifier, system: precision {f(sc['system']['precision'])}, recall {f(sc['system']['recall'])}, "
             f"F1 {f(sc['system']['f1'])}, balanced accuracy {f(sc['system']['balanced_accuracy'])}, MCC {f(sc['system']['mcc'])}; "
             f"held-out MCC {f(sc['system_held_out']['mcc'])}",
             f"- Controller: accuracy {f(ctl['accuracy'])}, macro-F1 {f(ctl['macro_f1_all'])} "
             f"(actions with n>=10: {f(ctl['macro_f1_support_10_plus'])}), weighted F1 {f(ctl['weighted_f1'])}",
             "- Agreement (members): " + "; ".join(
                 f"{d}: {f(v['percent_agreement'])} agree, alpha {f(v.get('krippendorff_alpha_ordinal', v.get('krippendorff_alpha_nominal')))}"
                 for d, v in res["agreement"]["main_sheet"].items()),
             "- Rank-biserial, team members: " + "; ".join(f"{d} {v['rank_biserial']:+.2f}"
                                                         for d, v in res["rubric_effects"]["team_members"].items()),
             f"- Latency P90 full reply: baseline {f(res['latency']['baseline']['turn_wall_s']['p90'])} s, "
             f"system {f(res['latency']['system']['turn_wall_s']['p90'])} s",
             "- MathDial DAMR (baseline vs system): " + "; ".join(
                 f"{d} {f(res['mathdial_damr'][d]['baseline']['rate'])} vs {f(res['mathdial_damr'][d]['system']['rate'])}"
                 for d in res["mathdial_damr"]["desired"])]
    print("\n".join(lines))
    path = write_result("extra_metrics", dataset_sources=[{"path": str(DATA)}], config={"svamp_items": SVAMP_N},
                        per_example_results=[], aggregate_metrics=res)
    write_summary_markdown(path, lines)
    print(f"\nRaw: {path}")


if __name__ == "__main__":
    main()
