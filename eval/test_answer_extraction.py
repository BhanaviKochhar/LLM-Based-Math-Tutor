"""eval/test_answer_extraction.py — offline tests for the committed-answer
extractor (eval/answer_extraction.py) and the out-of-scope / paired-stats
scoring in eval/score_transcripts.py.

Every case below is a real response shape from the v1 transcripts (item id
in the test name) that an earlier version of the scorer got wrong in one
direction or the other. Deterministic, no LLM, no network; same check()
convention as eval/component_eval/test_component_eval.py.

Run:  python -m eval.test_answer_extraction
"""
from __future__ import annotations

from eval import answer_extraction as ax
from eval import score_transcripts as st

_passed = 0
_failed = 0


def check(name: str, cond: bool) -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok   {name}")
    else:
        _failed += 1
        print(f"  FAIL {name}")


def verdict(text: str, candidates: list[str], question: str = "") -> bool | None:
    return ax.judge(ax.committed_answer(text), candidates, question)


def test_no_substring_rescue() -> None:
    print("no credit for the expected value appearing somewhere else")
    essay = ("The LCM of 4 and 6 is 12 and the HCF is 2.\n\n"
             "Bottom line: for two different numbers the LCM is larger.\n\nAnswer: no")
    check("cb-908 '4' inside an essay is not an answer of 4", verdict(essay, ["4"], "LCM vs HCF of 4?") is not True)
    check("cb-067 '589 > 598' is wrong for 598",
          verdict("So the answer is:\n\n**589 > 598**\n\nKeep practicing!", ["598"],
                  "Which is greater, 589 or 598?") is False)


def test_answer_line() -> None:
    print("Answer: lines")
    check("plain Answer line", verdict("Steps...\n\nAnswer: 7", ["7"], "What is 3 + 4?") is True)
    check("RHS of an equation on the Answer line (cb-919)",
          verdict("**Answer:** 7/12 + 1/4 = 5/6", ["5/6"], "Add 7/12 and 1/4.") is True)
    check("Answer heading with the value on the next line (cb-914)",
          verdict("**Answer**\n\nThe second runner finishes in **13.55 seconds**.", ["271/20"],
                  "14.35 s minus 0.8 s?") is True)
    check("practice question after the Answer line is ignored (cb-819 shape)",
          verdict("... = **6** lines.\n\n**Practice:** How many lines does an octagon have?\n\nAnswer: 6",
                  ["6"], "Lines of symmetry of a regular hexagon?") is True)
    check("bare yes/no Answer line on a numeric item is undecided (cb-780)",
          verdict("Because we still multiply by 2, the answer is **no**.\n\nAnswer: no", ["14"],
                  "Do you just count the symbols?") is None)


def test_concluding_sentences() -> None:
    print("concluding sentences and bold results")
    check("result is the non-input number (cb-241)",
          verdict("So, after giving away 1 balloon, **Neha has 5 balloons left**.", ["5"],
                  "Neha has 6 balloons and gives away 1. How many are left?") is True)
    check("comparison falls back to the first number (cb-211)",
          verdict("**So, 7 is greater than 3.**", ["7"], "Which is greater, 7 or 3?") is True)
    check("'that is 10 more than 47 is 57' (cb-045)",
          verdict("**So, the number that is 10 more than 47 is 57.**", ["57"], "What is 10 more than 47?") is True)
    check("number word result (cb-537)",
          verdict("You simply have **no groups** of 6, so the total amount is zero.", ["0"],
                  "What is 6 times 0?") is True)
    check("value on the line after 'So,' (cb-577)",
          verdict("Multiply:\n\nSo,\n\n5 litres = 5000 millilitres", ["5000"],
                  "How many ml in 5 litres?") is True)
    check("parenthetical aside ignored (cb-851)",
          verdict("**Answer:** The two pieces together are 4/5 metre long (which is 80 cm).", ["4/5"],
                  "3/5 m and 1/5 m together?") is True)
    check("thin-space thousands separator (cb-571)",
          verdict("So, a bag that weighs **2 kilograms is 2 000 grams**.", ["2000"],
                  "How many grams in 2 kg?") is True)
    check("lakh notation (cb-792)",
          verdict("So, 9,99,500 rounded to the nearest thousand is **10 lakh** (10,00,000).",
                  ["1000000"], "Round 9,99,500 to the nearest thousand.") is True)
    check("conversion question keeps its answer (cb-139)",
          verdict("So for **15 lakh**:\n\n15 x 100000 = 1500000\n\n**Plain numerals:** **1,500,000** people.",
                  ["1500000"], "About 15 lakh people: how many in plain numerals?") is True)


def test_times_and_remainders() -> None:
    print("clock times, quotient-remainder, lists")
    check("spaced clock time (cb-440)", verdict("**Answer:**\nIn 50 minutes it will be **9 : 10**.", ["9:10"]) is True)
    check("decimal is not a clock time (cb-918)",
          verdict("**Answer:** The tailor has **0.75 metres** left.", ["3/4"], "1.5 m minus 0.75 m?") is True)
    check("minutes after midnight is wrong for a clock time (cb-480)",
          verdict("You've done it!\n\nAnswer: 425", ["7:05"], "Leaves 6:15, travels 50 min. Arrives?") is False)
    check("'Answer: 5' for 5:00 (cb-434)", verdict("Answer: 5", ["5:00"], "3 o'clock plus 2 hours?") is True)
    check("'half past 4' is 4:30 (cb-096)", verdict("So the time is half past 4.", ["4:30"]) is True)
    check("two-line quotient and remainder (cb-084)",
          verdict("### Answer\n- **Each student gets:** **4 pencils**\n- **Pencils left over:** **3 pencils**",
                  ["4 remainder 3"], "Share 23 pencils among 5 students.") is True)
    check("factor list in display math (cb-831)",
          verdict("Now list them:\n\n\\[\n1,\\;2,\\;3,\\;4,\\;6,\\;9,\\;12,\\;18,\\;36\n\\]\n\n"
                  "These nine numbers are all the factors of 36.", ["1, 2, 3, 4, 6, 9, 12, 18, 36"],
                  "List the factors of 36.") is True)


def test_truncation() -> None:
    print("truncation")
    check("cut off mid-word", ax.is_truncated("A logarith"))
    check("ends on an Answer line", not ax.is_truncated("Steps.\n\nAnswer: 425"))
    check("ends with an emoji", not ax.is_truncated("Great job! \U0001F31F"))


def test_out_of_scope_scheme() -> None:
    print("out-of-scope three-outcome scoring")
    gloss_item = {"truly_out_of_scope": True, "boundary_case": False,
                  "expected_behavior": "Give a short, warm, formula-free gloss of what the topic roughly means."}
    decline_item = {"truly_out_of_scope": True, "boundary_case": True, "expected_behavior": "Decline."}
    probe = {"truly_out_of_scope": False, "boundary_case": True, "expected_behavior": "Must answer normally."}
    sys_gloss = {"turns": [{"response": "Algebra uses letters for numbers. You'll learn it later!", "mode": None}]}
    sys_refused = {"turns": [{"response": "Let's ask your teacher about this one!", "mode": "scope_refused"}]}
    sys_taught = {"turns": [{"response": "Step 1...", "mode": "teach_invite"},
                            {"response": "Answer: 4", "mode": "co_solve"}]}
    sys_cut = {"turns": [{"response": "A logarith", "mode": None}]}
    base_reply = {"turns": [{"response": "Algebra is... e.g. x + 3 = 5 so x = 2."}]}
    check("system gloss on a gloss item is correct (oos-036)",
          st.score_item(gloss_item, sys_gloss)["correct"] is True)
    check("cut-off gloss is wrong (oos-116)",
          st.score_item(gloss_item, sys_cut)["correct"] is False)
    check("gloss on a decline item counts as a decline (oos-006)",
          st.score_item(decline_item, sys_gloss)["correct"] is True)
    check("refusal on a decline item is correct", st.score_item(decline_item, sys_refused)["correct"] is True)
    check("teaching a decline item is wrong", st.score_item(decline_item, sys_taught)["correct"] is False)
    check("refusing an in-scope probe is wrong", st.score_item(probe, sys_refused)["correct"] is False)
    r = st.score_item(gloss_item, base_reply)
    check("baseline on a gloss item waits for the judge", r["correct"] is None and r.get("needs_judge"))


def test_paired_stats() -> None:
    print("paired statistics")
    # Newcombe (1998) Table III, method 10: e, f, g, h -> interval.
    for (e, f, g, h), (lo, hi) in [((36, 12, 2, 0), (0.0569, 0.3404)),
                                   ((20, 12, 2, 16), (0.0562, 0.3292)),
                                   ((18, 12, 2, 18), (0.0562, 0.3290))]:
        _, l, u = st.newcombe_paired_ci(e, g, f, h)
        check(f"Newcombe method 10 matches Table III for {e},{f},{g},{h}",
              round(l, 4) == lo and round(u, 4) == hi)
    check("McNemar exact, no discordant pairs", st.mcnemar_exact_p(0, 0) == 1.0)
    check("McNemar exact, 0 vs 6", abs(st.mcnemar_exact_p(0, 6) - 0.03125) < 1e-12)
    rows = [{"mcnemar_p": 0.01}, {"mcnemar_p": 0.04}, {"mcnemar_p": 0.03}]
    st.holm_adjust(rows)
    check("Holm adjustment", [round(r["mcnemar_p_holm"], 2) for r in rows] == [0.03, 0.06, 0.06])


def main() -> None:
    test_no_substring_rescue()
    test_answer_line()
    test_concluding_sentences()
    test_times_and_remainders()
    test_truncation()
    test_out_of_scope_scheme()
    test_paired_stats()
    print(f"\n{_passed} passed, {_failed} failed")
    if _failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
