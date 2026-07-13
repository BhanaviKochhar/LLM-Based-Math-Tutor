"""
scripts/eval_retrieval.py — Day 6-7 retrieval evaluation (KEYWORD-BASED)

Why keyword-based: all 2329 chunks have topic=None (parser never tagged them),
so instead of topic-matching we check whether the retrieved chunks contain
words that a genuinely relevant chunk would contain.

Metrics:
    Keyword hit-rate  = for each question, does at least one of the top-3
                        retrieved chunks contain at least one expected keyword?
    Grade accuracy    = % of retrieved chunks within the allowed grade window
                        (grade or grade-1). Must be 100%.

Run (from project root):
    python -u scripts/eval_retrieval.py
"""

import json
import re
from collections import defaultdict
from pathlib import Path

from retrieval import retrieve_with_metadata, _grade_filter

# ---------------------------------------------------------------------------
# 20 test questions, 4 per grade. `keywords` = words a relevant chunk should
# contain (lowercase; substring match). Add/edit freely.
# ---------------------------------------------------------------------------
TEST_QUESTIONS = [
    # Class 1
    {"q": "How many altogether if I have 2 apples and 3 apples?", "grade": 1,
     "keywords": ["add", "altogether", "together", "sum", "more"]},
    {"q": "What comes after the number 7?", "grade": 1,
     "keywords": ["after", "before", "next", "count", "number"]},
    {"q": "Which shape is round like a ball?", "grade": 1,
     "keywords": ["round", "shape", "circle", "ball"]},
    {"q": "If I give away 2 of my 5 toffees, how many are left?", "grade": 1,
     "keywords": ["left", "take away", "gave", "remain", "subtract"]},
    # Class 2
    {"q": "How do I count in tens and ones?", "grade": 2,
     "keywords": ["tens", "ones", "ten", "bundle"]},
    {"q": "What is 25 plus 13?", "grade": 2,
     "keywords": ["add", "plus", "sum", "altogether"]},
    {"q": "How do I measure length with a scale?", "grade": 2,
     "keywords": ["measure", "length", "long", "scale", "centimetre", "cm"]},
    {"q": "What are the days of the week in order?", "grade": 2,
     "keywords": ["day", "week", "monday", "sunday", "calendar"]},
    # Class 3
    {"q": "How do I subtract with borrowing?", "grade": 3,
     "keywords": ["subtract", "take away", "borrow", "left", "minus"]},
    {"q": "What is multiplication as repeated addition?", "grade": 3,
     "keywords": ["multipl", "times", "repeated", "groups of"]},
    {"q": "How do I share 12 laddoos equally among 4 friends?", "grade": 3,
     "keywords": ["share", "divide", "equal", "distribut", "each"]},
    {"q": "How do I read time on a clock?", "grade": 3,
     "keywords": ["clock", "time", "hour", "minute", "hand"]},
    # Class 4
    {"q": "What is a fraction of a whole?", "grade": 4,
     "keywords": ["fraction", "half", "quarter", "part", "whole"]},
    {"q": "How do I multiply a 2-digit number by a 1-digit number?", "grade": 4,
     "keywords": ["multipl", "times", "product", "digit"]},
    {"q": "How do I find the perimeter of a field?", "grade": 4,
     "keywords": ["perimeter", "boundary", "around", "fence"]},
    {"q": "How many grams are there in one kilogram?", "grade": 4,
     "keywords": ["gram", "kilogram", "kg", "weigh", "weight"]},
    # Class 5
    {"q": "How do I add two fractions with different denominators?", "grade": 5,
     "keywords": ["fraction", "denominator", "numerator", "half", "equal parts"]},
    {"q": "What are decimals and how do I read them?", "grade": 5,
     "keywords": ["decimal", "point", "tenth", "hundredth"]},
    {"q": "How do I find the area of a rectangle?", "grade": 5,
     "keywords": ["area", "square", "rectangle", "cover"]},
    {"q": "What is a factor and what is a multiple?", "grade": 5,
     "keywords": ["factor", "multiple", "divis", "times"]},
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = PROJECT_ROOT / "data" / "eval_report.json"


def _contains_keyword(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    return any(kw in t for kw in keywords)


def run_eval() -> None:
    per_grade = defaultdict(lambda: {"hits": 0, "total": 0})
    grade_ok, grade_total = 0, 0
    failures = []

    for t in TEST_QUESTIONS:
        results = retrieve_with_metadata(t["q"], t["grade"])
        allowed = set(_grade_filter(t["grade"]))

        hit = any(_contains_keyword(r["text"], t["keywords"]) for r in results)
        per_grade[t["grade"]]["total"] += 1
        per_grade[t["grade"]]["hits"] += int(hit)

        for r in results:
            grade_total += 1
            grade_ok += int(r.get("grade") in allowed)

        if not hit:
            failures.append({
                "question": t["q"],
                "grade": t["grade"],
                "expected_keywords": t["keywords"],
                "got_texts": [r["text"][:100] for r in results],
            })

    print("\n===== RETRIEVAL EVAL REPORT (keyword-based) =====")
    overall_hits = sum(v["hits"] for v in per_grade.values())
    overall_total = sum(v["total"] for v in per_grade.values())
    for g in sorted(per_grade):
        v = per_grade[g]
        print(f"Class {g}: hit-rate {v['hits']}/{v['total']} "
              f"({100 * v['hits'] / v['total']:.0f}%)")
    print(f"\nOverall hit-rate:      {overall_hits}/{overall_total} "
          f"({100 * overall_hits / overall_total:.0f}%)")
    print(f"Grade-filter accuracy: {grade_ok}/{grade_total} "
          f"({100 * grade_ok / grade_total:.0f}%)  (must be 100%)")

    if failures:
        print(f"\n{len(failures)} weak retrievals — Day 7 to-do list:")
        for f_ in failures:
            print(f"\n  Class {f_['grade']} | Q: {f_['question']}")
            print(f"    expected any of: {f_['expected_keywords']}")
            for txt in f_["got_texts"]:
                print(f"    got: {txt}...")

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump({"per_grade": {str(k): v for k, v in per_grade.items()},
                   "overall_hit_rate": round(overall_hits / overall_total, 3),
                   "grade_filter_accuracy": round(grade_ok / grade_total, 3),
                   "failures": failures}, f, indent=2, ensure_ascii=False)
    print(f"\nFull report saved to {REPORT_PATH}")


if __name__ == "__main__":
    run_eval()