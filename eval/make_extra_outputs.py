"""eval/make_extra_outputs.py -- LaTeX tables and figures for the extra standard
measures, from saved results only (no API calls):

  eval/results/extra_metrics_*.json        (eval/extra_metrics.py, latest)
  eval/results/retrieval_ablation_*.json   (eval/retrieval_ablation.py, latest)

Writes paper/tables/extra/*.tex and paper/figures/extra/*.pdf|png, in the same
style as the main paper outputs (eval/make_paper_outputs.py, eval/paper_figures.py).

Run:  python -m eval.make_extra_outputs
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from eval import make_paper_outputs as M  # noqa: E402
from eval.paper_figures import (BASELINE, CONDITIONS, FONT, GRID, INK, MODE_LABELS, MUTED, SECONDARY,  # noqa: E402
                                SYSTEM, _axis, _base_style, _condition_legend, _paired_bars, _save)

TABLES = M.TABLES / "extra"
FIGURES = M.FIGURES / "extra"
# Retrieval variants: categorical slots 1, 3, 7, 4 (validated together; two sit
# below 3:1 contrast, so every line carries a direct label).
VARIANT_STYLE = {"hybrid": ("Hybrid (production)", SYSTEM), "dense_only": ("Dense only", "#6250d6"),
                 "bm25_only": ("BM25 only", "#1baf7a"), "hybrid_all_classes": ("Hybrid, no class filter", "#eda100")}
BLUES = LinearSegmentedColormap.from_list("tt_blues", ["#f4f8fd", "#a9c9ef", "#2a78d6", "#123f78"])
LABEL = {**MODE_LABELS, "ask_answer": "Ask for the answer", "co_solve": "Solve together"}


def f3(x) -> str:
    return "--" if x is None else f"{x:.3f}"


def f2(x) -> str:
    return "--" if x is None else f"{x:.2f}"


def pc(x) -> str:
    return "--" if x is None else f"{100 * x:.1f}"


def table(name: str, *args, **kw) -> None:
    M.table(f"extra/{name}", *args, **kw)


# --------------------------------------------------------------------------- tables
def tables(x: dict, ra: dict) -> None:
    acc = x["accuracy"]
    rows = []
    for title, block in (("Class", acc["by_class"]), ("Question type", acc["by_question_type"]),
                         ("SVAMP, class", acc["svamp_by_class"])):
        rows.append([f"\\textit{{{title}}}", "", "", "", "", ""])
        for k, r in block.items():
            rows.append([k.replace("_", " "), str(r["n"]), M.pct(r["baseline"]), M.pct(r["system"]), M.diff(r),
                         M.pval(r.get("p_holm"))])
        rows.append(["--midrule--"])
    p = acc["paired"]
    rows += [["Micro (pooled, paired)", str(p["n"]), M.pct(p["baseline"]), M.pct(p["system"]), M.diff(p), M.pval(p["mcnemar_p"])],
             ["Macro (mean of classes)", "", pc(acc["baseline"]["macro_accuracy_over_classes"]),
              pc(acc["system"]["macro_accuracy_over_classes"]), "", ""],
             ["Own scorable items (unpaired)", f"{acc['baseline']['accuracy_scorable']['n']} / {acc['system']['accuracy_scorable']['n']}",
              M.pct(acc["baseline"]["accuracy_scorable"]), M.pct(acc["system"]["accuracy_scorable"]), "", ""],
             ["Strict (all 935 items)", str(acc["items"]), M.pct(acc["baseline"]["strict_accuracy_all_items"]),
              M.pct(acc["system"]["strict_accuracy_all_items"]), "", ""],
             ["Error rate (paired)", str(p["n"]), pc(1 - p["baseline"]["rate"]), pc(1 - p["system"]["rate"]), "", ""]]
    table("accuracy_breakdown", "Final-Answer Accuracy by Class and Question Type (\\%)", "tab:acc-breakdown",
          "L{3.2cm}rrrcr", ["Stratum", "$n$", "Base.", "Sys.", "Diff.\\ [95\\% CI]", "$p_{\\mathrm{Holm}}$"], rows,
          notes="Curriculum items with one checkable final answer, paired on items scorable in both conditions, unless "
                "noted. McNemar tests, Holm-adjusted within each block. Unpaired: each condition on its own scorable "
                "items; Tiny Thinker's 6 extra items are refusals of conceptual questions, scored wrong. Strict: correct "
                "answers over all 935 items, so the 352--358 conceptual items count as not correct.")

    names = {"curriculum_correct": "Curriculum: correct", "svamp_correct": "SVAMP: correct",
             "svamp_correct_without_debatable": "SVAMP, debatable removed: correct",
             "out_of_scope_handled": "Out-of-scope: handled correctly",
             "mathdial_answer_handed_over": "MathDial: answer handed over$^\\downarrow$",
             "mathdial_names_mistake": "MathDial: names the mistake",
             "hallucination_flagged_by_both": "Hallucination, both members$^\\downarrow$",
             "hallucination_flagged_by_either": "Hallucination, either member$^\\downarrow$"}
    rows = []
    for k, e in x["effect_sizes"].items():
        lo, hi = e["odds_ratio_ci95"]
        star = "$^\\ast$" if e["zero_cell_correction"] else ""
        rows.append([names[k], str(e["n"]), str(e["only_baseline"]), str(e["only_system"]),
                     f"{e['discordant_odds_ratio_system_vs_baseline']:.2f}{star} [{lo:.2f}, {hi:.2f}]",
                     f"{e['cohens_g']:.2f} ({e['cohens_g_size']})", M.pval(e["mcnemar_p"])])
    table("effect_sizes", "Effect Sizes for Paired Yes/No Outcomes", "tab:effect-sizes", "L{3.6cm}rrrcll",
          ["Outcome", "$n$", "$b$", "$c$", "OR $c/b$ [95\\% CI]", "Cohen's $g$", "$p$"], rows,
          notes="$b$: items yes for the baseline only; $c$: yes for Tiny Thinker only. OR: discordant odds ratio, "
                "log-normal interval; $^\\ast$0.5 added to both cells because one is zero. Cohen's $g = |c/(b+c) - 0.5|$; "
                "bands $<$0.05 negligible, $<$0.15 small, $<$0.25 medium, otherwise large. With few discordant pairs "
                "(curriculum: 12) $g$ is unstable; read it with the interval. $\\downarrow$: fewer is better.",
          wide=True)

    sc = x["scope_classifier"]
    keys = [("tp", "True positives (stopped, beyond Class 5)"), ("fn", "False negatives (taught, beyond Class 5)"),
            ("fp", "False positives (refused, in scope)"), ("tn", "True negatives (answered, in scope)")]
    rows = [[lab] + [str(sc[c][k]) for c in ("baseline", "system", "system_held_out")] for k, lab in keys]
    rows.append(["--midrule--"])
    for k, lab in (("precision", "Precision"), ("recall", "Recall"), ("specificity", "Specificity"),
                   ("false_positive_rate", "False-positive rate"), ("f1", "F1"),
                   ("balanced_accuracy", "Balanced accuracy"), ("mcc", "MCC"), ("accuracy", "Accuracy")):
        rows.append([lab] + [f3(sc[c][k]) for c in ("baseline", "system", "system_held_out")])
    table("scope_classifier", "The Scope Gate as a Classifier", "tab:scope-classifier", "L{4.4cm}rrr",
          ["Positive = needs maths beyond Class 5", "Base.", "Sys.", "Sys., held-out"], rows,
          notes="Main sets: 217 beyond-Class-5 items and 1,495 in-scope items (curriculum, SVAMP, probes). A gloss "
                "counts as stopped. Held-out: 40 disguised beyond-Class-5 questions and 10 in-scope probes, Tiny Thinker "
                "only. Only 13\\% of main-set items are positive, so balanced accuracy and MCC are the fair single numbers.")

    v = ra["variants"]
    rows = []
    for key in ("hybrid", "bm25_only", "dense_only", "hybrid_all_classes"):
        b = v[key]
        lk = b["cross_class_leakage"]
        rows.append([VARIANT_STYLE[key][0], f3(b["hit@1"]), f3(b["hit@3"]), f3(b["recall@3"]), f3(b["precision@3"]),
                     f3(b["ndcg@3"]), f3(b["ap@3"]), f3(b["mrr"]), f3(b["ndcg@10"]), f"{lk['leaked']}/{lk['queries']}",
                     "--" if key == "hybrid" else M.pval(b.get("ndcg@3_vs_hybrid_wilcoxon_p"))])
    table("retrieval_measures", "Retrieval: Standard Measures and Variants", "tab:retrieval-measures",
          "lrrrrrrrrrr", ["Variant", "Hit@1", "Hit@3", "R@3", "P@3", "nDCG@3", "MAP@3", "MRR", "nDCG@10", "Leak",
                          "$p$ vs.\\ hybrid"], rows,
          notes=f"{ra['queries_scored']} queries with labelled relevant pages. Hit@k: a relevant chunk in the top $k$ "
                "(reported as Recall@k elsewhere in the evaluation); R@3: share of a query's relevant pages in the top 3; "
                "P@3: relevant chunks among the 3. nDCG and MAP use binary relevance. Leak: queries whose top 3 holds a "
                "chunk outside classes $G(g)$, over scored and wrong-class queries. $p$: Wilcoxon on per-query nDCG@3.",
          wide=True)
    rows = [[f"Class {g}", str(b["n"]), f3(b["hit@1"]), f3(b["hit@3"]), f3(b["ndcg@3"]), f3(b["mrr"])]
            for g, b in ra["hybrid_by_grade"].items()]
    rows.append(["--midrule--"])
    rows += [[c.replace("_", " "), str(b["n"]), f3(b["hit@1"]), f3(b["hit@3"]), f3(b["ndcg@3"]), f3(b["mrr"])]
             for c, b in ra["hybrid_by_category"].items()]
    table("retrieval_by_group", "Production Retrieval by Class and Query Type", "tab:retrieval-groups",
          "L{3.4cm}rrrrr", ["Group", "$n$", "Hit@1", "Hit@3", "nDCG@3", "MRR"], rows)

    ctl = x["controller"]
    rows = [[LABEL.get(a, a), str(r["support"]), str(r["predicted"]), f3(r["precision"]), f3(r["recall"]), f3(r["f1"])]
            for a, r in ctl["per_action"].items()]
    rows += [["--midrule--"], ["Accuracy (all turns)", str(ctl["turns"]), "", "", "", f3(ctl["accuracy"])],
             ["Macro-F1, all actions", "", "", "", "", f3(ctl["macro_f1_all"])],
             ["Macro-F1, actions with $n \\geq 10$", "", "", "", "", f3(ctl["macro_f1_support_10_plus"])],
             ["Weighted F1", "", "", "", "", f3(ctl["weighted_f1"])]]
    table("controller_per_action", "Controller: Per-Action Precision, Recall and F1", "tab:controller-actions",
          "L{4.0cm}rrrrr", ["Expected action", "$n$", "Taken", "Precision", "Recall", "F1"], rows,
          notes="666 scored turns in 206 conversations. $n$: turns where the action was expected; Taken: turns where "
                "Tiny Thinker took it. Showing the answer and solving together are accepted for each other, as in the "
                "headline score.")

    ag = x["agreement"]
    rows = []
    for d, b in ag["main_sheet"].items():
        rows.append([d.replace("_", " ").capitalize(), pc(b["percent_agreement"]), pc(b.get("within_one_point")),
                     f2(b.get("cohen_kappa", b.get("weighted_kappa"))), f2(b.get("gwet_ac1")),
                     f2(b.get("krippendorff_alpha_nominal", b.get("krippendorff_alpha_ordinal")))])
    rows.append(["--midrule--"])
    for d, b in ag["mathdial_sheet"].items():
        mb = b["members"]
        jm = min(b["judge_vs_members"], key=lambda r: r["percent_agreement"])
        rows.append([f"MathDial: {d.replace('_', ' ')}", pc(mb["percent_agreement"]), pc(mb.get("within_one_point")),
                     f2(mb.get("cohen_kappa", mb.get("weighted_kappa"))), f2(mb.get("gwet_ac1")),
                     f2(mb.get("krippendorff_alpha_nominal", mb.get("krippendorff_alpha_ordinal")))])
        rows.append(["\\quad judge vs.\\ member (lower)", pc(jm["percent_agreement"]), pc(jm.get("within_one_point")),
                     f2(jm.get("cohen_kappa", jm.get("weighted_kappa"))), f2(jm.get("gwet_ac1")),
                     f2(jm.get("krippendorff_alpha_nominal", jm.get("krippendorff_alpha_ordinal")))])
    table("agreement_extended", "Agreement Beyond Cohen's $\\kappa$", "tab:agreement-extended", "L{3.8cm}rrrrr",
          ["Measure", "Agree (\\%)", "$\\pm$1 (\\%)", "$\\kappa$ / $\\kappa_w$", "AC1", "$\\alpha$"], rows,
          notes="Two team members, 150 blind rows (MathDial: 50). $\\kappa$ for yes/no labels, quadratic-weighted "
                "$\\kappa_w$ for 1--5 scores. AC1: Gwet's, for yes/no labels. $\\alpha$: Krippendorff's, nominal for "
                "yes/no and ordinal for scores. When nearly every label is the same (hallucination: 95\\% agreement), "
                "$\\kappa$ is low while AC1 stays high.")

    re_ = x["rubric_effects"]
    rows = []
    for grp, title in (("judge_curriculum", "Judge, curriculum"), ("judge_multi_turn", "Judge, multi-turn"),
                       ("team_members", "Two team members"), ("judge_mathdial", "Judge, MathDial")):
        for i, (d, r) in enumerate(re_[grp].items()):
            rows.append([title if i == 0 else "", d.replace("_", " "), str(r["n_pairs"]), str(r["n_nonzero"]),
                         f"{r['rank_biserial']:+.2f}", r["size"]])
        rows.append(["--midrule--"])
    table("rubric_effects", "Rubric Effect Sizes (Matched-Pairs Rank-Biserial)", "tab:rubric-effects",
          "L{2.4cm}L{1.6cm}rrrl", ["Rater", "Dimension", "Pairs", "Changed", "$r$", "Size"], rows[:-1],
          notes="$r = (W_+ - W_-)/(W_+ + W_-)$ over pairs whose score changed; positive favours Tiny Thinker. Bands "
                "$|r| <$ 0.1 negligible, $<$ 0.3 small, $<$ 0.5 medium, otherwise large. Judge clarity, restraint and "
                "MathDial guidance are exploratory.")

    lt = x["latency"]
    b, s = lt["baseline"], lt["system"]
    rows = [["Full reply, P50 / P90 / P95 (s)", f"{b['turn_wall_s']['p50']:.2f} / {b['turn_wall_s']['p90']:.2f} / {b['turn_wall_s']['p95']:.2f}",
             f"{s['turn_wall_s']['p50']:.2f} / {s['turn_wall_s']['p90']:.2f} / {s['turn_wall_s']['p95']:.2f}"],
            ["First word, P50 / P90 / P95 (s)", f"{b['ttft_s']['p50']:.2f} / {b['ttft_s']['p90']:.2f} / {b['ttft_s']['p95']:.2f}",
             f"{s['ttft_s']['p50']:.2f} / {s['ttft_s']['p90']:.2f} / {s['ttft_s']['p95']:.2f}"],
            ["Model calls per turn (mean)", f"{b['llm_calls_per_turn']['mean']:.2f}", f"{s['llm_calls_per_turn']['mean']:.2f}"],
            ["New-problem turn: before generation, P50 (s)", "--", f"{s['new_problem_turns']['before_generation_p50']:.2f}"],
            ["New-problem turn: generation, P50 (s)", "--", f"{s['new_problem_turns']['generation_p50']:.2f}"],
            ["Clean turns", str(b["clean_turns"]), str(s["clean_turns"])]]
    table("latency_detail", "Latency Detail (SVAMP, Clean Turns)", "tab:latency-detail", "L{4.4cm}rr",
          ["Measure", "Base.", "Sys."], rows,
          notes="Clean turns: no rate-limit retry. A new-problem turn makes the scope and verifier calls before "
                f"generating ({s['new_problem_turns']['n']} turns); the scripted give-up turn makes one call.")

    md = x["mathdial_damr"]
    names = {"mistake_identification": "Mistake identification", "mistake_location": "Mistake location$^\\dagger$",
             "revealing_the_answer_withheld": "Answer withheld (code)", "providing_guidance": "Providing guidance$^\\dagger$",
             "actionability": "Actionability$^\\dagger$"}
    rows = [[names[k], md["desired"][k].replace("_", " "), M.pct(md[k]["baseline"]), M.pct(md[k]["system"]), M.diff(md[k]),
             M.pval(md[k]["mcnemar_p"])] for k in names]
    table("mathdial_damr", "MathDial on the MRBench Dimensions: Desired-Label Match Rate (\\%)", "tab:mathdial-damr",
          "L{3.2cm}L{2.6cm}rrcr", ["Dimension", "Desired", "Base.", "Sys.", "Diff.\\ [95\\% CI]", "$p$"], rows,
          notes="100 MathDial items, paired, McNemar. Judge: qwen/qwen3.8-27b, blind to condition. $^\\dagger$ Exploratory: "
                "location and actionability have no human check, and guidance agreement with the team members was low. "
                "Scaffolding replies are known to score lower on identification and location.",
          wide=True)


# --------------------------------------------------------------------------- figures
def fig_accuracy_by_class(x: dict) -> None:
    rows = [(f"Class {g}", f"n = {r['n']}", r["baseline"], r["system"]) for g, r in x["accuracy"]["by_class"].items()]
    fig, ax = plt.subplots(figsize=(3.5, 3.0))
    _paired_bars(ax, rows, bar_h=0.36, gap=1.0)
    _axis(ax, "Final answers correct (%)", xlim=(0, 100), ticks=[0, 25, 50, 75, 100])
    _condition_legend(ax, 1.0, loc="lower center")
    _save(fig, FIGURES, "fig_accuracy_by_class")


def fig_retrieval(ra: dict) -> None:
    ks = [1, 3, 5, 10]
    fig, axes = plt.subplots(1, 2, figsize=(7.16, 2.6), gridspec_kw={"wspace": 0.25})
    for ax, metric, title in ((axes[0], "hit", "Hit@k: a relevant chunk in the top k"),
                              (axes[1], "ndcg", "nDCG@k: ranking quality")):
        for key in ("hybrid", "dense_only", "bm25_only", "hybrid_all_classes"):
            name, color = VARIANT_STYLE[key]
            ys = [100 * ra["variants"][key][f"{metric}@{k}"] for k in ks]
            ax.plot(ks, ys, color=color, linewidth=2 if key == "hybrid" else 1.4, marker="o", markersize=4,
                    markeredgecolor="white", markeredgewidth=0.8, zorder=3 if key == "hybrid" else 2, label=name)
            if key == "hybrid":                            # the production value at k = 3, labelled
                ax.annotate(f"{ys[1]:.0f}", (3, ys[1]), textcoords="offset points", xytext=(0, 6), ha="center",
                            fontsize=FONT - 1, color=INK)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(MUTED)
            ax.spines[side].set_linewidth(0.6)
        ax.set_xticks(ks)
        ax.set_xlim(0.6, 10.2)
        ax.set_ylim(30, 102)
        ax.yaxis.grid(True, color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)
        ax.tick_params(colors=SECONDARY, length=2, width=0.6, labelsize=FONT - 0.5)
        ax.set_xlabel("k (chunks returned; the tutor uses 3)", color=SECONDARY, fontsize=FONT - 0.5)
        ax.set_ylabel("Score (%)", color=SECONDARY, fontsize=FONT - 0.5)
        ax.set_title(title, loc="left", color=INK, fontsize=FONT, pad=4)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.98), ncol=4, frameon=False,
               fontsize=FONT, handlelength=2.2, columnspacing=1.6)
    _save(fig, FIGURES, "fig_retrieval_variants")


def fig_controller_confusion(x: dict) -> None:
    ctl = x["controller"]
    rows = [a for a in ctl["labels_expected"] if ctl["per_action"][a]["support"] >= 10]
    cols = rows + [c for c in ctl["labels_taken"] if c not in rows]
    counts = np.array([[ctl["confusion"][r][c] for c in cols] for r in rows], dtype=float)
    share = counts / counts.sum(axis=1, keepdims=True)
    fig, ax = plt.subplots(figsize=(7.16, 3.5))
    ax.imshow(share, cmap=BLUES, vmin=0, vmax=1, aspect="auto")
    for i in range(len(rows)):
        for j in range(len(cols)):
            if counts[i, j]:
                ax.text(j, i, f"{int(counts[i, j])}", ha="center", va="center", fontsize=FONT - 1,
                        color="white" if share[i, j] > 0.55 else INK)
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels([LABEL.get(c, c) for c in cols], rotation=35, ha="right", fontsize=FONT - 1, color=INK)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([f"{LABEL.get(r, r)} (n={int(counts[i].sum())})" for i, r in enumerate(rows)],
                       fontsize=FONT - 0.5, color=INK)
    ax.set_xlabel("Action Tiny Thinker took", color=SECONDARY, fontsize=FONT - 0.5)
    ax.set_ylabel("Expected action", color=SECONDARY, fontsize=FONT - 0.5)
    ax.set_xticks(np.arange(-0.5, len(cols)), minor=True)
    ax.set_yticks(np.arange(-0.5, len(rows)), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.2)
    ax.tick_params(which="both", length=0)
    for side in ax.spines.values():
        side.set_visible(False)
    ax.set_title("Numbers are turns; shading is the share of each row (darker = more)", loc="left",
                 color=SECONDARY, fontsize=FONT - 0.5, pad=4, fontweight="normal")
    _save(fig, FIGURES, "fig_controller_confusion")


def fig_latency_split(x: dict) -> None:
    lt = x["latency"]
    base, s = lt["baseline"]["turn_wall_s"]["p50"], lt["system"]["new_problem_turns"]
    PRE = "#a9c9ef"
    fig, ax = plt.subplots(figsize=(3.5, 1.5))
    ax.barh(1, base, height=0.5, color=BASELINE, zorder=2)
    ax.text(base + 0.05, 1, f"{base:.1f} s", va="center", fontsize=FONT - 0.6, color=SECONDARY)
    ax.barh(0, s["before_generation_p50"], height=0.5, color=PRE, zorder=2)
    ax.barh(0, s["generation_p50"], left=s["before_generation_p50"], height=0.5, color=SYSTEM, zorder=2)
    ax.text(s["before_generation_p50"] / 2, 0, f"checks {s['before_generation_p50']:.1f} s", ha="center", va="center",
            fontsize=FONT - 1.2, color=INK)
    ax.text(s["before_generation_p50"] + s["generation_p50"] / 2, 0, f"reply {s['generation_p50']:.1f} s", ha="center",
            va="center", fontsize=FONT - 1.2, color="white")
    ax.set_yticks([1, 0])
    ax.set_yticklabels(["Baseline", "Tiny Thinker,\nnew problem"], fontsize=FONT - 0.5, color=INK)
    _axis(ax, "Median seconds per turn (SVAMP, clean turns)", xlim=(0, 3.5), ticks=[0, 1, 2, 3])
    ax.spines["left"].set_visible(False)
    _save(fig, FIGURES, "fig_latency_split")


def fig_mathdial_damr(x: dict) -> None:
    md = x["mathdial_damr"]
    rows = [("Names the mistake", "desired: yes", md["mistake_identification"]["baseline"], md["mistake_identification"]["system"]),
            ("Locates the mistake", "desired: yes; judge only", md["mistake_location"]["baseline"], md["mistake_location"]["system"]),
            ("Keeps the answer back", "desired: not stated", md["revealing_the_answer_withheld"]["baseline"],
             md["revealing_the_answer_withheld"]["system"]),
            ("Strong guidance (4-5 of 5)", "exploratory", md["providing_guidance"]["baseline"], md["providing_guidance"]["system"]),
            ("Clear next step", "desired: yes; judge only", md["actionability"]["baseline"], md["actionability"]["system"])]
    fig, ax = plt.subplots(figsize=(3.5, 3.0))
    _paired_bars(ax, rows, bar_h=0.36, gap=1.05)
    _axis(ax, "Replies with the desired label (%)", xlim=(0, 100), ticks=[0, 25, 50, 75, 100])
    _condition_legend(ax, 1.0, loc="lower center")
    _save(fig, FIGURES, "fig_mathdial_damr")


def main() -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    x = M.latest("extra_metrics")["aggregate_metrics"]
    ra = M.latest("retrieval_ablation")["aggregate_metrics"]
    tables(x, ra)
    _base_style()
    for f in list(FIGURES.glob("fig_*")):
        f.unlink()
    fig_accuracy_by_class(x)
    fig_retrieval(ra)
    fig_controller_confusion(x)
    fig_latency_split(x)
    fig_mathdial_damr(x)
    print("tables:", sorted(p.name for p in TABLES.glob("*.tex")))
    print("figures:", sorted(p.name for p in FIGURES.glob("*.pdf")))


if __name__ == "__main__":
    main()
