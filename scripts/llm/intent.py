"""scripts/llm/intent.py — read what a Class 1-5 student wants to do next.

The controller needs to know, on each student turn, which of these it is:

    ATTEMPT        they give an answer, show thinking, or restate the problem
                   to engage with it (restate counts as attempt for this age)
    HINT           they want a clue but intend to keep trying themselves
    CONFUSION      they didn't follow the tutor's LAST explanation of this
                   SAME problem and want it re-explained, not a hint ladder
    SOLVE          they ask to be shown/told the full answer or method
    GIVE_UP        they say they can't do it / want to stop -- distinct from
                   CONFUSION (still engaged, just needs it explained again)
    CORRECTION     they reject/correct the tutor's last reply
    MATH_FOLLOWUP  they change a number/condition in the SAME problem instead
                   of answering it (resolved against the live conversation by
                   scripts.llm.conversation_resolver, not by this module)
    CLARIFY        too incomplete/ambiguous to safely act on
    NEW_QUESTION   they ask a different, unrelated maths question

This module only LABELS the turn; it does not resolve what changed (that is
conversation_resolver's job, invoked by the caller only for the MATH_FOLLOWUP
branch, so the common ATTEMPT/HINT/SOLVE turns still cost exactly one
classification call, not two).

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

LABELS = ("ATTEMPT", "HINT", "SOLVE", "GIVE_UP", "NEW_QUESTION",
         "CONFUSION", "CORRECTION", "MATH_FOLLOWUP", "CLARIFY")

# A turn that is ONLY digits/operators/punctuation (has at least one digit) —
# "56", "5+5", "is it... " no (has letters). Almost always showing work.
_BARE_EXPR = re.compile(r"^[\d\s+\-*/().=,x×÷]*\d[\d\s+\-*/().=,x×÷]*$")

# Deterministic, zero-cost correction guardrail (mirrors
# conversation_resolver's own validated "no/nope/..." pattern, reused here so
# an open episode gets the same safe handling without a second LLM call): a
# bare rejection never needs the model classifier to recognise it.
_CORRECTION_PHRASE = re.compile(
    r"(?:no|nope|nah|not really|that's not it|that is not it|"
    r"thats not it|not what i meant|you misunderstood|"
    r"that's wrong|that is wrong|thats wrong)\s*[.!?]*",
    re.I,
)

_SYSTEM = (
    "You label what a Class 1-5 child wants to do next in a maths tutoring "
    "chat about ONE specific problem. The tutor has just been helping them "
    "with that problem. Read the child's message and reply with EXACTLY ONE "
    "of these labels and nothing else:\n"
    "ATTEMPT - they give an answer, show their thinking, or restate/rephrase "
    "the SAME problem to engage with it\n"
    "HINT - they explicitly ask for a hint or clue, wanting to keep solving "
    "the SAME problem themselves with a little more help (e.g. 'give me a "
    "hint', 'another hint', 'help me start') -- NOT confusion about something "
    "you already said; that is CONFUSION instead\n"
    "CONFUSION - they say they don't understand / are confused / are lost "
    "about your LAST explanation of this problem, or ask you to explain it "
    "again -- they want the SAME idea explained differently, not a numbered "
    "hint and not to stop\n"
    "SOLVE - they ask you to show or tell them the full answer or how to do it\n"
    "GIVE_UP - they explicitly want to STOP trying (e.g. 'I don't know', "
    "'this is too hard', 'I can't do it') -- NOT merely confused and NOT "
    "correcting you; a child who says they don't understand is asking for "
    "help, not quitting, so that is CONFUSION, not GIVE_UP\n"
    "CORRECTION - they reject or correct your LAST reply (e.g. 'no', "
    "'that's not what I meant', 'that's wrong', 'you misunderstood')\n"
    "MATH_FOLLOWUP - they change a number or condition in the SAME problem "
    "instead of answering it (e.g. 'what if it was 150 instead of 136?', "
    "'what about 5 instead?')\n"
    "CLARIFY - the message refers to something ('it', 'that', 'the other "
    "one') without saying what, or is otherwise too fragmentary to act on at "
    "all (e.g. 'the second one', 'what about that', 'huh?')\n"
    "NEW_QUESTION - they name or ask about a different maths topic or "
    "problem than the current one -- including a bare topic name with no "
    "question mark (e.g. 'fractions', 'add and sub', 'multiplication "
    "tables'), since a child this age often types just the topic, not a full "
    "question. If it names a self-contained topic/problem, it is "
    "NEW_QUESTION even without a question mark; CLARIFY is only for messages "
    "with nothing to act on at all\n"
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
    ("i dont understand", "CONFUSION"),
    ("i dont get it", "CONFUSION"),
    ("i'm confused", "CONFUSION"),
    ("wait what does that mean", "CONFUSION"),
    ("can you explain that again", "CONFUSION"),
    ("just tell me", "SOLVE"),
    ("show me how", "SOLVE"),
    ("whats the answer", "SOLVE"),
    ("i dont know", "GIVE_UP"),
    ("idk", "GIVE_UP"),
    ("this is too hard", "GIVE_UP"),
    ("i cant do it", "GIVE_UP"),
    ("no thats not what i meant", "CORRECTION"),
    ("thats wrong", "CORRECTION"),
    ("you misunderstood me", "CORRECTION"),
    ("what if it was 150 instead of 136", "MATH_FOLLOWUP"),
    ("what about 5 instead", "MATH_FOLLOWUP"),
    ("the second one", "CLARIFY"),
    ("what about that", "CLARIFY"),
    ("what is 5 plus 5", "NEW_QUESTION"),
    ("can we do division now", "NEW_QUESTION"),
    ("add and sub", "NEW_QUESTION"),
    ("fractions", "NEW_QUESTION"),
    ("learn addition", "NEW_QUESTION"),
]

# Order matters: each label is checked top-to-bottom and the first match
# wins, so a phrase that could plausibly fit two labels resolves to the one
# listed first. CORRECTION and CONFUSION are both checked well before
# GIVE_UP so "I can't understand this" (contains "cant", a GIVE_UP keyword)
# still resolves to the keep-going CONFUSION reading, matching the _SYSTEM
# prompt's explicit distinction above.
_KEYWORDS = [
    ("CORRECTION", ("thats not what i meant", "that's not what i meant",
                    "you misunderstood", "thats wrong", "that's wrong",
                    "not what i meant", "no thats not", "no that's not")),
    ("CONFUSION", ("dont understand", "don't understand", "cant understand",
                  "can't understand", "dont get it", "don't get it",
                  "confused", "what does that mean", "what do you mean",
                  "explain that again", "explain again", "im lost",
                  "i'm lost")),
    ("HINT", ("hint", "clue", "help me start", "where do i start", "stuck")),
    ("SOLVE", ("tell me", "show me", "the answer", "solve it", "just do it",
               "whats the answer", "what is the answer", "how do you do")),
    ("GIVE_UP", ("dont know", "don't know", "idk", "no idea", "give up",
                 "too hard", "cant", "can't", "cannot", "teach me")),
    ("NEW_QUESTION", ("what is", "how do i", "how many", "can we do",
                      "next question")),
]


def _prefilter(turn: str) -> str | None:
    t = (turn or "").strip()
    if not t:
        return None
    if _CORRECTION_PHRASE.fullmatch(t):
        return "CORRECTION"
    if _BARE_EXPR.match(t):
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