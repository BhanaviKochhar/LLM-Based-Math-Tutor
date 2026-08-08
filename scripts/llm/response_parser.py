"""scripts/llm/response_parser.py — read structured bits out of model text.

The tutor prompts (v1..v5) all end the answer with a line like

    Answer: 42

so the sanity checker can find the model's final value reliably. This module
locates that value and extracts a clean numeric token (integer, decimal, or
fraction) from free text. It does no maths — turning a token into a value and
comparing lives in verifier.py.
"""
from __future__ import annotations

import re

# The refusal sentinel shared by every prompt version.
REFUSAL_MARKER = "ask your teacher"

# "Answer:" possibly bold/starred, capturing the rest of that line.
_ANSWER_RE = re.compile(r"(?im)^\s*\**\s*answer\s*\**\s*[:\-]\s*\**\s*(.+?)\s*$")

# A number: optional sign, then a fraction a/b, or a decimal/integer.
_FRACTION_RE = re.compile(r"[-+]?\d+\s*/\s*\d+")
_DECIMAL_RE = re.compile(r"[-+]?\d*\.\d+|[-+]?\d+")


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

    Prefers a fraction ("3/4") over a plain number so that "3/4 of the cake"
    is read as the fraction, not the 3. Whitespace inside a fraction is
    collapsed ("3 / 4" -> "3/4"). Returns None when there's no number.
    """
    if not text:
        return None
    m = _FRACTION_RE.search(text)
    if m:
        return re.sub(r"\s+", "", m.group(0))
    m = _DECIMAL_RE.search(text)
    if m:
        return m.group(0)
    return None


def final_number_str(text: str) -> str | None:
    """Best-effort model final value: try the 'Answer:' line first, then fall
    back to scanning the whole reply."""
    line = extract_answer(text)
    if line:
        num = extract_number_str(line)
        if num is not None:
            return num
    return extract_number_str(text or "")
