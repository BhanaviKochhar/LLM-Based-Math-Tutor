"""scripts/llm/verifier.py — independent maths engine for the tutor.

Jobs (compute/check unchanged in spirit; solve() drives the compute-first path):

  compute(question)  -> ground-truth Computation for a *computable* question.
  solve(question, grade)
                     -> (answer_str_or_None, is_math_bool) for the injection gate:
                          (str,  True)  -> inject this trusted answer
                          (None, True)  -> computable but NOT injected because the
                                           exact value isn't the taught form (bare
                                           non-exact division is taught as
                                           quotient+remainder). Skip strict verify.
                          (None, False) -> conceptual; not a computation.
  check(question, model_output, computed_value=None)
                     -> post-generation consistency gate.

Tier A hardening (from live testing):
  * max_tokens raised so reasoning tokens can't truncate the expression
    (we saw "45 /" at 24 tokens; "45 / 8" at 256).
  * Extractor output is SCANNED for an expression, not assumed to be one.
  * One retry on empty extractor result rides through brief 429s.
  * Injection is grade-appropriate: we don't inject a form that fights NCERT.

Safety unchanged: we NEVER eval model prose. Every candidate expression is
validated against an allow-list before sympy sees it.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

import sympy

from . import response_parser

# Only digits, the four operators, exponent, parens, decimal point, spaces.
_SAFE_EXPR = re.compile(r"^[0-9+\-*/.()\s]+$")
# A run that could be an arithmetic expression, for scanning noisier output.
_EXPR_RUN = re.compile(r"[0-9][0-9+\-*/.()\s]*[0-9)]")
# A bare "int / int" (taught as quotient+remainder at primary level).
_PLAIN_DIV = re.compile(r"^\s*\d+\s*/\s*\d+\s*$")

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

# Room for the reasoning model's hidden thinking tokens so the visible
# expression isn't truncated. 24 was too small on gpt-oss-120b.
_EXTRACT_MAX_TOKENS = 256


@dataclass
class Computation:
    verifiable: bool
    expression: str | None = None
    value: object | None = None


def _safe_eval(expr_str: str | None):
    """Evaluate a plain arithmetic string with sympy, or None if unsafe/non-numeric."""
    if not expr_str:
        return None
    expr_str = expr_str.strip()
    if not _SAFE_EXPR.match(expr_str):
        return None
    try:
        val = sympy.sympify(expr_str, rational=True)
    except Exception:
        return None
    if getattr(val, "free_symbols", set()):
        return None
    if not getattr(val, "is_number", False):
        return None
    return val


def _default_extractor(question: str, retries: int = 1) -> str:
    """Ask the shared LLM client for a single arithmetic expression.

    Retries once on an empty result so a brief 429 doesn't silently disable
    injection (empty return was the live failure mode under rate limits).
    """
    from . import llm_client  # lazy: keeps verifier import-safe offline

    messages = [{"role": "system", "content": _EXTRACT_SYSTEM}]
    for q, a in _EXTRACT_FEWSHOT:
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": a})
    messages.append({"role": "user", "content": question})

    text = ""
    for attempt in range(retries + 1):
        result = llm_client.chat(
            messages,
            params={"temperature": 0.0, "max_tokens": _EXTRACT_MAX_TOKENS, "top_p": 1.0},
        )
        text = (result.get("text") or "").strip()
        if text:
            break
        if attempt < retries:
            time.sleep(1.5)
    return text


def _expression_candidates(raw: str):
    """Yield plausible expression strings from noisy output, best first."""
    seen = set()

    def _clean(s):
        s = (s or "").strip().rstrip("=.").strip()
        if s and s not in seen:
            seen.add(s)
            return s
        return None

    c = _clean(raw)
    if c:
        yield c
    for line in raw.splitlines():
        c = _clean(line)
        if c:
            yield c
    for m in _EXPR_RUN.findall(raw):
        c = _clean(m)
        if c:
            yield c


def compute(question: str, extract_fn=None) -> Computation:
    """Ground-truth Computation for `question`, robust to noisy extractor output."""
    extract_fn = extract_fn or _default_extractor
    raw = (extract_fn(question) or "").strip()
    if not raw:
        return Computation(verifiable=False)
    if re.search(r"\bNONE\b", raw, re.IGNORECASE):
        return Computation(verifiable=False)
    for cand in _expression_candidates(raw):
        val = _safe_eval(cand)
        if val is not None:
            return Computation(verifiable=True, expression=cand, value=val)
    return Computation(verifiable=False, expression=raw)


def format_value(val) -> str:
    """Render a sympy number as a clean, child-facing string for injection."""
    try:
        if val == int(val):
            return str(int(val))
    except (TypeError, ValueError):
        pass
    if isinstance(val, sympy.Rational) and val.q != 1:
        return f"{val.p}/{val.q}"
    try:
        d = float(val)
        return f"{d:.4f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(val)


def _grade_appropriate_answer(expression: str | None, value) -> str | None:
    """Injectable answer string, or None if the exact value isn't the taught form.

      * Integer result -> inject (unambiguous at every primary grade).
      * Bare "int / int" that isn't exact -> DON'T inject (taught as quotient +
        remainder, not an improper fraction/decimal). Let the tutor teach
        remainders; skip strict verify.
      * Any other non-integer (real fraction arithmetic like 1/2 + 1/4) ->
        inject the exact value; that IS the taught answer.
    """
    try:
        if value == int(value):
            return format_value(value)
    except (TypeError, ValueError):
        pass
    if expression and _PLAIN_DIV.match(expression):
        return None
    return format_value(value)


def solve(question: str, grade: int | None = None, extract_fn=None):
    """Compute-first + injection gate.

    Returns (answer_or_None, is_math):
        (str,  True)  -> inject this trusted answer
        (None, True)  -> computable but not injected (remainder framing)
        (None, False) -> conceptual, not a computation
    grade is accepted for future grade-aware framing (Tier B); current rule is
    grade-independent.
    """
    comp = compute(question, extract_fn=extract_fn)
    if not comp.verifiable or comp.value is None:
        return None, False
    answer = _grade_appropriate_answer(comp.expression, comp.value)
    return answer, True


def _close(a, b, tol: float = 1e-6) -> bool:
    try:
        if sympy.simplify(a - b) == 0:
            return True
    except Exception:
        pass
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def check(question: str, model_output: str, extract_fn=None,
          computed_value=None) -> dict:
    """Compare a stated answer to an independent computation."""
    if response_parser.is_refusal(model_output or ""):
        return _result(False, None, None, None, "model refused; nothing to verify")

    if computed_value is not None:
        truth = computed_value
    else:
        comp = compute(question, extract_fn=extract_fn)
        if not comp.verifiable:
            return _result(False, None, None, None, "not a computable question")
        truth = comp.value

    num_str = response_parser.final_number_str(model_output or "")
    model_val = _safe_eval(num_str) if num_str else None
    if model_val is None:
        return _result(True, None, str(truth), None,
                       "couldn't read a number from the answer")

    match = _close(truth, model_val)
    note = "answer matches the computation" if match else "answer disagrees with the computation"
    return _result(True, bool(match), str(truth), str(model_val), note)


def _result(verifiable, match, computed, model_value, note) -> dict:
    return {
        "verifiable": verifiable,
        "match": match,
        "computed": computed,
        "model_value": model_value,
        "note": note,
    }