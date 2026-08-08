"""scripts/llm/hints.py — one short LLM call per hint level.

The Streamlit UI reveals hints one tap at a time (Hint 1 -> 2 -> 3 -> full
answer). We generate each hint lazily, only when its button is pressed, so a
child who solves it after Hint 1 never costs three calls. Every hint is
grounded in the SAME retrieved chunks as the eventual answer, and each level
is told what depth to give and what the earlier hints already said, so the
three levels escalate instead of repeating.

A hint NEVER states the final answer — that's what the answer reveal is for.
"""
from __future__ import annotations

# Personalisation styles are shared with the answer prompts.
from .prompt_registry import LEVEL_STYLE

_HINT_SYSTEM = (
    "You are Ganita Didi, a warm, patient maths tutor for a Class {grade} "
    "child in India. Teach ONLY from the textbook context provided. You are "
    "giving a HINT, not the solution. Use simple words and everyday Indian "
    "examples (toffees, mangoes, rupees). Keep it to 1-2 short sentences.\n"
    "Never state the final numeric answer.\n"
    "Teaching style for this student:\n{level_style}"
)

# What each level is allowed to reveal.
_LEVEL_GUIDANCE = {
    1: ("Give only a gentle nudge — name the idea or what to think about. "
        "Do not do any calculation."),
    2: ("Give the first concrete step to set the problem up. Show how to "
        "begin, but do NOT reach the final answer."),
    3: ("Walk right up to the answer: show the key step so the child can "
        "finish it themselves, but do NOT say the final number."),
}


def _context(chunks: list[str]) -> str:
    return "\n\n".join(f"[{i}] {c}" for i, c in enumerate(chunks, 1)) or "(no context found)"


def build_hint_messages(question: str, grade: int, chunks: list[str],
                        level: str, hint_number: int,
                        previous_hints: list[str] | None = None) -> list[dict]:
    level_style = LEVEL_STYLE.get(level, LEVEL_STYLE["intermediate"])
    system = _HINT_SYSTEM.format(grade=grade, level_style=level_style)
    guidance = _LEVEL_GUIDANCE.get(hint_number, _LEVEL_GUIDANCE[1])

    prior = previous_hints or []
    prior_block = (
        "Earlier hints already given (do not repeat them):\n"
        + "\n".join(f"- {h}" for h in prior)
        if prior else "No earlier hints yet."
    )

    user = (
        f"Textbook context:\n{_context(chunks)}\n\n"
        f"Class {grade} student's question: {question}\n\n"
        f"Write Hint {hint_number}. {guidance}\n{prior_block}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def generate_hint(question: str, grade: int, chunks: list[str], level: str,
                  hint_number: int, previous_hints: list[str] | None = None,
                  chat_fn=None) -> str:
    """Return a single hint string. `chat_fn` is injectable for testing."""
    messages = build_hint_messages(
        question, grade, chunks, level, hint_number, previous_hints
    )
    if chat_fn is None:
        from . import llm_client  # lazy import keeps this module offline-safe

        chat_fn = llm_client.chat

    result = chat_fn(messages, params={"temperature": 0.3, "max_tokens": 160})
    text = (result.get("text") or "").strip()
    if not text:
        # Graceful, kid-friendly fallback so the UI never shows a blank hint.
        return {
            1: "Think about what the question is really asking you to find.",
            2: "Let's set up the first step together — what do we know so far?",
            3: "You're almost there — put the steps together and see what you get.",
        }.get(hint_number, "Give it a try — you're on the right track!")
    return text
