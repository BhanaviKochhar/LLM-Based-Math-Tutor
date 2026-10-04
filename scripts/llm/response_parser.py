"""scripts/llm/response_parser.py — read structured bits out of model text.

The tutor prompts (v1..v5) all end the answer with a line like

    Answer: 42

so the sanity checker can find the model's final value reliably. This module
locates that value and extracts a clean numeric token (integer, decimal, or
fraction) from free text. It does no maths — turning a token into a value and
comparing lives in verifier.py.

final_number_str()'s fallback (no "Answer:" line found) used to scan the
WHOLE text and take the FIRST number -- which, in a multi-sentence
explanation, is very often an early input number rather than the stated
result (e.g. "We have 3 groups, and each group has 4 apples... = 12" used to
return "3"). A naive "take the LAST number instead" fix is also wrong for
this tutor specifically: several prompt directives (see
scripts/llm/controller.py _d_diagnose_correct, _d_reveal) instruct the model
to append a follow-up suggestion AFTER the answer ("Would you like to try
8 x 7 next?"), so the last number in the text is often that suggestion, not
the answer. final_number_str() now uses a confidence-tiered fallback instead
of guessing between first/last -- see its docstring.
"""
from __future__ import annotations

import re

# The refusal sentinel shared by every prompt version.
REFUSAL_MARKER = "ask your teacher"

# "Answer:" possibly bold/starred, capturing the rest of that line.
_ANSWER_RE = re.compile(r"(?im)^\s*\**\s*answer\s*\**\s*[:\-]\s*\**\s*(.+?)\s*$")

# A number: optional sign, then a mixed number (1 1/2), a comma-grouped
# integer (1,234 / Indian 1,00,000), a fraction a/b, or a decimal/integer.
# Order matters -- each more specific shape must be tried before a shape it
# contains, or part of it is silently dropped: "1 1/2" read as just "1/2"
# loses the whole part, and "1,234" read as just "1" loses everything after
# the first comma. Both are realistic model outputs here (grade 4-5 fraction
# results over 1, and grade 4-5 "numbers up to 100,000" content) and would
# otherwise cause a correct stated answer to be verified against the wrong
# value.
_MIXED_NUMBER_RE = re.compile(r"[-+]?\d+\s+\d+\s*/\s*\d+")
_COMMA_GROUPED_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{2,3})+")
_NUMBER_TOKEN = (
    r"[-+]?\d+\s+\d+\s*/\s*\d+"
    r"|[-+]?\d{1,3}(?:,\d{2,3})+"
    r"|[-+]?\d+\s*/\s*\d+"
    r"|[-+]?\d*\.\d+"
    r"|[-+]?\d+"
)
_FRACTION_RE = re.compile(r"[-+]?\d+\s*/\s*\d+")
_DECIMAL_RE = re.compile(r"[-+]?\d*\.\d+|[-+]?\d+")
_NUMBER_TOKEN_RE = re.compile(_NUMBER_TOKEN)
_MIXED_NUMBER_PARTS_RE = re.compile(r"^([-+]?)(\d+)\s+(\d+)\s*/\s*(\d+)$")


def _normalize_token(raw: str) -> str:
    """Collapse one matched numeric token into a sympy-evaluable string.

    A plain fraction/decimal/integer only needs internal whitespace removed
    (e.g. "3 / 4" -> "3/4", the pre-existing behaviour). A MIXED NUMBER like
    "1 1/2" needs its whole and fractional parts combined into one improper
    fraction ("3/2") -- naively stripping whitespace would instead
    concatenate the digits into "11/2", a different and wrong value. A
    COMMA-GROUPED integer like "1,234" or the Indian "1,00,000" just needs
    its commas removed.
    """
    s = re.sub(r"\s+", " ", raw.strip())
    mixed = _MIXED_NUMBER_PARTS_RE.match(s)
    if mixed:
        sign, whole, num, den = mixed.groups()
        improper = int(whole) * int(den) + int(num)
        return f"{sign}{improper}/{den}"
    return re.sub(r"\s+", "", s).replace(",", "")

# A stated computed result: "<work> = <value>" or "<work> equals <value>".
# Deliberately requires "=" / "equals" immediately before the number, so a
# trailing suggestion like "like 8 x 7" (no "=") is never mistaken for one.
_EQUATION_RESULT_RE = re.compile(r"(?:=|\bequals\b)\s*(" + _NUMBER_TOKEN + r")",
                                 re.IGNORECASE)


def is_refusal(text: str) -> bool:
    return REFUSAL_MARKER in (text or "").lower()


def extract_answer(text: str) -> str | None:
    """Return the content of the LAST 'Answer:' line, or None.

    Last match wins because models sometimes echo an example 'Answer:' line
    before stating their own final one.
    """
    if not text:
        return None
    matches = _ANSWER_RE.findall(text)
    if not matches:
        return None
    return matches[-1].strip()


def extract_number_str(text: str) -> str | None:
    """Pull the first numeric token from `text` as a normalized string.

    Prefers a mixed number ("1 1/2" -> "3/2") or comma-grouped integer
    ("1,234" -> "1234") over a bare fraction, and a bare fraction ("3/4")
    over a plain number, so that "3/4 of the cake" is read as the fraction,
    not the 3. Whitespace inside a fraction is collapsed ("3 / 4" -> "3/4").
    Returns None when there's no number.
    """
    if not text:
        return None
    m = _MIXED_NUMBER_RE.search(text)
    if m:
        return _normalize_token(m.group(0))
    m = _COMMA_GROUPED_RE.search(text)
    if m:
        return _normalize_token(m.group(0))
    m = _FRACTION_RE.search(text)
    if m:
        return _normalize_token(m.group(0))
    m = _DECIMAL_RE.search(text)
    if m:
        return m.group(0)
    return None


def _last_equation_result(text: str) -> str | None:
    """The value from the LAST explicit '... = value' / '... equals value'
    statement in the text, or None if there is no such statement. Taking the
    last one (not the first) matters when a worked solution states several
    intermediate equations before the final result."""
    matches = list(_EQUATION_RESULT_RE.finditer(text or ""))
    if not matches:
        return None
    return _normalize_token(matches[-1].group(1))


def _all_number_tokens(text: str) -> list[str]:
    """Every numeric token in `text`, left to right, fraction-prioritized at
    each position (matches extract_number_str's own token definition)."""
    return [_normalize_token(m.group(0)) for m in _NUMBER_TOKEN_RE.finditer(text or "")]


def final_number_str(text: str) -> str | None:
    """Best-effort model final value, in decreasing order of confidence:

    1. An explicit 'Answer:' line -- every tutor prompt version is instructed
       to end with one, so this is the normal, reliable case.
    2. The LAST explicit '... = value' / '... equals value' statement in the
       text. Narrower than "the last number anywhere": several controller
       directives instruct the model to append a follow-up suggestion AFTER
       the answer (e.g. "Would you like to try 8 x 7 next?"), and that
       trailing number must not be mistaken for the result.
    3. The sole numeric token in the text, IF there is exactly one -- safe by
       elimination (nothing else for it to be).

    Anything else is ambiguous (e.g. several bare numbers with no structural
    signal for which is the final answer) and returns None rather than
    guessing -- callers (verifier.check) already treat None as "couldn't
    read a number", not as "wrong"."""
    text = text or ""
    line = extract_answer(text)
    if line:
        num = extract_number_str(line)
        if num is not None:
            return num

    eq = _last_equation_result(text)
    if eq is not None:
        return eq

    tokens = _all_number_tokens(text)
    if len(tokens) == 1:
        return tokens[0]
    return None
