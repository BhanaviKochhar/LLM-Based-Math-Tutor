"""scripts/llm/safety.py — deterministic input/output safety gate.

Bounded, keyword/pattern-based child-safety check. Deliberately NOT an LLM
call: the whole point of checking input safety here is that it must run
BEFORE any LLM-based routing (conversation_resolver, intent.classify_intent)
sees the text at all, so an unsafe message is never forwarded to a model.
Symmetrically, check_output() scans what the model itself generated, as a
bounded defense-in-depth layer in case the system-prompt-level refusal
(prompt_registry's "beyond primary school / off-topic" rule) doesn't catch
it -- that rule is about SYLLABUS scope, not child-safety content.

Deliberately NOT implemented here (out of scope for this pass, see the
stabilization brief): a general-purpose moderation model, parent/admin
escalation, or any notification side-effect. This module only classifies
text and returns a decision; callers decide what to do with it (render a
deterministic fallback, log the decision).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Bounded, deliberately conservative pattern lists -- catch clear cases
# without flooding false positives on ordinary child messages. Each pattern
# is a whole-word/phrase match, not a substring, to avoid e.g. flagging
# "class" for containing "ass".
_CATEGORY_PATTERNS: dict[str, list[str]] = {
    "self_harm": [
        r"kill myself", r"want to die", r"wish i was dead", r"end my life",
        r"hurt myself", r"self[\s-]?harm", r"suicide",
    ],
    "violence": [
        r"kill (you|him|her|them)", r"bring a (gun|knife)", r"make a bomb",
        r"hurt (you|him|her|them)",
    ],
    "sexual_profanity": [
        r"\bfuck\w*", r"\bshit\w*", r"\bbitch\w*", r"\bass\s*hole\w*",
        r"\bporn\w*", r"\bsex\w*", r"\bnude\w*", r"\bnaked\b",
    ],
    "personal_info": [
        r"\b\d{3}[\s.-]?\d{3}[\s.-]?\d{4}\b",            # phone-number shaped
        r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",                  # email address
        r"\bmy (home )?address is\b", r"\bi live at\b",
        r"\bmeet me (at|in person)\b",
    ],
}

_COMPILED = {
    cat: [re.compile(p, re.IGNORECASE) for p in pats]
    for cat, pats in _CATEGORY_PATTERNS.items()
}

# Shown to the CHILD -- never mentions the category/keyword matched.
_INPUT_FALLBACK = {
    "self_harm": (
        "I care about you, but I'm just a math helper and not the right "
        "person for this. Please tell a parent, teacher, or another adult "
        "you trust how you're feeling \U0001f49b I'm here whenever you want "
        "to work on math."
    ),
    "violence": (
        "Let's keep our chat kind and focused on math \U0001f642 "
        "What math question can I help you with?"
    ),
    "sexual_profanity": (
        "Let's keep our words kind here \U0001f642 What math question can "
        "I help you with?"
    ),
    "personal_info": (
        "Let's keep things like phone numbers, addresses, or emails "
        "private, okay? I'm here to help with math — what would you "
        "like to work on?"
    ),
}

_OUTPUT_FALLBACK = (
    "Let's try that a different way — could you ask your math "
    "question again? \U0001f642"
)


@dataclass
class SafetyResult:
    blocked: bool
    category: str | None = None   # internal only; never shown to the child
    fallback_text: str | None = None  # set iff blocked


def _first_match(text: str) -> str | None:
    t = text or ""
    for category, patterns in _COMPILED.items():
        if any(p.search(t) for p in patterns):
            return category
    return None


def check_input(text: str) -> SafetyResult:
    """Run BEFORE conversation_resolver/intent classification. A blocked
    result means the turn must stop here -- no resolver, no retrieval, no
    verifier, no generation call for this turn."""
    category = _first_match(text)
    if category is None:
        return SafetyResult(blocked=False)
    return SafetyResult(blocked=True, category=category,
                        fallback_text=_INPUT_FALLBACK[category])


def check_output(text: str) -> SafetyResult:
    """Run AFTER generation, before the reply is rendered. Bounded
    defense-in-depth: the system prompt already instructs the model to stay
    in scope, but nothing previously checked the actual generated text
    against unsafe content categories."""
    category = _first_match(text)
    if category is None:
        return SafetyResult(blocked=False)
    return SafetyResult(blocked=True, category=category, fallback_text=_OUTPUT_FALLBACK)
