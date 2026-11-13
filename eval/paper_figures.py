"""eval/paper_figures.py -- the paper's figures, drawn from the paper-metrics
result (see eval/make_paper_outputs.py, which calls figures()).

Design rules applied to every figure:
  - bars, read from a zero baseline; two conditions in fixed colours (baseline
    orange #eb6834, Tiny Thinker blue #2a78d6; checked for colour-blind
    separation), always named in a legend or label, never by colour alone;
  - one axis per chart; 0-100 for shares; the value printed at the end of each
    bar; 95% intervals as thin whiskers where they matter;
  - each measure says which direction is better; plain-English labels;
  - recessive grid, neutral text; sized for an IEEE column (3.5 in) or the page
    width (7.16 in).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

SYSTEM, BASELINE = "#2a78d6", "#eb6834"
INK, SECONDARY, MUTED, GRID = "#1f1f1e", "#52514e", "#8a8984", "#ebeae6"
FONT = 7.5

MODE_LABELS = {
    "teach_invite": "Teach, then invite a try", "diagnose_correct": "Confirm a correct answer",
    "diagnose_wrong": "Diagnose a wrong answer", "hint": "Give a hint", "clarify": "Ask what the child means",
    "reveal": "Show the answer after a give-up", "confusion_help": "Re-explain when confused",
    "ack_conceptual": "Acknowledge a conceptual answer", "gloss": "Short gloss (beyond Class 5)",
    "scope_refused": "Decline (beyond Class 5)", "co_solve": "Solve together", "redirect": "Redirect",
}
CONDITIONS = (("baseline", "Baseline (plain LLM tutor)", BASELINE), ("system", "Tiny Thinker", SYSTEM))


def _base_style() -> None:
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": FONT, "pdf.fonttype": 42,
                         "axes.titlesize": FONT + 0.5, "axes.titleweight": "bold"})


def _axis(ax, xlabel: str | None = None, xlim=(0, 100), ticks=None) -> None:
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.spines["bottom"].set_linewidth(0.6)
    ax.tick_params(axis="x", colors=SECONDARY, length=2, width=0.6, labelsize=FONT - 0.5)
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(*xlim)
    if ticks is not None:
        ax.set_xticks(ticks)
    ax.xaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    if xlabel:
        ax.set_xlabel(xlabel, color=SECONDARY, fontsize=FONT - 0.5)


def _condition_legend(target, y: float = 1.0, loc: str = "upper center") -> None:
    handles = [Patch(facecolor=c, label=lab) for _, lab, c in CONDITIONS]
    target.legend(handles=handles, loc=loc, bbox_to_anchor=(0.5, y), ncol=2, frameon=False, fontsize=FONT,
                  handlelength=1.2, handleheight=0.8, columnspacing=1.6)


def _save(fig, out: Path, name: str) -> None:
    fig.savefig(out / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(out / f"{name}.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def _paired_bars(ax, rows: list[tuple[str, str, dict, dict]], bar_h: float = 0.34, gap: float = 1.05) -> None:
    """rows: (label, direction, baseline_rate, system_rate) -> a baseline bar above a
    system bar for each measure, value at each bar's end, faint 95% whiskers."""
    y = 0.0
    for label, direction, b, s in rows:
        for (cond, _, color), r, dy in zip(CONDITIONS, (b, s), (bar_h / 2 + 0.02, -bar_h / 2 - 0.02)):
            v = 100 * r["rate"]
            ax.barh(y + dy, v, height=bar_h, color=color, zorder=2)
            lo, hi = (100 * x for x in r["ci95"])
            ax.plot([lo, hi], [y + dy, y + dy], color=INK, linewidth=0.6, alpha=0.35, zorder=3)
            inside = v >= 86
            ax.text(v - 1.2 if inside else max(v, hi) + 1.2, y + dy, f"{v:.0f}%", va="center",
                    ha="right" if inside else "left", fontsize=FONT - 0.6,
                    color="white" if inside else SECONDARY, fontweight="bold" if inside else "normal", zorder=4)
        ax.text(-2, y + 0.1, label, ha="right", va="center", fontsize=FONT, color=INK)
        ax.text(-2, y - 0.27, direction, ha="right", va="center", fontsize=FONT - 1.3, color=MUTED, style="italic")
        y -= gap
    ax.set_yticks([])
    ax.set_ylim(y + gap - 0.55, 0.55)


def fig_main_outcomes(m: dict, out: Path) -> None:
    sv, oos, md = m["svamp"], m["out_of_scope"], m["mathdial"]
    tf, tb = m["text_curriculum"]["system"], m["text_curriculum"]["baseline"]
    panels = [
        ("Solving problems", [
            ("Curriculum questions answered correctly", "higher is better", m["curriculum_all"]["baseline"],
             m["curriculum_all"]["system"]),
            ("SVAMP word problems answered correctly", "higher is better", sv["official_labels"]["baseline"],
             sv["official_labels"]["system"])]),
        ("Staying within Class 1-5", [
            ("Out-of-scope questions handled correctly", "higher is better", oos["overall"]["baseline"],
             oos["overall"]["system"])]),
        ("Teaching, not just telling", [
            ("First reply gives the answer away", "lower is better", tb["early_reveal_in_first_reply"],
             tf["early_reveal_in_first_reply"]),
            ("First reply invites the child to try", "higher is better", tb["pedagogy_first"]["invites_attempt"],
             tf["pedagogy_first"]["invites_attempt"]),
            ("Wrong attempt: names the mistake outright", "Tiny Thinker re-teaches the step instead",
             md["judge_mistake_identified"]["baseline"],
             md["judge_mistake_identified"]["system"]),
            ("Wrong attempt: hands over the answer", "lower is better", md["answer_revealed_extractor"]["baseline"],
             md["answer_revealed_extractor"]["system"])]),
    ]
    heights = [len(rows) * 1.05 + 0.4 for _, rows in panels]
    fig, axes = plt.subplots(len(panels), 1, figsize=(7.16, 0.5 * sum(heights) + 0.6),
                             gridspec_kw={"height_ratios": heights, "hspace": 0.62})
    for ax, (title, rows) in zip(axes, panels):
        _paired_bars(ax, rows)
        ax.set_title(title, loc="left", color=INK, pad=5, x=-0.62)
        _axis(ax, xlim=(0, 100), ticks=[0, 25, 50, 75, 100])
    axes[-1].set_xlabel("Share of items (%); thin lines: 95% confidence intervals", color=SECONDARY, fontsize=FONT - 0.5)
    fig.subplots_adjust(left=0.36, right=0.97, top=0.92)
    _condition_legend(fig, 0.995)
    _save(fig, out, "fig_main_outcomes")


def fig_out_of_scope(m: dict, out: Path) -> None:
    oos = m["out_of_scope"]["by_expected_behaviour"]
    rows = [("Beyond Class 5: should decline", f"refuse or short gloss; n = {oos['decline']['n']}",
             oos["decline"]["baseline"], oos["decline"]["system"]),
            ("Beyond-Class-5 term: should gloss", f"short, formula-free; n = {oos['gloss']['n']}",
             oos["gloss"]["baseline"], oos["gloss"]["system"]),
            ("Sounds advanced, is Class 1-5: should answer", f"answering is correct; n = {oos['answer']['n']}",
             oos["answer"]["baseline"], oos["answer"]["system"])]
    fig, ax = plt.subplots(figsize=(3.5, 2.4))
    _paired_bars(ax, rows, bar_h=0.36, gap=1.1)
    _axis(ax, "Out-of-scope questions handled correctly (%)", xlim=(0, 100), ticks=[0, 25, 50, 75, 100])
    _condition_legend(ax, 1.0, loc="lower center")
    _save(fig, out, "fig_out_of_scope")


def fig_rubric(m: dict, out: Path) -> None:
    """Mean 1-5 rubric scores, the two team members beside the LLM judge, as
    paired bars from the scale's floor (1); the Holm-adjusted Wilcoxon result
    sits at the end of each pair."""
    dims = [("correctness", "Correctness"), ("grade_fit", "Fits the child's class"), ("clarity", "Clarity"),
            ("restraint", "Restraint (no padding)")]
    panels = [(m["human_ratings"]["rubric_mean_of_two"], "Two team members (75 paired replies)", set()),
              (m["judge_curriculum"]["rubric"], "LLM judge (935 curriculum replies)", {"clarity", "restraint"})]
    fig, axes = plt.subplots(1, 2, figsize=(7.16, 2.3), sharey=True, gridspec_kw={"wspace": 0.12})
    bar_h = 0.34
    for ax, (src, title, exploratory) in zip(axes, panels):
        for i, (key, label) in enumerate(dims):
            y, r = -i * 1.05, src[key]
            for (cond, _, color), v, dy in zip(CONDITIONS, (r["baseline_mean"], r["system_mean"]),
                                               (bar_h / 2 + 0.02, -bar_h / 2 - 0.02)):
                ax.barh(y + dy, v - 1, left=1, height=bar_h, color=color, zorder=2)
                ax.text(v - 0.05, y + dy, f"{v:.2f}", ha="right", va="center", fontsize=FONT - 0.6, color="white",
                        fontweight="bold", zorder=4)
            p = r.get("p_holm")
            sig = ("differs" if p < 0.05 else "no clear\ndifference") if p is not None else ""
            ax.text(5.08, y, sig + ("\n(exploratory)" if key in exploratory else ""), ha="left", va="center",
                    fontsize=FONT - 1.3, color=MUTED, style="italic", linespacing=1.1)
            if ax is axes[0]:
                ax.text(0.92, y, label, ha="right", va="center", fontsize=FONT, color=INK)
        ax.set_yticks([])
        ax.set_ylim(-(len(dims) - 1) * 1.05 - 0.55, 0.55)
        ax.set_title(title, loc="left", color=INK, pad=4, fontsize=FONT)
        _axis(ax, "Mean score (1 = poor, 5 = best)", xlim=(1, 5.75), ticks=[1, 2, 3, 4, 5])
    _condition_legend(fig, 1.08)
    _save(fig, out, "fig_rubric")


def fig_controller(m: dict, out: Path) -> None:
    by = {k: v for k, v in m["multi_turn"]["by_expected_action"].items() if v["n"] >= 10}
    items = sorted(by.items(), key=lambda kv: kv[1]["rate"], reverse=True)
    overall = m["multi_turn"]["controller_action_match"]
    fig, ax = plt.subplots(figsize=(3.5, 0.27 * len(items) + 0.8))
    for i, (k, r) in enumerate(items):
        y = len(items) - 1 - i
        v = 100 * r["rate"]
        ax.barh(y, v, height=0.6, color=SYSTEM, zorder=2)
        lo, hi = (100 * x for x in r["ci95"])
        ax.plot([lo, hi], [y, y], color=INK, linewidth=0.6, alpha=0.35, zorder=3)
        ax.text(-2, y, f"{MODE_LABELS.get(k, k)}  (n={r['n']})", ha="right", va="center", fontsize=FONT - 0.5,
                color=INK)
        inside = v >= 86
        ax.text(v - 1.2 if inside else max(v, hi) + 1.2, y, f"{v:.0f}%", ha="right" if inside else "left",
                va="center", fontsize=FONT - 0.8, color="white" if inside else SECONDARY,
                fontweight="bold" if inside else "normal", zorder=4)
    ax.axvline(100 * overall["rate"], color=MUTED, linewidth=0.8, linestyle=(0, (3, 2)), zorder=1)
    ax.text(100 * overall["rate"] - 1, len(items) - 0.35, f"all turns: {100 * overall['rate']:.0f}%", ha="right",
            va="bottom", fontsize=FONT - 1, color=SECONDARY)
    ax.set_yticks([])
    ax.set_ylim(-0.6, len(items) + 0.1)
    _axis(ax, "Turns where Tiny Thinker took the expected teaching action (%)", xlim=(0, 100),
          ticks=[0, 25, 50, 75, 100])
    _save(fig, out, "fig_controller")


def fig_latency(m: dict, out: Path) -> None:
    ls, pl = m["latency_svamp"], m["production_latency"]
    rows = [("Time to first word", "clean_ttft_s"), ("Full reply time", "clean_turn_wall_s")]
    fig, ax = plt.subplots(figsize=(3.5, 1.55))
    y = 0.0
    for label, key in rows:
        for (cond, _, color), dy in zip(CONDITIONS, (0.19, -0.19)):
            r = ls[cond][key]
            ax.barh(y + dy, r["median"], height=0.34, color=color, zorder=2)
            ax.plot(r["median_ci95"], [y + dy, y + dy], color=INK, linewidth=0.6, alpha=0.35, zorder=3)
            ax.text(max(r["median"], r["median_ci95"][1]) + 0.05, y + dy, f"{r['median']:.1f} s", va="center",
                    ha="left", fontsize=FONT - 0.6, color=SECONDARY)
        ax.text(-0.05, y, label, ha="right", va="center", fontsize=FONT, color=INK)
        y -= 1.0
    ax.set_yticks([])
    ax.set_ylim(y + 0.45, 0.55)
    _axis(ax, f"Median seconds per reply on SVAMP (no rate-limit waits). Live pilot median: {pl['latency_s']['median']:.1f} s",
          xlim=(0, 3), ticks=[0, 0.5, 1, 1.5, 2, 2.5, 3])
    ax.xaxis.label.set_size(FONT - 1.2)
    _condition_legend(ax, 1.0, loc="lower center")
    _save(fig, out, "fig_latency")


def figures(m: dict, out: Path) -> None:
    _base_style()
    for f in list(out.glob("fig_*")):
        f.unlink()
    fig_main_outcomes(m, out)
    fig_out_of_scope(m, out)
    fig_rubric(m, out)
    fig_controller(m, out)
    fig_latency(m, out)
