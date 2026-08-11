"""eval/run_eval.py — baseline vs system evaluation (Objective 3).

Two conditions on the SAME questions:
  baseline : one LLM call, no classification, no injected answer, no verify.
             (prompt = v4-graded-refusal, computed_answer=None)
  system   : Tier A path — sympy solves first (when grade-appropriate), the
             answer is injected, the model explains, and check() confirms.

Scoring reads the stated final number from each answer and compares to the
sympy ground truth. Wrong-answer rate is the headline. Division questions that
are taught as quotient+remainder accept BOTH the exact value and the integer
quotient as correct, so a correct "5 R 5" isn't marked wrong.

Run:
    python -m eval.run_eval --mock            # offline logic check, no API
    python -m eval.run_eval --no-retrieval    # live, skip ChromaDB
    python -m eval.run_eval                    # live, retrieval on
Options:
    --sleep N   seconds between questions (default 3.0; raise if you see 429s)
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from scripts.llm import prompt_registry, response_parser, verifier

_PLAIN_DIV = re.compile(r"^\s*\d+\s*/\s*\d+\s*$")

# `truth` is a plain arithmetic string sympy evaluates identically for both
# conditions. Extend freely — aim for a spread of grades and operations.
from eval.eval_set import EVAL_SET


def _truth_value(item):
    return verifier._safe_eval(item["truth"])


def _accepted_values(item):
    """The set of numerically-correct answers. For a bare non-exact division,
    the integer quotient (remainder form) is also correct at primary level."""
    truth = _truth_value(item)
    accepted = [truth]
    if _PLAIN_DIV.match(item["truth"]):
        try:
            if truth != int(truth):
                import sympy
                accepted.append(sympy.Integer(int(truth)))  # floor quotient
        except (TypeError, ValueError):
            pass
    return accepted


def _generate(messages):
    from scripts.llm import llm_client
    return (llm_client.chat(messages).get("text") or "").strip()


def _retrieve(question, grade, use_retrieval):
    if not use_retrieval:
        return []
    try:
        from scripts.retrieval import retrieve
        return retrieve(question, grade)
    except Exception:
        return []


def run_condition(item, condition, use_retrieval, mock):
    truth = _truth_value(item)
    accepted = _accepted_values(item)
    chunks = _retrieve(item["q"], item["grade"], use_retrieval)

    if condition == "system":
        if mock:
            injected = verifier._grade_appropriate_answer(item["truth"], truth)
        else:
            injected, _ = verifier.solve(item["q"], item["grade"])
        messages = prompt_registry.build_messages(
            item["q"], item["grade"], chunks, version="v5-personalized",
            level="intermediate", computed_answer=injected)
    else:
        injected = None
        messages = prompt_registry.build_messages(
            item["q"], item["grade"], chunks, version="v4-graded-refusal",
            level="intermediate", computed_answer=None)

    if mock:
        if condition == "system" and injected is not None:
            text = f"...working...\nAnswer: {injected}"
        elif condition == "system":
            # remainder case: model teaches quotient form
            text = f"...working...\nAnswer: {int(truth)} remainder ..."
        else:
            hard = item["truth"] in {"45/8", "1/2+1/4"}
            stated = "5" if hard else verifier.format_value(truth)
            text = f"...working...\nAnswer: {stated}"
    else:
        text = _generate(messages)

    num_str = response_parser.final_number_str(text)
    stated_val = verifier._safe_eval(num_str) if num_str else None
    if stated_val is None:
        return {"stated": None, "correct": None, "no_number": True, "injected": injected}
    correct = any(verifier._close(a, stated_val) for a in accepted)
    return {"stated": str(stated_val), "correct": bool(correct),
            "no_number": False, "injected": injected}


def summarize(rows, condition):
    n = len(rows)
    wrong = sum(1 for r in rows if r[condition]["correct"] is False)
    right = sum(1 for r in rows if r[condition]["correct"] is True)
    nonum = sum(1 for r in rows if r[condition]["no_number"])
    return {"condition": condition, "n": n, "correct": right, "wrong": wrong,
            "no_number": nonum,
            "wrong_rate": round(wrong / n, 3) if n else 0.0,
            "correct_rate": round(right / n, 3) if n else 0.0}


def main():
    ap = argparse.ArgumentParser(description="Baseline vs system math-tutor eval.")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--no-retrieval", action="store_true")
    ap.add_argument("--sleep", type=float, default=3.0,
                    help="seconds between questions (raise if you hit 429s)")
    ap.add_argument("--out", default="data/eval_baseline_vs_system.json")
    args = ap.parse_args()

    use_retrieval = not args.no_retrieval and not args.mock
    rows = []
    print(f"{'#':>2}  {'grade':>5}  {'truth':>10}  {'baseline':>12}  {'system':>12}")
    print("-" * 60)
    for i, item in enumerate(EVAL_SET, 1):
        base = run_condition(item, "baseline", use_retrieval, args.mock)
        syst = run_condition(item, "system", use_retrieval, args.mock)
        rows.append({"item": item, "cat": item.get("cat", "other"), "baseline": base, "system": syst})

        def cell(r):
            if r["no_number"]:
                return "no-number"
            return ("OK " if r["correct"] else "WRONG ") + str(r["stated"])
        print(f"{i:>2}  {item['grade']:>5}  "
              f"{str(verifier.format_value(_truth_value(item))):>10}"
              f"  {cell(base):>12}  {cell(syst):>12}")
        if not args.mock:
            time.sleep(args.sleep)

    base_sum = summarize(rows, "baseline")
    sys_sum = summarize(rows, "system")
    print("\n=== summary ===")
    for s in (base_sum, sys_sum):
        print(f"{s['condition']:>8}: wrong {s['wrong']}/{s['n']} "
              f"(rate {s['wrong_rate']}) . correct {s['correct']} . "
              f"no-number {s['no_number']}")
    # per-category breakdown — where the gap actually is
    cats = {}
    for r in rows:
        cats.setdefault(r["cat"], []).append(r)
    print("\n=== by category (wrong / n) ===")
    print(f"{'category':>14}  {'baseline':>10}  {'system':>10}")
    for cat, rs in cats.items():
        b = sum(1 for r in rs if r["baseline"]["correct"] is False)
        y = sum(1 for r in rs if r["system"]["correct"] is False)
        print(f"{cat:>14}  {str(b)+'/'+str(len(rs)):>10}  {str(y)+'/'+str(len(rs)):>10}")

    reduction = base_sum["wrong_rate"] - sys_sum["wrong_rate"]
    print(f"\nwrong-answer-rate reduction (baseline - system): {round(reduction, 3)}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"rows": rows, "baseline": base_sum, "system": sys_sum},
                  f, indent=2, ensure_ascii=False, default=str)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()

# """eval/run_eval.py — baseline vs system evaluation (Objective 3).

# Two conditions on the SAME questions:
#   baseline : one LLM call, no classification, no injected answer, no verify.
#              (prompt = v4-graded-refusal, computed_answer=None)
#   system   : Tier A path — sympy solves first (when grade-appropriate), the
#              answer is injected, the model explains, and check() confirms.

# Scoring reads the stated final number from each answer and compares to the
# sympy ground truth. Wrong-answer rate is the headline. Division questions that
# are taught as quotient+remainder accept BOTH the exact value and the integer
# quotient as correct, so a correct "5 R 5" isn't marked wrong.

# Run:
#     python -m eval.run_eval --mock            # offline logic check, no API
#     python -m eval.run_eval --no-retrieval    # live, skip ChromaDB
#     python -m eval.run_eval                    # live, retrieval on
# Options:
#     --sleep N   seconds between questions (default 3.0; raise if you see 429s)
# """
# from __future__ import annotations

# import argparse
# import json
# import re
# import time
# from pathlib import Path

# from scripts.llm import prompt_registry, response_parser, verifier

# _PLAIN_DIV = re.compile(r"^\s*\d+\s*/\s*\d+\s*$")

# # `truth` is a plain arithmetic string sympy evaluates identically for both
# # conditions. Extend freely — aim for a spread of grades and operations.
# EVAL_SET = [
#     {"q": "What is 7 times 8?", "grade": 3, "truth": "7*8"},
#     {"q": "I have 8 balloons and 3 fly away. How many are left?", "grade": 1, "truth": "8-3"},
#     {"q": "How can I share 12 toffees equally among 4 friends?", "grade": 2, "truth": "12/4"},
#     {"q": "What is 45 divided by 8?", "grade": 4, "truth": "45/8"},
#     {"q": "What is 1/2 + 1/4?", "grade": 4, "truth": "1/2+1/4"},
#     {"q": "What is 1/2 of 8?", "grade": 3, "truth": "(1/2)*8"},
#     {"q": "What is the perimeter of a square with side 5 cm?", "grade": 4, "truth": "4*5"},
#     {"q": "What is the area of a rectangle 4 cm by 7 cm?", "grade": 5, "truth": "4*7"},
#     {"q": "What comes after 49?", "grade": 1, "truth": "49+1"},
#     {"q": "What is 27 plus 15?", "grade": 2, "truth": "27+15"},
#     {"q": "A pencil costs 6 rupees. How much do 7 pencils cost?", "grade": 3, "truth": "6*7"},
#     {"q": "There are 24 sweets shared among 6 children. How many each?", "grade": 3, "truth": "24/6"},
# ]


# def _truth_value(item):
#     return verifier._safe_eval(item["truth"])


# def _accepted_values(item):
#     """The set of numerically-correct answers. For a bare non-exact division,
#     the integer quotient (remainder form) is also correct at primary level."""
#     truth = _truth_value(item)
#     accepted = [truth]
#     if _PLAIN_DIV.match(item["truth"]):
#         try:
#             if truth != int(truth):
#                 import sympy
#                 accepted.append(sympy.Integer(int(truth)))  # floor quotient
#         except (TypeError, ValueError):
#             pass
#     return accepted


# def _generate(messages):
#     from scripts.llm import llm_client
#     return (llm_client.chat(messages).get("text") or "").strip()


# def _retrieve(question, grade, use_retrieval):
#     if not use_retrieval:
#         return []
#     try:
#         from scripts.retrieval import retrieve
#         return retrieve(question, grade)
#     except Exception:
#         return []


# def run_condition(item, condition, use_retrieval, mock):
#     truth = _truth_value(item)
#     accepted = _accepted_values(item)
#     chunks = _retrieve(item["q"], item["grade"], use_retrieval)

#     if condition == "system":
#         if mock:
#             injected = verifier._grade_appropriate_answer(item["truth"], truth)
#         else:
#             injected, _ = verifier.solve(item["q"], item["grade"])
#         messages = prompt_registry.build_messages(
#             item["q"], item["grade"], chunks, version="v5-personalized",
#             level="intermediate", computed_answer=injected)
#     else:
#         injected = None
#         messages = prompt_registry.build_messages(
#             item["q"], item["grade"], chunks, version="v4-graded-refusal",
#             level="intermediate", computed_answer=None)

#     if mock:
#         if condition == "system" and injected is not None:
#             text = f"...working...\nAnswer: {injected}"
#         elif condition == "system":
#             # remainder case: model teaches quotient form
#             text = f"...working...\nAnswer: {int(truth)} remainder ..."
#         else:
#             hard = item["truth"] in {"45/8", "1/2+1/4"}
#             stated = "5" if hard else verifier.format_value(truth)
#             text = f"...working...\nAnswer: {stated}"
#     else:
#         text = _generate(messages)

#     num_str = response_parser.final_number_str(text)
#     stated_val = verifier._safe_eval(num_str) if num_str else None
#     if stated_val is None:
#         return {"stated": None, "correct": None, "no_number": True, "injected": injected}
#     correct = any(verifier._close(a, stated_val) for a in accepted)
#     return {"stated": str(stated_val), "correct": bool(correct),
#             "no_number": False, "injected": injected}


# def summarize(rows, condition):
#     n = len(rows)
#     wrong = sum(1 for r in rows if r[condition]["correct"] is False)
#     right = sum(1 for r in rows if r[condition]["correct"] is True)
#     nonum = sum(1 for r in rows if r[condition]["no_number"])
#     return {"condition": condition, "n": n, "correct": right, "wrong": wrong,
#             "no_number": nonum,
#             "wrong_rate": round(wrong / n, 3) if n else 0.0,
#             "correct_rate": round(right / n, 3) if n else 0.0}


# def main():
#     ap = argparse.ArgumentParser(description="Baseline vs system math-tutor eval.")
#     ap.add_argument("--mock", action="store_true")
#     ap.add_argument("--no-retrieval", action="store_true")
#     ap.add_argument("--sleep", type=float, default=3.0,
#                     help="seconds between questions (raise if you hit 429s)")
#     ap.add_argument("--out", default="data/eval_baseline_vs_system.json")
#     args = ap.parse_args()

#     use_retrieval = not args.no_retrieval and not args.mock
#     rows = []
#     print(f"{'#':>2}  {'grade':>5}  {'truth':>10}  {'baseline':>12}  {'system':>12}")
#     print("-" * 60)
#     for i, item in enumerate(EVAL_SET, 1):
#         base = run_condition(item, "baseline", use_retrieval, args.mock)
#         syst = run_condition(item, "system", use_retrieval, args.mock)
#         rows.append({"item": item, "baseline": base, "system": syst})

#         def cell(r):
#             if r["no_number"]:
#                 return "no-number"
#             return ("OK " if r["correct"] else "WRONG ") + str(r["stated"])
#         print(f"{i:>2}  {item['grade']:>5}  "
#               f"{str(verifier.format_value(_truth_value(item))):>10}"
#               f"  {cell(base):>12}  {cell(syst):>12}")
#         if not args.mock:
#             time.sleep(args.sleep)

#     base_sum = summarize(rows, "baseline")
#     sys_sum = summarize(rows, "system")
#     print("\n=== summary ===")
#     for s in (base_sum, sys_sum):
#         print(f"{s['condition']:>8}: wrong {s['wrong']}/{s['n']} "
#               f"(rate {s['wrong_rate']}) . correct {s['correct']} . "
#               f"no-number {s['no_number']}")
#     reduction = base_sum["wrong_rate"] - sys_sum["wrong_rate"]
#     print(f"\nwrong-answer-rate reduction (baseline - system): {round(reduction, 3)}")

#     out = Path(args.out)
#     out.parent.mkdir(parents=True, exist_ok=True)
#     with open(out, "w", encoding="utf-8") as f:
#         json.dump({"rows": rows, "baseline": base_sum, "system": sys_sum},
#                   f, indent=2, ensure_ascii=False, default=str)
#     print(f"\nwrote {out}")


# if __name__ == "__main__":
#     main()