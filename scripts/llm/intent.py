"""scripts/llm/intent.py — read what a Class 1-5 student wants to do next.

The controller needs to know, on each student turn, which of these it is:

    ATTEMPT       they give an answer, show thinking, or restate the problem
                  to engage with it (restate counts as attempt for this age)
    HINT          they want a clue but intend to keep trying themselves
    SOLVE         they ask to be shown/told the full answer or method
    GIVE_UP       they say they can't do it / don't understand / want to stop
    NEW_QUESTION  they ask a different maths question

Design (three layers, cheap-first):
  1. a deterministic PREFILTER — a bare number/expression is almost always an
     attempt, so we don't spend an LLM call (and can't get it wrong).
  2. an LLM few-shot classifier for free text.
  3. a keyword FALLBACK if the LLM returns nothing (rate limit) — so a throttle
     degrades to a guess rather than crashing the turn.

Buttons in the UI emit these labels directly and bypass all of this; the
classifier only handles typed free text. That's why a fallback guess is
acceptable — the reliable path is always the button.

This module is import-safe offline (LLM import is lazy).
"""
from __future__ import annotations

import re

LABELS = ("ATTEMPT", "HINT", "SOLVE", "GIVE_UP", "NEW_QUESTION")

# A turn that is ONLY digits/operators/punctuation (has at least one digit) —
# "56", "5+5", "is it... " no (has letters). Almost always showing work.
_BARE_EXPR = re.compile(r"^[\d\s+\-*/().=,x×÷]*\d[\d\s+\-*/().=,x×÷]*$")

_SYSTEM = (
    "You label what a Class 1-5 child wants to do next in a maths tutoring "
    "chat. The tutor has just been helping them with a problem and usually just "
    "asked them to try. Read the child's message and reply with EXACTLY ONE of "
    "these labels and nothing else:\n"
    "ATTEMPT - they give an answer, show their thinking, or restate/rephrase "
    "the problem to engage with it\n"
    "HINT - they ask for a hint or clue but want to keep trying\n"
    "SOLVE - they ask you to show or tell them the full answer or how to do it\n"
    "GIVE_UP - they say they can't do it, don't understand, or want to stop\n"
    "NEW_QUESTION - they ask a different maths question\n"
    "Children write short and misspell. Output only the label."
)

_FEWSHOT = [
    ("56", "ATTEMPT"),
    ("is it 12?", "ATTEMPT"),
    ("i think you add them", "ATTEMPT"),
    ("how many toffees was it again", "ATTEMPT"),
    ("maybe 7 left", "ATTEMPT"),
    ("give me a hint", "HINT"),
    ("hint pls", "HINT"),
    ("help me start", "HINT"),
    ("just tell me", "SOLVE"),
    ("show me how", "SOLVE"),
    ("whats the answer", "SOLVE"),
    ("i dont know", "GIVE_UP"),
    ("idk", "GIVE_UP"),
    ("this is too hard", "GIVE_UP"),
    ("i cant do it", "GIVE_UP"),
    ("what is 5 plus 5", "NEW_QUESTION"),
    ("can we do division now", "NEW_QUESTION"),
]

_KEYWORDS = [
    ("HINT", ("hint", "clue", "help me start", "where do i start", "stuck")),
    ("SOLVE", ("tell me", "show me", "the answer", "solve it", "just do it",
               "whats the answer", "what is the answer", "how do you do")),
    ("GIVE_UP", ("dont know", "don't know", "idk", "no idea", "give up",
                 "too hard", "cant", "can't", "cannot", "teach me")),
    ("NEW_QUESTION", ("what is", "how do i", "how many", "can we do",
                      "what about", "next question")),
]


def _prefilter(turn: str) -> str | None:
    t = (turn or "").strip()
    if t and _BARE_EXPR.match(t):
        return "ATTEMPT"
    return None


def _keyword_guess(turn: str) -> str:
    t = (turn or "").lower()
    for label, kws in _KEYWORDS:
        if any(k in t for k in kws):
            return label
    # a number somewhere -> probably showing work; else assume engagement
    if re.search(r"\d", t):
        return "ATTEMPT"
    return "ATTEMPT"


def _normalize(text: str) -> str | None:
    """Pull a label out of possibly-chatty model output.

    Reasoning models may emit thinking around the label. Prefer a line that is
    exactly a label; otherwise take the LAST label mentioned (a model states its
    conclusion last, e.g. "...so this is HINT").
    """
    up = (text or "").strip().upper()
    if not up:
        return None
    # 1) a line that is exactly one label (ignoring stray punctuation)
    for line in up.splitlines():
        token = line.strip().strip(".:-*# ").strip()
        if token in LABELS:
            return token
    # 2) otherwise, the last label that appears anywhere
    last = None
    for lab in LABELS:
        idx = up.rfind(lab)
        if idx != -1 and (last is None or idx > last[0]):
            last = (idx, lab)
    return last[1] if last else None


def _llm_classify(turn: str, context: str | None) -> str | None:
    from . import llm_client  # lazy

    messages = [{"role": "system", "content": _SYSTEM}]
    for ex, lab in _FEWSHOT:
        messages.append({"role": "user", "content": ex})
        messages.append({"role": "assistant", "content": lab})
    user = turn if not context else f"(Tutor just said: {context})\nChild: {turn}"
    messages.append({"role": "user", "content": user})
    result = llm_client.chat(messages, params={"temperature": 0.0, "max_tokens": 256})
    return _normalize(result.get("text") or "")


def classify_intent(turn: str, context: str | None = None,
                    classify_fn=None) -> str:
    """Return one of LABELS. classify_fn is injectable for tests.

    Order: prefilter -> classifier -> keyword fallback. Never raises.
    """
    pre = _prefilter(turn)
    if pre:
        return pre
    try:
        fn = classify_fn or (lambda t, c=context: _llm_classify(t, c))
        label = fn(turn) if classify_fn else _llm_classify(turn, context)
        if label in LABELS:
            return label
    except Exception:
        pass
    return _keyword_guess(turn)