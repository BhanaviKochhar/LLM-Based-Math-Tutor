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
                     -> post-generation consistency gate against the
                        STUDENT'S problem's trusted answer (only the modes
                        that inject a computed_answer call this).
  check_self_consistency(text)
                     -> bounded guardrail for every OTHER mode (teach_invite,
                        redirect, hints, diagnose_wrong, ...): the model is
                        free to invent its own illustrative numbers there,
                        and nothing else checks whether ITS OWN arithmetic in
                        that example actually adds up.

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
    # Live-reported gap: place-value and unit-conversion word problems were
    # unreliably converted on the first pass (e.g. "1 ten and 4 ones" only
    # ever got computed indirectly, via a LATER reply's own graduation, not
    # from the child's original question) -- not a missing-function problem
    # like lcm/hcf below, just thin few-shot coverage of common NCERT
    # phrasings for the SAME plain-arithmetic extractor.
    ("What is 1 ten and 4 ones put together?", "10 + 4"),
    ("I have 2 tens and 3 ones. What number is that?", "20 + 3"),
    ("How many centimetres are in 3 metres?", "3 * 100"),
    ("Convert 5 rupees to paise.", "5 * 100"),
]

# Room for the reasoning model's hidden thinking tokens so the visible
# expression isn't truncated. 24 was too small on gpt-oss-120b.
_EXTRACT_MAX_TOKENS = 256

# Objective 2 gap, live-reported: a question with a single short, objectively
# checkable but NON-numeric answer (a day of the week, a shape name, a
# yes/no fact) was never computable by the arithmetic extractor above, so it
# had no trusted value to grade against at all -- a CORRECT answer to "if
# today is Monday, what day will it be after 3 days?" landed in the same
# ungraded path as a genuinely conceptual "what is a fraction?" question,
# and personalisation tracking (student_tracker.record, only called from a
# graded diagnose_correct/wrong outcome) never saw it either. This extends
# the SAME compute-first philosophy -- ground the trusted answer via a
# constrained extraction call, never trust the tutor's own free text -- to
# that second, non-numeric answer shape, rather than widening what counts
# as "numeric". It is a SEPARATE extractor, tried only once the numeric one
# above has already said NONE, so it can never compete with or weaken the
# existing numeric path.
_CATEGORICAL_EXTRACT_SYSTEM = (
    "You read a primary-school (NCERT Class 1-5) maths question and decide "
    "whether it has exactly ONE short, factual, objectively-checkable "
    "answer that is NOT computed by arithmetic -- a day of the week, a "
    "month, a shape name, a yes/no fact, which of two given things is "
    "bigger/smaller/equal, or similar.\n"
    "Rules:\n"
    "- Output ONLY the answer itself, in 1-4 words, the way an NCERT "
    "textbook would state it (e.g. 'Thursday', 'a square', 'yes', '9').\n"
    "- The answer must be FULLY DETERMINED by the question exactly as "
    "asked -- never guess or invent information the question didn't give.\n"
    "- If the question asks for an explanation, a definition, an opinion, "
    "a list of several things, or has no single short correct answer, "
    "output exactly: NONE\n"
    "- If the question is really an ARITHMETIC computation (addition, "
    "subtraction, multiplication, division, fractions...), output exactly: "
    "NONE -- that is handled separately.\n"
    "- A question asking the CHILD to self-report -- whether something "
    "makes sense to them, whether they understand, how they feel, what "
    "THEY think or want to do next -- is NOT a factual question, even if "
    "it is grammatically shaped like a yes/no question. There is no "
    "objectively correct answer to check that against. Output NONE."
)

_CATEGORICAL_EXTRACT_FEWSHOT = [
    ("If today is Monday, what day will it be after 3 days?", "Thursday"),
    ("What shape has 4 equal sides and 4 right angles?", "a square"),
    ("Is 7 an even number?", "no"),
    ("Which is bigger, 6 or 9?", "9"),
    ("What month comes right after June?", "July"),
    ("What is 2 + 3?", "NONE"),
    ("What is a fraction?", "NONE"),
    ("Name the months that have 31 days.", "NONE"),
    ("How do I find a common denominator?", "NONE"),
    ("Does that make sense so far?", "NONE"),
    ("Do you understand how to add fractions now?", "NONE"),
    ("Would you like to try a harder question next?", "NONE"),
]

# Objective 2 follow-up, live-reported: "What is the LCM of 4 and 6?" had NO
# trusted value to grade against on the first attempt -- not because the
# ANSWER is non-numeric (it's a plain integer), but because the numeric
# extractor's grammar (_SAFE_EXPR: digits and + - * / ( ) only) has no
# function-call support at all, so it can't express "lcm", "hcf", or any
# other named operation. A THIRD, separate extractor (same "never compete
# with the numeric path" discipline as the categorical one) recognises a
# small, explicit allow-list of named functions and routes each to the
# corresponding SymPy/Python call -- SAME safety posture as the operator
# allow-list: never a generic eval of an arbitrary function name, only
# ever one of the fixed, reviewed callables below, with validated arity
# and numeric-only arguments (each argument is itself run through
# _safe_eval, so "lcm(4+2, 6)" is fine but "lcm(evil_code(), 6)" can never
# reach a real function call at all).
def _hcf(a, b) -> int:
    return int(sympy.gcd(int(a), int(b)))


def _lcm(a, b) -> int:
    return int(sympy.lcm(int(a), int(b)))


def _is_prime(n) -> str:
    return "yes" if sympy.isprime(int(n)) else "no"


def _factors_of(n) -> list[int]:
    return sorted(int(d) for d in sympy.divisors(int(n)))


def _angle_type(degrees) -> str:
    d = float(degrees) % 360
    if d == 90:
        return "right angle"
    if d < 90:
        return "acute angle"
    if d < 180:
        return "obtuse angle"
    if d == 180:
        return "straight angle"
    return "reflex angle"


def _time_add(hour, minute, delta_minutes) -> str:
    total = (int(hour) % 24) * 60 + int(minute) + int(delta_minutes)
    total %= 24 * 60
    return f"{total // 60}:{total % 60:02d}"


# name -> (callable, arity, answer_type for the result)
_FUNCTION_REGISTRY: dict[str, tuple] = {
    "lcm": (_lcm, 2, "numeric"),
    "hcf": (_hcf, 2, "numeric"),
    "gcd": (_hcf, 2, "numeric"),
    "is_prime": (_is_prime, 1, "categorical"),
    "factors": (_factors_of, 1, "list"),
    "angle_type": (_angle_type, 1, "categorical"),
    "time_add": (_time_add, 3, "time"),
}

_FUNCTION_EXTRACT_SYSTEM = (
    "You convert a primary-school (NCERT Class 1-5) maths question into ONE "
    "function call, from this EXACT list, a computer can evaluate:\n"
    "- lcm(a, b) -- the Lowest/Least Common Multiple of a and b\n"
    "- hcf(a, b) -- the Highest Common Factor of a and b (also called GCD)\n"
    "- is_prime(n) -- whether n is a prime number\n"
    "- factors(n) -- the list of all factors of n\n"
    "- angle_type(d) -- the type of angle for d degrees (acute/right/"
    "obtuse/straight/reflex)\n"
    "- time_add(h, m, delta_minutes) -- the clock time delta_minutes after "
    "h:m, 24-hour clock (h is 0-23)\n"
    "Rules:\n"
    "- Output ONLY the function call, exactly as shown above, with numbers "
    "filled in from the question. No explanation, no '=' sign.\n"
    "- If the question does not match one of these EXACTLY, output exactly: "
    "NONE -- including ordinary arithmetic (addition, subtraction, "
    "multiplication, division, fractions), which is handled elsewhere."
)

_FUNCTION_EXTRACT_FEWSHOT = [
    ("What is the LCM of 4 and 6?", "lcm(4, 6)"),
    ("Find the HCF of 12 and 18.", "hcf(12, 18)"),
    ("What is the lowest common multiple of 3 and 5?", "lcm(3, 5)"),
    ("Is 7 a prime number?", "is_prime(7)"),
    ("Is 15 a composite number?", "is_prime(15)"),
    ("What are the factors of 12?", "factors(12)"),
    ("List the factors of 18.", "factors(18)"),
    ("What type of angle is 120 degrees?", "angle_type(120)"),
    ("If it is 3:30 now, what time will it be in 45 minutes?", "time_add(3, 30, 45)"),
    ("What is 2 + 3?", "NONE"),
    ("What is a fraction?", "NONE"),
    ("What is 7 times 8?", "NONE"),
]

# A bare "name(args)" call shape -- no nesting, so a stray "(" inside an
# argument can't be mistaken for a second call.
_FUNCTION_CALL_RE = re.compile(r"^\s*([a-z_]+)\s*\(\s*(.*?)\s*\)\s*$", re.IGNORECASE)


@dataclass
class Computation:
    verifiable: bool
    expression: str | None = None
    value: object | None = None
    answer_type: str = "numeric"  # or "categorical" -- see compute_categorical


def _safe_eval(expr_str: str | None):
    """Evaluate a plain arithmetic string with sympy, or None if unsafe/non-numeric.

    Division by zero is rejected here, not just in the bare-"int/int" shape
    _grade_appropriate_answer special-cases. sympy evaluates e.g. "5/0+3" or
    "8/(3-3)" to `zoo` (ComplexInfinity) or "0/0"-shaped expressions to `nan`
    rather than raising -- and `zoo`/`nan` both satisfy sympy's `is_number`,
    so without this check one could flow all the way through solve() and be
    formatted as a literal "zoo"/"nan" string injected into the tutor prompt
    as a "trusted" answer. Real numbers (int/Rational) always have
    `is_real is True`; zoo/nan/+-oo do not.
    """
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
    if val.is_real is not True:
        return None
    return val


def parse_trusted_value(value_str: str | None):
    """Public entry point for callers outside this package (e.g. the
    frontend) that already hold an already-trusted answer string — such as
    a controller TutorState.computed_answer — and need it as a comparable
    value. Equivalent to _safe_eval, which stays the internal name used by
    verifier.py/controller.py/tests within this package."""
    return _safe_eval(value_str)


def _extract_via_llm(system: str, fewshot: list[tuple[str, str]], question: str,
                     retries: int = 1) -> str:
    """Shared call shape for both extractors below: a constrained, few-shot,
    temperature-0 classification call. Retries once on an empty result so a
    brief 429 doesn't silently disable injection (empty return was the live
    failure mode under rate limits)."""
    from . import llm_client  # lazy: keeps verifier import-safe offline

    messages = [{"role": "system", "content": system}]
    for q, a in fewshot:
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


def _default_extractor(question: str, retries: int = 1) -> str:
    """Ask the shared LLM client for a single arithmetic expression."""
    return _extract_via_llm(_EXTRACT_SYSTEM, _EXTRACT_FEWSHOT, question, retries)


def _default_categorical_extractor(question: str, retries: int = 1) -> str:
    """Ask the shared LLM client for a short non-numeric trusted answer
    (see Computation.answer_type / compute_categorical)."""
    return _extract_via_llm(_CATEGORICAL_EXTRACT_SYSTEM, _CATEGORICAL_EXTRACT_FEWSHOT,
                            question, retries)


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


def compute_categorical(question: str, extract_fn=None) -> Computation:
    """Ground-truth Computation for a question whose answer is a short,
    objectively-checkable fact that ISN'T arithmetic (see
    _CATEGORICAL_EXTRACT_SYSTEM) -- the non-numeric counterpart to
    compute(). Only ever consulted by solve_with_type() AFTER the numeric
    path has already said NONE, so it can never compete with a genuine
    computation."""
    extract_fn = extract_fn or _default_categorical_extractor
    raw = (extract_fn(question) or "").strip()
    if not raw or re.search(r"\bNONE\b", raw, re.IGNORECASE):
        return Computation(verifiable=False)
    return Computation(verifiable=True, value=raw, answer_type="categorical")


def _default_function_extractor(question: str, retries: int = 1) -> str:
    return _extract_via_llm(_FUNCTION_EXTRACT_SYSTEM, _FUNCTION_EXTRACT_FEWSHOT,
                            question, retries)


def _parse_function_call(raw: str):
    """Parse "name(arg1, arg2, ...)" into (result, answer_type), or None if
    the shape, the name, the arity, or any individual argument doesn't
    check out. Every argument is independently run through _safe_eval, so
    only plain numeric sub-expressions can ever reach a real function
    call -- never an arbitrary string."""
    m = _FUNCTION_CALL_RE.match(raw)
    if not m:
        return None
    name = m.group(1).lower()
    if name not in _FUNCTION_REGISTRY:
        return None
    args_str = m.group(2).strip()
    args = [a.strip() for a in args_str.split(",")] if args_str else []
    fn, arity, answer_type = _FUNCTION_REGISTRY[name]
    if len(args) != arity:
        return None
    values = []
    for a in args:
        v = _safe_eval(a)
        if v is None:
            return None
        values.append(v)
    try:
        result = fn(*values)
    except Exception:
        return None
    return result, answer_type


def compute_function(question: str, extract_fn=None) -> Computation:
    """Ground-truth Computation for a question that names one of a small,
    fixed set of NCERT-1-5 operations (LCM/HCF/prime/factors/angle-type/
    clock-time-add) that the plain-arithmetic extractor's grammar can't
    express at all (see _FUNCTION_REGISTRY). Only ever consulted by
    solve_with_type() AFTER the numeric path has already said NONE, so it
    can never compete with a genuine arithmetic computation."""
    extract_fn = extract_fn or _default_function_extractor
    raw = (extract_fn(question) or "").strip()
    if not raw or re.search(r"\bNONE\b", raw, re.IGNORECASE):
        return Computation(verifiable=False)
    parsed = _parse_function_call(raw)
    if parsed is None:
        return Computation(verifiable=False, expression=raw)
    result, answer_type = parsed
    if answer_type == "list":
        value_str = ", ".join(str(x) for x in result)
    else:
        value_str = str(result)
    return Computation(verifiable=True, expression=raw, value=value_str, answer_type=answer_type)


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


def _strip_enclosing_parens(expression: str) -> str:
    """Strip one or more layers of parentheses that wrap the WHOLE
    expression (e.g. "(20/3)" -> "20/3", "((20/3))" -> "20/3"), so the
    "bare int/int" shape below is recognised regardless of whether the
    extractor happened to wrap it defensively. Parens that don't span the
    entire expression (e.g. "(1/2)*8") are left untouched."""
    s = expression.strip()
    while len(s) >= 2 and s[0] == "(" and s[-1] == ")":
        depth = 0
        spans_whole = True
        for i, ch in enumerate(s):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(s) - 1:
                    spans_whole = False
                    break
        if not spans_whole:
            break
        s = s[1:-1].strip()
    return s


# A bare "int/int" expression is genuinely ambiguous on its own: "3/10" could
# be a non-exact division word problem (taught as quotient+remainder, so the
# improper fraction/decimal must be withheld) or a fraction VALUE the
# question is directly about -- "What is 3/10 written as a decimal?",
# "Convert 7/20 to a decimal", "What fraction of the bottle caps did you
# colour?" -- where withholding makes no sense because the fraction value
# (not a quotient+remainder) IS the question, not a side effect of sharing/
# dividing a quantity. The expression shape alone cannot distinguish these
# (component-evaluation found this producing real mismatches on
# ar-020/cb-158); the question's own wording can, in the common cases --
# including the "what/which fraction...?" phrasing that is itself the
# standard way NCERT poses a part-of-a-whole exercise.
_FRACTION_CONVERSION_RE = re.compile(
    r"\bdecimal\b|\bas a fraction\b|\bwrite.{0,15}fraction\b|"
    r"\bequivalent fraction\b|\bsimplify\b|\breduce.{0,15}fraction\b|"
    r"\bconvert\b|\bwhat fraction\b|\bwhich fraction\b",
    re.IGNORECASE,
)


def _looks_like_fraction_conversion(question: str | None) -> bool:
    return bool(question) and _FRACTION_CONVERSION_RE.search(question) is not None


def _grade_appropriate_answer(expression: str | None, value,
                              question: str | None = None) -> str | None:
    """Injectable answer string, or None if the exact value isn't the taught form.

      * Integer result -> inject (unambiguous at every primary grade).
      * Bare "int / int" that isn't exact -> DON'T inject (taught as quotient +
        remainder, not an improper fraction/decimal), UNLESS the original
        question's own wording signals a fraction/decimal-conversion intent
        (see _FRACTION_CONVERSION_RE), in which case the fraction value IS
        the taught answer and withholding it would be wrong. Recognised
        whether or not the expression is wrapped in redundant enclosing
        parens, e.g. "(20/3)".
      * Any other non-integer (real fraction arithmetic like 1/2 + 1/4) ->
        inject the exact value; that IS the taught answer.

    `question` is optional and defaults to None (preserving the prior
    division-withholding behaviour) for any caller that doesn't have the
    original question text on hand -- only solve() currently passes it.
    """
    try:
        if value == int(value):
            return format_value(value)
    except (TypeError, ValueError):
        pass
    is_bare_division = bool(expression) and _PLAIN_DIV.match(_strip_enclosing_parens(expression))
    if is_bare_division and not _looks_like_fraction_conversion(question):
        return None
    return format_value(value)


def _quotient_remainder(expression: str | None):
    """When _grade_appropriate_answer withholds a bare non-exact "int/int"
    division (taught as quotient+remainder, not a fraction/decimal -- see
    its own docstring), the quotient and remainder are themselves trivially
    computable and gradable; there's no reason to leave the question fully
    ungraded just because the improper-fraction VALUE isn't the taught
    form. Returns (quotient, remainder), or None if `expression` isn't a
    bare int/int division (or divides by zero)."""
    if not expression:
        return None
    stripped = _strip_enclosing_parens(expression)
    if not _PLAIN_DIV.match(stripped):
        return None
    a_str, b_str = stripped.split("/", 1)
    try:
        a, b = int(a_str.strip()), int(b_str.strip())
    except ValueError:
        return None
    if b == 0:
        return None
    return a // b, a % b


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
    answer = _grade_appropriate_answer(comp.expression, comp.value, question=question)
    return answer, True


_CLOCK_TARGET_RE = re.compile(r"\bwhat\s+time\b|\bclock\s+(?:will\s+)?shows?\b|\b24[\s-]hour\b",
                              re.IGNORECASE)


def asks_for_clock_time(question: str | None) -> bool:
    """True when the answer the question wants is a clock time ("what time
    will it be", "what will the clock show"), as opposed to a duration
    ("how long", "how many minutes"), which plain arithmetic answers fine."""
    return bool(_CLOCK_TARGET_RE.search(question or ""))


def solve_with_type(question: str, grade: int | None = None, extract_fn=None,
                    categorical_extract_fn=None, function_extract_fn=None):
    """Like solve(), but for the controller's actual grading path: tries,
    in order, plain arithmetic, the quotient+remainder fallback for a
    withheld non-exact division, the small named-function registry (LCM/
    HCF/prime/factors/angle-type/clock-time-add), and finally the general
    categorical extractor -- before giving up. Only this entry point grows
    a third return value -- solve() itself, and every existing caller of it
    (controller.py's own-example self-check, the eval harnesses, the legacy
    Tier A path), stay numeric-only and untouched; grading the STUDENT's
    actual problem is the one place the extra extraction calls are worth
    it.

    Returns (answer_or_None, is_math, answer_type):
        (str,  True,  "numeric")           -> inject this computed trusted answer
        (str,  True,  "quotient_remainder")-> inject this "q remainder r" trusted answer
        (str,  True,  "categorical")       -> inject this short factual answer
        (str,  True,  "list")              -> inject this comma-separated set (e.g. factors)
        (str,  True,  "time")              -> inject this "H:MM" clock trusted answer
        (None, True,  "numeric")           -> computable but not injected (remainder framing,
                                               and the question's own wording didn't signal a
                                               fraction/decimal intent, AND no clean q/r pair)
        (None, False, "numeric")           -> neither arithmetic nor a checkable short fact
    """
    if asks_for_clock_time(question):
        # A what-time question goes to time_add FIRST. The arithmetic
        # extractor happily turns "8:20 plus 50 minutes" into minutes after
        # midnight (8*60+20+50 = 550), which then got injected as the
        # trusted answer -- "Answer: 550" for 9:10 on 5 of 19 clock items in
        # the paper-eval v1 run, with the post-check reporting a match.
        # If time_add can't express it, inject nothing rather than a count
        # of minutes.
        func = compute_function(question, extract_fn=function_extract_fn)
        if func.verifiable and func.value is not None and func.answer_type == "time":
            return str(func.value), True, "time"
        return None, True, "numeric"

    comp = compute(question, extract_fn=extract_fn)
    if comp.verifiable and comp.value is not None:
        answer = _grade_appropriate_answer(comp.expression, comp.value, question=question)
        if answer is not None:
            return answer, True, "numeric"
        qr = _quotient_remainder(comp.expression)
        if qr is not None:
            quotient, remainder = qr
            return f"{quotient} remainder {remainder}", True, "quotient_remainder"
        return None, True, "numeric"

    func = compute_function(question, extract_fn=function_extract_fn)
    if func.verifiable and func.value is not None:
        return str(func.value), True, func.answer_type

    cat = compute_categorical(question, extract_fn=categorical_extract_fn)
    if cat.verifiable and cat.value:
        return str(cat.value), True, "categorical"
    return None, False, "numeric"


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


# Bounded guardrail for numbers the model invents ITSELF outside the
# student's own problem -- e.g. a worked example with made-up numbers in a
# broad teach_invite/redirect reply, or a demonstration inside a hint. The
# main compute-first/inject path only ever checks the student's problem; it
# has no opinion on a self-chosen example the model picks to illustrate a
# method. This does not re-derive what the "right" example should be (that
# would need a new extraction mechanism); it only checks that whatever
# equation the model DID write down is internally consistent, independent of
# which mode produced it. Deliberately conservative: a statement this regex
# can't confidently parse is skipped, not flagged, so noisy prose/text with
# words between the numbers never produces a false alarm.
_SELF_CONSISTENCY_EQ_RE = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?(?:\s*[+\-*/]\s*\d+(?:\.\d+)?)+)\s*=\s*"
    # The fraction alternative is listed BEFORE the bare-number one: regex
    # alternation tries left-to-right and stops at the first match, so with
    # the bare-number form first, "2/4" on the right of "=" was matching only
    # "2" and silently discarding "/4" -- the RHS of "1/2 = 2/4" was read as
    # "2", producing a false mismatch against the correctly-evaluated "1/2"
    # LHS. The more specific (longer) form must be tried first.
    r"([-+]?\d+\s*/\s*\d+|[-+]?\d+(?:\.\d+)?)"
)


def check_self_consistency(text: str) -> list[dict]:
    """Scan free text for explicit "A op B = C" arithmetic statements the
    model wrote itself and verify each one independently with sympy.

    Returns a list of mismatches (empty if every stated equation checks out,
    or none were found) — each item: {"statement", "computed", "stated"}.
    Never raises; an unparsable operand is skipped, not reported.
    """
    mismatches = []
    for m in _SELF_CONSISTENCY_EQ_RE.finditer(text or ""):
        lhs_str, rhs_str = m.group(1), m.group(2)
        lhs_val = _safe_eval(lhs_str)
        rhs_val = _safe_eval(re.sub(r"\s+", "", rhs_str))
        if lhs_val is None or rhs_val is None:
            continue
        if not _close(lhs_val, rhs_val):
            mismatches.append({
                "statement": f"{lhs_str.strip()} = {rhs_str.strip()}",
                "computed": str(lhs_val),
                "stated": str(rhs_val),
            })
    return mismatches


def _result(verifiable, match, computed, model_value, note) -> dict:
    return {
        "verifiable": verifiable,
        "match": match,
        "computed": computed,
        "model_value": model_value,
        "note": note,
    }