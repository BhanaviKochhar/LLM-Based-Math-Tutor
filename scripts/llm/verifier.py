"""scripts/llm/verifier.py — independent maths check for the tutor's answer.

Two jobs:

  compute(question)  -> ground-truth value for a *computable* question.
                        An LLM turns the natural-language question into ONE
                        arithmetic expression; sympy evaluates it. Conceptual
                        or non-arithmetic questions yield verifiable=False.

  check(question, model_output)
                     -> compares the model's stated final answer against the
                        computed value and reports match / mismatch / n/a.

Design choices that keep this safe and honest:
  * We NEVER eval the model's prose. The expression comes from a constrained
    extractor and is validated against an allow-list before sympy sees it, so
    no functions, symbols, or names (sqrt, pi, __import__, ...) can slip in.
  * We only verify arithmetic that is *determined by the numbers in the
    question*. Factual recall ("minutes in an hour") returns NONE — we check
    computation, not the model's memory.
  * If we can't read a number from the model's answer, we say so (match=None)
    rather than guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import sympy

from . import response_parser

# Only digits, the four operators, exponent, parens, decimal point, spaces.
_SAFE_EXPR = re.compile(r"^[0-9+\-*/.()\s]+$")

# ---- the extractor prompt -------------------------------------------------

_EXTRACT_SYSTEM = (
    "You convert a primary-school (NCERT Class 1-5) maths question into ONE "
    "arithmetic expression a computer can evaluate.\n"
    "Rules:\n"
    "- Output ONLY the expression: digits and + - * / ** ( ) and decimals.\n"
    "- Write fractions as a/b (e.g. 1/2). No mixed numbers, no words, no "
    "units, no '=' sign, no explanation.\n"
    "- The expression must be fully determined by the numbers in the question.\n"
    "- If the question is conceptual, a definition, a comparison, factual "
    "recall, or not primary arithmetic, output exactly: NONE"
)

_EXTRACT_FEWSHOT = [
    ("What is 2 + 3?", "2 + 3"),
    ("I have 8 balloons and 3 fly away. How many are left?", "8 - 3"),
    ("What is 7 times 8?", "7 * 8"),
    ("How can I share 12 toffees equally among 4 friends?", "12 / 4"),
    ("What is 1/2 of 8?", "(1/2) * 8"),
    ("What is the perimeter of a square with side 5 cm?", "4 * 5"),
    ("What is the area of a rectangle 4 cm by 7 cm?", "4 * 7"),
    ("What is 1/2 + 1/4?", "1/2 + 1/4"),
    ("What comes after 49?", "49 + 1"),
    ("What is a fraction?", "NONE"),
    ("How many minutes are in one hour?", "NONE"),
    ("Which is bigger, 6 or 9?", "NONE"),
    ("Explain algebra to me", "NONE"),
]


@dataclass
class Computation:
    verifiable: bool
    expression: str | None = None
    value: object | None = None  # a sympy number when verifiable


def _safe_eval(expr_str: str | None):
    """Evaluate a plain arithmetic string with sympy, or return None if it's
    unsafe, non-numeric, or unparseable."""
    if not expr_str:
        return None
    expr_str = expr_str.strip()
    if not _SAFE_EXPR.match(expr_str):
        return None
    try:
        val = sympy.sympify(expr_str, rational=True)
    except Exception:
        return None
    # Reject anything that isn't a pure number (symbols, unresolved funcs).
    if getattr(val, "free_symbols", set()):
        return None
    if not val.is_number:
        return None
    return val


def _default_extractor(question: str) -> str:
    """Ask the shared LLM client for a single arithmetic expression."""
    from . import llm_client  # lazy: keeps verifier import-safe offline

    messages = [{"role": "system", "content": _EXTRACT_SYSTEM}]
    for q, a in _EXTRACT_FEWSHOT:
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": a})
    messages.append({"role": "user", "content": question})

    result = llm_client.chat(
        messages, params={"temperature": 0.0, "max_tokens": 24, "top_p": 1.0}
    )
    return (result.get("text") or "").strip()


def compute(question: str, extract_fn=None) -> Computation:
    """Return the ground-truth Computation for `question`.

    `extract_fn` is injectable for testing (default calls the LLM).
    """
    extract_fn = extract_fn or _default_extractor
    raw = (extract_fn(question) or "").strip()
    # Take the first line/token the model gave, be lenient about stray text.
    first = raw.splitlines()[0].strip() if raw else ""
    if not first or first.upper().startswith("NONE"):
        return Computation(verifiable=False)
    val = _safe_eval(first)
    if val is None:
        return Computation(verifiable=False, expression=first)
    return Computation(verifiable=True, expression=first, value=val)


def _close(a, b, tol: float = 1e-6) -> bool:
    """Exact equality for rationals, else float comparison within tol."""
    try:
        if sympy.simplify(a - b) == 0:
            return True
    except Exception:
        pass
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def check(question: str, model_output: str, extract_fn=None) -> dict:
    """Compare the model's stated answer to an independent computation.

    Returns a dict:
        verifiable  – could we compute a ground truth for this question?
        match       – True / False, or None if undecidable (no number read,
                      or not verifiable)
        computed    – str(ground truth) or None
        model_value – str(number read from the model) or None
        note        – short human-readable explanation
    """
    # Refusals are never "wrong" — nothing to check.
    if response_parser.is_refusal(model_output or ""):
        return _result(False, None, None, None, "model refused; nothing to verify")

    comp = compute(question, extract_fn=extract_fn)
    if not comp.verifiable:
        return _result(False, None, None, None, "not a computable question")

    num_str = response_parser.final_number_str(model_output or "")
    model_val = _safe_eval(num_str) if num_str else None
    if model_val is None:
        return _result(
            True, None, str(comp.value), None,
            "couldn't read a number from the answer",
        )

    match = _close(comp.value, model_val)
    note = "answer matches the computation" if match else "answer disagrees with the computation"
    return _result(True, bool(match), str(comp.value), str(model_val), note)


def _result(verifiable, match, computed, model_value, note) -> dict:
    return {
        "verifiable": verifiable,
        "match": match,
        "computed": computed,
        "model_value": model_value,
        "note": note,
    }
