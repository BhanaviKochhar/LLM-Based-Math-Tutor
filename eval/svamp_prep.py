"""eval/svamp_prep.py -- build the SVAMP set the baseline and system
runners take unchanged (eval/datasets/svamp.jsonl).

Source: SVAMP (Patel et al., 2021), github.com/arkilpatel/SVAMP, file
SVAMP.json at commit 78e727689e1c1bebfc4be39c446898e8e10b0518, MIT license.
1,000 one-unknown arithmetic word problems, each with Body, Question,
Equation, a whole-number Answer and a Type.

All 1,000 problems are used (decided 2026-10-25, so results compare
directly with published SVAMP figures). --sample N instead draws N items
stratified by Type in proportion to the full set (largest-remainder
rounding), with random.Random(SEED) per type. "Common-Divison" (one item, a typo in the source) counts as Common-Division.

Items use the curriculum benchmark's fields where the harness reads them:
case_id, grade, question, expected_answer, trusted_expression (the source
Equation without its ".0"s), verifiable, accepted_equivalents. The source
text is kept on every item (svamp_body, svamp_question) so each change is
visible. One source answer that contradicts the source's own Equation is
corrected (ANSWER_CORRECTIONS), keeping the original as svamp_answer.

Text: the only change is how Body and Question are joined. SVAMP's Body
usually ends without punctuation ("... a discount of 25 dollars on each
pack" + "How much do you have to pay ..."). If the Body's last sentence
starts with "If", they are joined with ", " and the Question's first letter
is lowercased; otherwise with ". ". Nothing else is edited (dollars, names
and spellings stay as written).

Grade (SVAMP has none), from the largest number in the problem or its
answer and the operations in its Equation, against
docs/verified_ncert_class_1_5_topics.md:
  Class 1  addition/subtraction only, every number <= 20
  Class 2  addition/subtraction only, every number <= 99
  Class 3  addition/subtraction <= 999, or multiplication/division <= 100
  Class 4  every number <= 99,999
  Class 5  every number <= 99,999,999 (lakhs and crores)
An Equation with two or more operations is at least Class 3 (multi-step
word problems), and a decimal in the text makes it Class 5. Nothing is
dropped: an item needing maths beyond Class 5 (numbers above 8 digits, a
division that does not come out whole along the way, or a decimal
multiplied or divided) keeps its grade and gets a beyond_class_5_note.

Run:  python -m eval.svamp_prep --raw <path to SVAMP.json>
"""
from __future__ import annotations

import argparse
import ast
import json
import random
import re
from collections import Counter
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "eval" / "datasets" / "svamp.jsonl"
SEED = 20261024
SOURCE = {"url": "https://github.com/arkilpatel/SVAMP",
          "commit": "78e727689e1c1bebfc4be39c446898e8e10b0518",
          "file": "SVAMP.json", "license": "MIT"}
# Source answers that contradict the source's own Equation and Body; the
# item keeps the original as svamp_answer. chal-680: 4 apples, 2 picked,
# 3 more grew -> 5 (the Equation gives 5; the listed Answer is 1).
ANSWER_CORRECTIONS = {"chal-680": "5"}

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _type_of(row: dict) -> str:
    return "Common-Division" if row["Type"] == "Common-Divison" else row["Type"]


def _clean_number(text: str) -> str:
    """'76.0' -> '76'; anything with a real decimal part is left alone."""
    return text[:-2] if text.endswith(".0") else text


def trusted_expression(equation: str) -> str:
    expr = re.sub(r"\d+\.\d+", lambda m: _clean_number(m.group(0)), equation)
    expr = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", expr))
    expr = expr.strip()
    if expr.startswith("(") and expr.endswith(")") and _balanced(expr[1:-1]):
        expr = expr[1:-1]
    return expr


def _balanced(s: str) -> bool:
    depth = 0
    for ch in s:
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if depth < 0:
            return False
    return depth == 0


def join_text(body: str, question: str) -> str:
    body, question = body.strip(), question.strip()
    if body[-1:] in ".!?":
        return f"{body} {question}"
    last = _SENTENCE_SPLIT_RE.split(body)[-1]
    if last.lower().startswith("if "):
        return f"{body}, {question[:1].lower()}{question[1:]}"
    return f"{body}. {question}"


def _divisions_whole(equation: str) -> bool:
    """False if any division in the Equation leaves a fraction on the way."""
    whole = True

    def ev(node):
        nonlocal whole
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return Fraction(str(node.value))
        if isinstance(node, ast.BinOp):
            a, b = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if isinstance(node.op, ast.Div):
                q = a / b
                if q.denominator != 1:
                    whole = False
                return q
        raise ValueError(f"unexpected node in {equation!r}")

    ev(ast.parse(equation, mode="eval"))
    return whole


def grade_and_note(row: dict) -> tuple[int, str | None]:
    text = f"{row['Body']} {row['Question']}"
    numbers = [float(n.replace(",", "")) for n in _NUMBER_RE.findall(text)] + [float(row["Answer"])]
    biggest = max(numbers)
    ops = re.findall(r"[-+*/]", row["Equation"])
    muldiv = any(o in "*/" for o in ops)
    has_decimal = any(not n.is_integer() for n in numbers)

    if not muldiv and biggest <= 20:
        grade = 1
    elif not muldiv and biggest <= 99:
        grade = 2
    elif (not muldiv and biggest <= 999) or (muldiv and biggest <= 100):
        grade = 3
    elif biggest <= 99_999:
        grade = 4
    else:
        grade = 5
    if len(ops) >= 2:
        grade = max(grade, 3)
    if has_decimal:
        grade = 5

    notes = []
    if biggest > 99_999_999:
        notes.append("numbers above 8 digits")
    if not _divisions_whole(row["Equation"]):
        notes.append("a division that does not come out whole")
    if has_decimal and muldiv:
        notes.append("a decimal multiplied or divided")
    return grade, "; ".join(notes) or None


def stratified_sample(rows: list[dict], n: int, seed: int) -> list[dict]:
    by_type: dict[str, list[dict]] = {}
    for r in rows:
        by_type.setdefault(_type_of(r), []).append(r)
    exact = {t: n * len(v) / len(rows) for t, v in by_type.items()}
    quota = {t: int(x) for t, x in exact.items()}
    for t in sorted(exact, key=lambda t: exact[t] - quota[t], reverse=True)[: n - sum(quota.values())]:
        quota[t] += 1
    rng = random.Random(seed)
    picked = []
    for t in sorted(by_type):
        picked += rng.sample(by_type[t], quota[t])
    order = {r["ID"]: i for i, r in enumerate(rows)}
    return sorted(picked, key=lambda r: order[r["ID"]])


def build(rows: list[dict], sample: int | None = None) -> list[dict]:
    picked = stratified_sample(rows, sample, SEED) if sample else rows
    items = []
    for i, r in enumerate(picked, 1):
        grade, note = grade_and_note(r)
        answer = _clean_number(str(r["Answer"]))
        item = {"case_id": f"svamp-{i:04d}", "svamp_id": r["ID"], "svamp_type": _type_of(r),
                "grade": grade, "question_type": "word_problem",
                "question": join_text(r["Body"], r["Question"]),
                "expected_answer": answer, "accepted_equivalents": [],
                "trusted_expression": trusted_expression(r["Equation"]), "verifiable": True,
                "svamp_body": r["Body"], "svamp_question": r["Question"]}
        if r["ID"] in ANSWER_CORRECTIONS:
            item["expected_answer"] = ANSWER_CORRECTIONS[r["ID"]]
            item["svamp_answer"] = answer
        if note:
            item["beyond_class_5_note"] = note
        items.append(item)
    return items


def check(items: list[dict]) -> list[str]:
    """Offline checks: ids unique, every field the harness reads present,
    and the scorer reads exactly the source answer for every item."""
    from eval.score_transcripts import ground_truth_candidates
    from scripts.llm import verifier

    problems = []
    if len({it["case_id"] for it in items}) != len(items):
        problems.append("duplicate case_id")
    for it in items:
        missing = {"case_id", "grade", "question", "expected_answer", "trusted_expression"} - set(it)
        if missing:
            problems.append(f"{it['case_id']}: missing {sorted(missing)}")
        value = verifier._safe_eval(it["trusted_expression"])
        if value is None or Fraction(str(value)) != Fraction(it["expected_answer"]):
            problems.append(f"{it['case_id']}: {it['trusted_expression']} = {value}, expected {it['expected_answer']}")
        if ground_truth_candidates(it) != [it["expected_answer"]]:
            problems.append(f"{it['case_id']}: scorer reads {ground_truth_candidates(it)}")
    return problems


HEADER = [
    "# eval/datasets/svamp.jsonl -- all 1,000 SVAMP word problems (Patel et al., 2021)",
    f"#   from {SOURCE['url']} @ {SOURCE['commit'][:7]} ({SOURCE['license']} license).",
    "#   Built by eval/svamp_prep.py, which documents the text join, the grade",
    "#   rule and the beyond_class_5_note tags.",
    "# Fields: case_id, svamp_id, svamp_type, grade, question_type, question,",
    "#   expected_answer, accepted_equivalents, trusted_expression, verifiable,",
    "#   svamp_body, svamp_question, beyond_class_5_note and svamp_answer (a corrected",
    "#   source answer; see ANSWER_CORRECTIONS) on some items.",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True, help="path to SVAMP.json")
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--sample", type=int, default=None,
                        help="draw this many items stratified by type instead of all")
    args = parser.parse_args()

    rows = json.load(open(args.raw, encoding="utf-8"))
    items = build(rows, args.sample)
    problems = check(items)
    if problems:
        raise SystemExit("checks failed:\n  " + "\n  ".join(problems))
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(HEADER) + "\n")
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"{len(items)} items -> {args.out}")
    print("by type:", dict(Counter(it["svamp_type"] for it in items)))
    print("by grade:", dict(sorted(Counter(it["grade"] for it in items).items())))
    print("beyond Class 5:", sum(1 for it in items if "beyond_class_5_note" in it))


if __name__ == "__main__":
    main()
