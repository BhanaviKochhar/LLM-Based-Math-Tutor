"""eval/mathdial_prep.py -- build the MathDial "student mistake" sample the
baseline and system runners take unchanged (eval/datasets/mathdial_sample.jsonl).

Source: MathDial (Macina et al., EMNLP 2023 Findings), github.com/eth-nlped/mathdial,
file data/test.jsonl at commit b06c020a0a1f57a87577fec33e657b63e7eb476e,
CC BY-SA 4.0. 599 GSM8K problems, each with a simulated student's incorrect
solution and the confusion a teacher named for it.

Each item is the child's single message: the problem, then the student's own
wrong working, then "Is my answer right?". It tests what a tutor does with a
wrong attempt -- spot the mistake and guide, or simply hand over the answer
-- which SVAMP (solving only) cannot.

Class 1-5 filter:
  - the correct solution (ground_truth) has at most 4 calculation steps, and
    every number in the problem, every step result and the answer is a whole
    number from 0 to 99,999,999; no percentages;
  - the student's wrong working uses arithmetic only: no letters standing for
    numbers ("let x", "x + 5"), no "equation", and no negative results -- a
    Class 1-5 child would not write those, and the scope check would rightly
    stop them, which would test the gate instead of the tutoring.
Graded with eval/svamp_prep.py's rule, 3+ steps counting as at least Class 4.

Sample: SAMPLE_SIZE problems, random.Random(SEED). The forced give-up turn is
switched off (no_forced_reveal): the measure is the tutor's reply to the
attempt, not a later reveal.

Run:  python -m eval.mathdial_prep --raw <path to test.jsonl>
"""
from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from fractions import Fraction
from pathlib import Path

from eval.svamp_prep import grade_and_note

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "eval" / "datasets" / "mathdial_sample.jsonl"
SEED = 20261027
SAMPLE_SIZE = 100
MAX_STEPS = 4
SOURCE = {"url": "https://github.com/eth-nlped/mathdial", "commit": "b06c020a0a1f57a87577fec33e657b63e7eb476e",
          "file": "data/test.jsonl", "license": "CC BY-SA 4.0"}

_STEP_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?(?:\s*[-+*/x×÷]\s*\d[\d,]*(?:\.\d+)?)+)\s*=\s*(-?\d[\d,]*(?:\.\d+)?)")
_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
# A letter standing for a number: "let x", "equation", or a lone letter next
# to an operator or "=" that is not a times sign between two numbers ("3 x 4").
_ALGEBRA_RE = re.compile(r"\blet\s+[a-z]\b|\bequations?\b|\bvariables?\b|\bunknown\b|\b\d+[a-z]\s*[-+=]"
                         r"|(?<![\d)]\s)(?<![\d)])\b[a-z]\b\s*(?:[-+*/=]|\))"
                         r"|(?:[-+*/=(])\s*\b[a-z]\b(?!\s*\d)", re.IGNORECASE)


def _whole(text: str) -> bool:
    try:
        v = Fraction(text.replace(",", "").strip())
    except (ValueError, ZeroDivisionError):
        return False
    return v.denominator == 1 and 0 <= v <= 99_999_999


def final_number(text: str) -> str | None:
    nums = _NUMBER_RE.findall((text or "").strip().splitlines()[-1] if text and text.strip() else "")
    return nums[-1].replace(",", "") if nums else None


def steps(solution: str) -> list[tuple[str, str]]:
    return _STEP_RE.findall(solution or "")


def eligible(row: dict) -> bool:
    gt, q, wrong = row["ground_truth"], row["question"], row["student_incorrect_solution"]
    st, answer, student = steps(gt), final_number(gt), final_number(wrong)
    if not st or len(st) > MAX_STEPS or not answer or not student or answer == student:
        return False
    if "%" in q or "percent" in q.lower() or _ALGEBRA_RE.search(wrong):
        return False
    numbers = _NUMBER_RE.findall(q) + [r for _, r in st] + [answer] + _NUMBER_RE.findall(wrong)
    return all(_whole(n) for n in numbers)


def grade_of(row: dict) -> tuple[int, str | None]:
    st = steps(row["ground_truth"])
    equation = " + ".join(f"( {e.replace(',', '').replace('x', '*').replace('×', '*').replace('÷', '/')} )"
                          for e, _ in st)
    g, note = grade_and_note({"Body": row["question"], "Question": "", "Equation": equation,
                              "Answer": float(Fraction(final_number(row["ground_truth"])))})
    return (max(g, 4) if len(st) >= 3 else g), note


def message(row: dict) -> str:
    working = row["student_incorrect_solution"].strip()
    return f"{row['question'].strip()}\n\nThis is how I did it:\n{working}\n\nIs my answer right?"


def build(rows: list[dict]) -> tuple[list[dict], int]:
    # A problem can appear with several students' attempts; keep the first
    # eligible attempt per problem so no problem is asked twice.
    pool, seen = [], set()
    for r in rows:
        if eligible(r) and r["qid"] not in seen:
            seen.add(r["qid"])
            pool.append(r)
    rng = random.Random(SEED)
    picked = rng.sample(pool, min(SAMPLE_SIZE, len(pool)))
    picked.sort(key=lambda r: int(r["qid"]))
    items = []
    for n, r in enumerate(picked, 1):
        grade, note = grade_of(r)
        item = {"case_id": f"mathdial-{n:03d}", "mathdial_qid": r["qid"], "grade": grade,
                "question_type": "student_mistake", "question": message(r),
                "problem": r["question"].strip(), "expected_answer": final_number(r["ground_truth"]),
                "student_answer": final_number(r["student_incorrect_solution"]),
                "student_confusion": r.get("teacher_described_confusion") or "",
                "accepted_equivalents": [], "verifiable": True, "no_forced_reveal": True,
                "solution_steps": len(steps(r["ground_truth"]))}
        if note:
            item["beyond_class_5_note"] = note
        items.append(item)
    return items, len(pool)


def check(items: list[dict]) -> list[str]:
    from eval.score_transcripts import ground_truth_candidates
    problems = []
    if len({i["case_id"] for i in items}) != len(items) or len({i["mathdial_qid"] for i in items}) != len(items):
        problems.append("duplicate ids")
    for it in items:
        if ground_truth_candidates(it) != [it["expected_answer"]]:
            problems.append(f"{it['case_id']}: scorer reads {ground_truth_candidates(it)}")
        if it["student_answer"] == it["expected_answer"]:
            problems.append(f"{it['case_id']}: the student's answer is not wrong")
    return problems


HEADER = [
    "# eval/datasets/mathdial_sample.jsonl -- MathDial (Macina et al., 2023) problems with a student's",
    f"#   incorrect working, filtered to Class 1-5 arithmetic; {SOURCE['url']} @ {SOURCE['commit'][:7]}",
    f"#   ({SOURCE['license']}). Seed {SEED}. Built by eval/mathdial_prep.py, which documents the filter.",
    "# Fields: case_id, mathdial_qid, grade, question_type, question (problem + the student's working +",
    "#   'Is my answer right?'), problem, expected_answer, student_answer, student_confusion,",
    "#   accepted_equivalents, verifiable, no_forced_reveal, solution_steps, beyond_class_5_note (some).",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    rows = [json.loads(l) for l in open(args.raw, encoding="utf-8") if l.strip()]
    items, pool = build(rows)
    problems = check(items)
    if problems:
        raise SystemExit("checks failed:\n  " + "\n  ".join(problems))
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(HEADER) + "\n")
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"eligible Class 1-5 problems: {pool} of {len(rows)}")
    print(f"{len(items)} items -> {args.out}")
    print("by grade:", dict(sorted(Counter(i["grade"] for i in items).items())))
    print("by steps:", dict(sorted(Counter(i["solution_steps"] for i in items).items())))
    print("beyond Class 5:", sum("beyond_class_5_note" in i for i in items))


if __name__ == "__main__":
    main()
