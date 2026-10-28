"""eval/make_paper_outputs.py -- the paper's LaTeX tables and figures, built only
from saved result files (no API calls):

  eval/results/paper_metrics_*.json        (eval/paper_metrics.py, latest)
  eval/results/retrieval_eval_*.json, arithmetic_eval_*, curriculum_benchmark_eval_*,
  controller_eval_*, personalization_eval_*, opener_eval_*, judge_calibration_*  (latest of each)

Writes paper/tables/*.tex (booktabs, IEEEtran-ready) and paper/figures/*.pdf (+ .png
previews). Every number in them traces to one of those files.

Figures are drawn by eval/paper_figures.py (design rules in its docstring).

Run:  python -m eval.make_paper_outputs
"""
from __future__ import annotations

import json
from pathlib import Path

from eval.paper_figures import figures

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "eval" / "results"
TABLES = ROOT / "paper" / "tables"
FIGURES = ROOT / "paper" / "figures"


def latest(prefix: str) -> dict:
    files = sorted(RESULTS.glob(f"{prefix}_2*.json"))
    files = [f for f in files if not f.stem.endswith("_rubric_queue")]
    if not files:
        raise SystemExit(f"no {prefix} results file")
    return json.load(open(files[-1], encoding="utf-8"))


# --------------------------------------------------------------------------- formatting
def pct(r: dict | None, digits: int = 1) -> str:
    if not r or r.get("rate") is None:
        return "--"
    return f"{100 * r['rate']:.{digits}f}"


def frac(r: dict | None) -> str:
    return "--" if not r or r.get("n") is None else f"{r['k']}/{r['n']}"


def counted(r: dict | None) -> str:
    return f"{pct(r)} ({frac(r)})"


def pval(p: float | None) -> str:
    if p is None:
        return "--"
    return "$<$0.001" if p < 0.001 else f"{p:.3f}"


def diff(row: dict) -> str:
    d, (lo, hi) = row["diff_system_minus_baseline"], row["diff_ci95"]
    return f"{100 * d:+.1f} [{100 * lo:+.1f}, {100 * hi:+.1f}]"


def table(name: str, caption: str, label: str, colspec: str, header: list[str], rows: list[list[str]],
          notes: str | None = None, wide: bool = False) -> None:
    env = "table*" if wide else "table"
    lines = [f"\\begin{{{env}}}[t]", "\\centering", f"\\caption{{{caption}}}", f"\\label{{{label}}}",
             "\\footnotesize", f"\\begin{{tabular}}{{@{{}}{colspec}@{{}}}}", "\\toprule",
             " & ".join(header) + " \\\\", "\\midrule"]
    for r in rows:
        lines.append("\\midrule" if r == ["--midrule--"] else " & ".join(r) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    if notes:
        lines += [f"\\par\\smallskip\\parbox{{\\linewidth}}{{\\scriptsize {notes}}}"]
    lines += [f"\\end{{{env}}}", ""]
    (TABLES / f"{name}.tex").write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- tables
def tables(m: dict, comp: dict) -> None:
    sv, oos, hr, md = m["svamp"], m["out_of_scope"], m["human_ratings"], m["mathdial"]
    tf, tb = m["text_curriculum"]["system"], m["text_curriculum"]["baseline"]

    table("datasets", "Evaluation Sets", "tab:evalsets", "L{3.0cm}rL{3.6cm}",
          ["Set", "Items", "Scored by"],
          [["Curriculum benchmark, Classes 1--5", "935", "Committed final answer (code); judge rubric"],
           ["Out-of-scope questions", "277", "Answer / gloss / decline outcome (code)"],
           ["Multi-turn conversations", "206", "Controller action per turn; judge rubric"],
           ["Held-out: child-style openers", "30", "Clarify vs.\\ new question (code)"],
           ["Held-out: ambiguous and everyday", "20", "Expected behaviour, read item by item"],
           ["Held-out: out-of-scope", "50", "Outcome (code)"],
           ["SVAMP (first 500 of 1{,}000)", "500", "Final answer (code)"],
           ["MathDial student mistakes", "100", "Answer revealed (code); judge, checked by two raters"],
           ["Blind human rating sheet", "150", "Two team members, rubric and hallucination"]])

    c = m["curriculum_all"]
    rows = [
        ["Curriculum final-answer accuracy", pct(c["baseline"]), pct(c["system"]), diff(c), pval(c["mcnemar_p"]), frac(c["system"])],
        ["SVAMP accuracy (official labels)", pct(sv["official_labels"]["baseline"]), pct(sv["official_labels"]["system"]),
         diff(sv["official_labels"]), pval(sv["official_labels"]["mcnemar_p"]), frac(sv["official_labels"]["system"])],
        ["SVAMP accuracy (debatable labels removed)", pct(sv["without_debatable"]["baseline"]),
         pct(sv["without_debatable"]["system"]), diff(sv["without_debatable"]), pval(sv["without_debatable"]["mcnemar_p"]),
         frac(sv["without_debatable"]["system"])],
        ["Out-of-scope: correct behaviour", pct(oos["overall"]["baseline"]), pct(oos["overall"]["system"]),
         diff(oos["overall"]), pval(oos["overall"]["mcnemar_p"]), frac(oos["overall"]["system"])],
        ["--midrule--"],
        ["First reply gives the answer away$^\\downarrow$", pct(tb["early_reveal_in_first_reply"]),
         pct(tf["early_reveal_in_first_reply"]), "--", "--", frac(tf["early_reveal_in_first_reply"])],
        ["MathDial: names the mistake outright (judge)$^\\ddagger$", pct(md["judge_mistake_identified"]["baseline"]),
         pct(md["judge_mistake_identified"]["system"]), diff(md["judge_mistake_identified"]),
         pval(md["judge_mistake_identified"]["mcnemar_p"]), frac(md["judge_mistake_identified"]["system"])],
        ["MathDial: answer handed over (code)$^\\downarrow$", pct(md["answer_revealed_extractor"]["baseline"]),
         pct(md["answer_revealed_extractor"]["system"]), diff(md["answer_revealed_extractor"]),
         pval(md["answer_revealed_extractor"]["mcnemar_p"]), frac(md["answer_revealed_extractor"]["system"])],
        ["--midrule--"],
        ["Hallucination, flagged by both team members$^\\downarrow$", pct(hr["hallucination_both"]["baseline"]),
         pct(hr["hallucination_both"]["system"]), diff(hr["hallucination_both"]), pval(hr["hallucination_both"]["mcnemar_p"]),
         frac(hr["hallucination_both"]["system"])],
        ["Hallucination, flagged by either team member$^\\downarrow$", pct(hr["hallucination_either"]["baseline"]),
         pct(hr["hallucination_either"]["system"]), diff(hr["hallucination_either"]),
         pval(hr["hallucination_either"]["mcnemar_p"]), frac(hr["hallucination_either"]["system"])]]
    rows.insert(6, ["First reply invites the child to try", pct(tb["pedagogy_first"]["invites_attempt"]),
                    pct(tf["pedagogy_first"]["invites_attempt"]), "--", "--", frac(tf["pedagogy_first"]["invites_attempt"])])
    table("main_results", "Baseline Versus Tiny Thinker: Paired Results (\\%)", "tab:main", "L{4.4cm}rrcrr",
          ["Measure", "Base.", "Sys.", "Diff.\\ [95\\% CI]", "$p$", "Sys.\\ $k/n$"], rows,
          notes="Paired on the same items. Differences are system minus baseline in percentage points with Newcombe "
                "intervals; $p$ from the exact McNemar test. $\\downarrow$: lower is better. The first-reply measures "
                "are not paired tests: the baseline answers at once, the system's first reply invites an attempt. "
                "Curriculum accuracy and giving the answer away cover the items with one checkable final answer; "
                "inviting a try covers every first reply. Sys.: Tiny Thinker. $^\\ddagger$ Neither "
                "direction is better by itself: on 98 of 100 MathDial items the system re-teaches the step and asks the "
                "child to try again instead of naming the error, and the judge rated its guidance higher "
                "(Table~\\ref{tab:rubric}).",
          wide=True)

    rub_rows = []
    for src, label, n_note in ((m["judge_curriculum"]["rubric"], "Judge, curriculum", "935"),
                               (m["judge_multi_turn"]["rubric"], "Judge, multi-turn", "206"),
                               (hr["rubric_mean_of_two"], "Two team members (mean)", "75")):
        for dim in ("correctness", "grade_fit", "clarity", "restraint"):
            r = src[dim]
            tag = "$^\\dagger$" if label.startswith("Judge") and dim in ("clarity", "restraint") else ""
            rub_rows.append([label if dim == "correctness" else "", dim.replace("_", " ") + tag,
                             f"{r['baseline_mean']:.2f}", f"{r['system_mean']:.2f}", f"{r['mean_diff']:+.2f}",
                             pval(r.get("p_holm"))])
        rub_rows.append(["--midrule--"])
    g = md["judge_guidance_exploratory"]
    rub_rows.append(["Judge, MathDial", "guidance$^\\dagger$", f"{g['baseline_mean']:.2f}", f"{g['system_mean']:.2f}",
                     f"{g['mean_diff']:+.2f}", pval(g["wilcoxon_p"])])
    table("rubric", "Response Quality, 1--5 Rubric", "tab:rubric", "L{2.2cm}L{1.7cm}rrrr",
          ["Rater", "Dimension", "Base.", "Sys.", "Diff.", "$p_{\\mathrm{Holm}}$"], rub_rows,
          notes="Paired Wilcoxon signed-rank tests, Holm-corrected across the four dimensions (MathDial guidance: a "
                "single test). Judge: 935 curriculum replies, 206 conversations, 100 MathDial replies; team members: 75 "
                "paired replies. Restraint: no padding or needless detail. $^\\dagger$ Exploratory: the judge's "
                "agreement with the team members on this dimension fell below the bar set in advance.")

    sc, ho = m["scope"], m["held_out"]
    table("scope", "Scope Gate: False Refusals and Recall (\\%)", "tab:scope", "L{4.6cm}rr",
          ["Measure", "Base.", "Sys."],
          [["In-scope refused, curriculum", pct(sc["baseline"]["false_refusal_curriculum"]), pct(sc["system"]["false_refusal_curriculum"])],
           ["In-scope refused, SVAMP", pct(sc["baseline"]["false_refusal_svamp"]), pct(sc["system"]["false_refusal_svamp"])],
           ["In-scope refused, probes", pct(sc["baseline"]["false_refusal_oos_probes"]), pct(sc["system"]["false_refusal_oos_probes"])],
           ["In-scope refused, all sets", pct(sc["baseline"]["false_refusal_all_in_scope"]), pct(sc["system"]["false_refusal_all_in_scope"])],
           ["--midrule--"],
           ["Beyond-Class-5 stopped (refused or gloss)", pct(sc["baseline"]["recall_out_of_scope"]), pct(sc["system"]["recall_out_of_scope"])],
           ["Held-out disguised beyond-Class-5 stopped", "--", counted(ho["out_of_scope"]["stopped_beyond_class_5"])],
           ["Held-out in-scope probes answered", "--", counted(ho["out_of_scope"]["answered_in_scope_probes"])],
           ["Held-out vague openers asked to clarify", "--",
            counted({"k": ho["openers"].get("CLARIFY->CLARIFY", 0), "n": 15, "rate": ho["openers"].get("CLARIFY->CLARIFY", 0) / 15})],
           ["Held-out everyday questions answered", "--", counted(ho["ambiguous_everyday"]["meets_expected_everyday"])],
           ["Held-out ambiguous: several answers given", "--", counted(ho["ambiguous_everyday"]["meets_expected_ambiguous"])]],
          notes="Held-out sets were written after the system was fixed, by someone who had not seen the scope rules; "
                "they were run on the system only, and their rows give the item count.")

    def ped(rows_src: dict) -> list[str]:
        r, p = rows_src["reading_first"], rows_src["pedagogy_first"]
        return [f"{r['fk_grade']['median']:.1f}", f"{r['coleman_liau']['median']:.1f}", f"{r['words']['median']:.0f}",
                f"{r['words_per_sentence']['median']:.1f}", pct(p["invites_attempt"], 0),
                f"{p['mean_questions_to_child']:.2f}", pct(p["has_example"], 0), pct(p["has_encouragement"], 0),
                pct(p["mentions_beyond_class_5"], 0)]
    table("reading_pedagogy", "Reading Level and Teaching Moves in the First Reply (Curriculum)", "tab:pedagogy",
          "lrrrrrrrrr", ["", "FK", "CLI", "Words", "W/sent.", "Invite (\\%)", "Q/reply", "Example (\\%)",
                        "Praise (\\%)", "Beyond-5 (\\%)"],
          [["Baseline"] + ped(tb), ["Tiny Thinker"] + ped(tf)],
          notes="Medians for FK (Flesch-Kincaid grade), CLI (Coleman-Liau index), words, and words per sentence, "
                "computed on prose with numbers and markup removed; readability formulas are used comparatively only. "
                "Both conditions read below a Grade 5 level by Flesch-Kincaid. "
                "Invite: the reply asks the child to try. Beyond-5: mentions a beyond-Class-5 concept.",
          wide=True)

    mt, ver, ls, pl = m["multi_turn"], m["verifier"], m["latency_svamp"], m["production_latency"]
    ret = comp["retrieval"]
    cur, ari, ctl, per = comp["curriculum"], comp["arithmetic"], comp["controller"], comp["personalization"]
    table("components", "System Components", "tab:components", "L{4.8cm}r",
          ["Measure", "Value"],
          [["Retrieval Recall@1 / @3 / @5", f"{ret['recall_at_1']:.2f} / {ret['recall_at_3']:.2f} / {ret['recall_at_5']:.2f}"],
           ["Retrieval MRR; cross-grade leakage", f"{ret['mrr']:.2f}; {ret['grade_scope_mismatch_cross_grade_leakage_count']}"],
           ["--midrule--"],
           ["Verifier: items given a trusted value", f"{pct(ver['with_trusted_value'])}\\%"],
           ["Verifier: trusted value correct", f"{pct(ver['trusted_value_right'])}\\% ({frac(ver['trusted_value_right'])})"],
           ["Verifier on the benchmark (offline)", f"{cur['answer_accuracy']['numerator_match']}/{cur['answer_accuracy']['denominator_scorable']}"],
           ["Arithmetic set (offline)", f"{ari['answer_accuracy']['numerator_match']}/{ari['answer_accuracy']['denominator_scorable']}"],
           ["--midrule--"],
           ["Controller: expected action taken", f"{pct(mt['controller_action_match'])}\\% ({frac(mt['controller_action_match'])})"],
           ["Controller scenarios (deterministic)", f"{ctl['deterministic_pass_rate']['numerator']}/{ctl['deterministic_pass_rate']['denominator']}"],
           ["Personalization checks (deterministic)", f"{per['pass']}/{per['deterministically_checked']}"],
           ["--midrule--"],
           ["Latency, SVAMP clean turns: baseline / system (s)",
            f"{ls['baseline']['clean_turn_wall_s']['median']:.2f} / {ls['system']['clean_turn_wall_s']['median']:.2f}"],
           ["First token, SVAMP clean turns: baseline / system (s)",
            f"{ls['baseline']['clean_ttft_s']['median']:.2f} / {ls['system']['clean_ttft_s']['median']:.2f}"],
           ["Production pilot: median / P95 latency (s)",
            f"{pl['latency_s']['median']:.2f} / {pl['latency_s']['p95']:.2f}"],
           ["Production pilot: fallback provider used", f"{pct(pl['fallback_share'])}\\%"]],
          notes="Latency medians use clean turns only (no rate-limit retry). The system's extra time goes to the scope "
                "check, retrieval and answer verification that run before it starts replying. The production pilot is "
                "the live app's "
                f"own {pl['succeeded']} tutoring calls, 20 July to 22 August 2026.")

    ag, mda, cal = hr["agreement"], md["agreement"], comp["judge_calibration"]
    table("agreement", "Agreement Between Raters (Cohen's $\\kappa$)", "tab:agreement", "L{3.6cm}rr",
          ["Measure", "Raters", "Judge vs.\\ raters"],
          [["Hallucination", f"{ag['hallucination_kappa']:.2f}", f"{cal['hallucination'][0]:.2f}"],
           ["Correctness (weighted)", f"{ag['correctness_weighted_kappa']:.2f}", f"{cal['correctness'][0]:.2f}"],
           ["Grade fit (weighted)", f"{ag['grade_fit_weighted_kappa']:.2f}", f"{cal['grade_fit'][0]:.2f}"],
           ["Clarity (weighted)", f"{ag['clarity_weighted_kappa']:.2f}", f"{cal['clarity'][0]:.2f}"],
           ["Restraint (weighted)", f"{ag['restraint_weighted_kappa']:.2f}", f"{cal['restraint'][0]:.2f}"],
           ["--midrule--"],
           ["MathDial: mistake identified", f"{mda['mistake_identified']['humans_kappa']:.2f}",
            f"{min(mda['mistake_identified']['judge_vs_member_kappas']):.2f}"],
           ["MathDial: answer revealed", f"{mda['answer_revealed']['humans_kappa']:.2f}",
            f"{min(mda['answer_revealed']['judge_vs_member_kappas']):.2f}"],
           ["MathDial: guidance (weighted)", f"{mda['guidance']['humans_weighted_kappa']:.2f}",
            f"{min(mda['guidance']['judge_vs_member_weighted_kappas']):.2f}"]],
          notes="Raters: the two team members. Judge vs.\\ raters: the lower of the judge's agreement with each rater "
                "(MathDial), or with a rater on a held-back half of an earlier blind sheet (rubric rows). The judge's "
                "hallucination flags are not used.")


def main() -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    m = latest("paper_metrics")["aggregate_metrics"]
    comp = {"retrieval": latest("retrieval_eval")["aggregate_metrics"],
            "curriculum": latest("curriculum_benchmark_eval")["aggregate_metrics"],
            "arithmetic": latest("arithmetic_eval")["aggregate_metrics"],
            "controller": latest("controller_eval")["aggregate_metrics"],
            "personalization": latest("personalization_eval")["aggregate_metrics"],
            "judge_calibration": latest("judge_calibration")["aggregate_metrics"]}
    tables(m, comp)
    figures(m, FIGURES)
    print("tables:", sorted(p.name for p in TABLES.glob("*.tex")))
    print("figures:", sorted(p.name for p in FIGURES.glob("*.pdf")))


if __name__ == "__main__":
    main()
