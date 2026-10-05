"""scripts/llm/topics.py — canonical NCERT topic classification.

Deterministic, keyword-based (no LLM call, no retrieval dependency -- the
corpus chunks themselves carry no `topic` field, only {text, grade, page,
source}, so this is the only source of topic signal currently available).

Maps a question/problem string to one of a small, fixed set of canonical
topic names grounded in docs/verified_ncert_class_1_5_topics.md, or None
when nothing matches confidently. Callers should treat None as "don't
know" and bucket it honestly (e.g. "Other"), never guess.

Deliberately a FLAT, grade-independent taxonomy rather than copying the
reference doc's per-grade topic names verbatim (which differ slightly in
wording per grade, e.g. "Addition & Subtraction (1 to 9)" vs "... with
Regrouping") -- the coarser, stable set below is what a keyword matcher can
actually classify reliably, and is still directly traceable to that doc's
topics. This trades fine-grained precision for a representation that is
genuinely canonical (the same topic string every time), which is the
specific problem being fixed: previously `weak_topics` stored the raw,
30-char-truncated question text, so "how do I add 56 and 27" and "56 + 27
explain" produced two different, unaggregatable keys for the same topic.
"""
from __future__ import annotations

import re

CANONICAL_TOPICS = (
    "Numbers & Counting", "Addition & Subtraction", "Multiplication", "Division",
    "Fractions & Decimals", "Factors & Multiples", "Shapes & Geometry",
    "Symmetry & Angles", "Measurement", "Perimeter, Area & Volume",
    "Time & Calendar", "Money", "Patterns", "Data Handling",
)

# Checked top-to-bottom, first match wins -- more specific topics (fractions,
# factors, perimeter/area) are listed before the generic arithmetic-operator
# keywords they could otherwise be mistaken for (e.g. "half" before a bare
# "+"/"add" check, so "what is half of 8" doesn't fall through to Addition).
_KEYWORD_TOPICS: tuple[tuple[str, str], ...] = (
    (r"fraction|numerator|denominator|\bhalf\b|\bquarter\b|\bthird\b", "Fractions & Decimals"),
    (r"decimal|tenths|hundredths", "Fractions & Decimals"),
    (r"\bperimeter\b", "Perimeter, Area & Volume"),
    (r"\barea\b|\bvolume\b", "Perimeter, Area & Volume"),
    (r"\bfactor|\bmultiples?\b|\blcm\b|\bhcf\b|\bprime\b|\bcomposite\b", "Factors & Multiples"),
    (r"\bangle|\bdegree|\bprotractor", "Symmetry & Angles"),
    (r"symmetr|\brotat", "Symmetry & Angles"),
    (r"\btriangle|\bcircle|\bsquare\b|\brectangle|\bcube\b|\bcylinder|\bshape", "Shapes & Geometry"),
    (r"\bdivide|\bdivision|\bdiv\b|÷|\d\s*/\s*\d", "Division"),
    (r"\bmultipl|\btimes\b|×|table of \d|\d\s*x\s*\d|\d\s*\*\s*\d", "Multiplication"),
    (r"\bsubtract|\bminus\b|take away|\d\s*-\s*\d", "Addition & Subtraction"),
    (r"\badd|\bplus\b|\bsum\b|\d\s*\+\s*\d", "Addition & Subtraction"),
    (r"\bmeasure|\blength\b|\bweight\b|\bcapacity\b|\bheavier\b|\blighter\b", "Measurement"),
    (r"\btime\b|\bclock\b|\bcalendar\b|\bhour\b|\bminute\b", "Time & Calendar"),
    (r"\bmoney\b|\brupee|₹", "Money"),
    (r"\bpattern\b", "Patterns"),
    (r"\bdata\b|\bgraph\b|\bchart\b|\btally\b|\bpictograph\b", "Data Handling"),
    (r"\bcount|\bnumber\b|\bplace value\b", "Numbers & Counting"),
)
_COMPILED = [(re.compile(p, re.IGNORECASE), t) for p, t in _KEYWORD_TOPICS]


def canonicalize(question: str) -> str | None:
    """Return one of CANONICAL_TOPICS, or None if nothing matched
    confidently. None means "don't know" -- callers must not invent a topic."""
    q = question or ""
    for pattern, topic in _COMPILED:
        if pattern.search(q):
            return topic
    return None
