"""scripts/llm/hints.py — one short LLM call per hint level.

The Streamlit UI reveals hints one tap at a time, one per step of the actual
worked solution (Hint 1 -> 2 -> ... -> N -> full answer), where N is however
many steps that specific problem's solution has. We generate each hint
lazily, only when its button is pressed, so a child who solves it early never
costs extra calls. Every hint is grounded in the SAME retrieved chunks as the
eventual answer, plus the true computed answer (never spoken aloud), and each
level is told what earlier hints already said, so the levels escalate
through the real working instead of repeating themselves.

A hint NEVER states the final answer — that's what the answer reveal is for.
"""
from __future__ import annotations

from .prompt_registry import LEVEL_STYLE

_HINT_SYSTEM = (
    "You are Ganita Didi, a warm, patient maths tutor for a Class {grade} "
    "child in India. Teach ONLY from the textbook context provided. You are "
    "giving a HINT, not the solution. Use simple words and everyday Indian "
    "examples (toffees, mangoes, rupees). Keep it to 1-2 short sentences.\n"
    "The correct final answer to this question is {computed_answer}, given "
    "to you ONLY so your hint points toward the right working — never say "
    "this number or the final answer out loud in your hint.\n"
    "Never state the final numeric answer.\n"
    "Teaching style for this student:\n{level_style}"
)

_GUIDANCE_FIRST = (
    "Give only a gentle nudge — name the idea or what to think about, and "
    "what operation or approach applies here. Do not do any calculation."
)
_GUIDANCE_LAST = (
    "Walk right up to the answer: give the final step of the working so the "
    "child only has one small thing left to do themselves. Do NOT say the "
    "final number."
)
_GUIDANCE_MIDDLE = (
    "Continue naturally from the earlier hints, moving the child one real "
    "step closer to solving it — a concrete number or partial setup from "
    "the problem. If the working is short and there isn't a distinct new "
    "step left to reveal, it's fine to rephrase or reinforce the last hint "
    "more concretely instead of forcing a new one. Do NOT complete the "
    "calculation or state the final answer."
)
_GUIDANCE_SINGLE = (
    "Give one focused hint that names the key idea AND the first concrete "
    "step, without doing the full calculation or stating the final answer."
)


def _guidance_for(hint_number: int, total_hints: int) -> str:
    """Guidance text scaled to however many hints this problem actually has
    (its real step count), instead of a fixed 3-level scheme."""
    if total_hints <= 1:
        return _GUIDANCE_SINGLE
    if hint_number <= 1:
        return _GUIDANCE_FIRST
    if hint_number >= total_hints:
        return _GUIDANCE_LAST
    return _GUIDANCE_MIDDLE


def _fallback_hint(hint_number: int, total_hints: int) -> str:
    if hint_number <= 1:
        return "Think about what the question is really asking you to find."
    if hint_number >= total_hints:
        return "You're almost there — put the steps together and see what you get."
    return "Let's set up the next step together — what do we know so far?"


def _context(chunks: list[str]) -> str:
    return "\n\n".join(f"[{i}] {c}" for i, c in enumerate(chunks, 1)) or "(no context found)"


def build_hint_messages(question: str, grade: int, chunks: list[str],
                        level: str, hint_number: int,
                        previous_hints: list[str] | None = None,
                        computed_answer: str | None = None,
                        total_hints: int = 3) -> list[dict]:
    level_style = LEVEL_STYLE.get(level, LEVEL_STYLE["intermediate"])
    system = _HINT_SYSTEM.format(
        grade=grade, level_style=level_style,
        computed_answer=computed_answer if computed_answer is not None
        else "(not computable — conceptual question)",
    )
    guidance = _guidance_for(hint_number, total_hints)

    prior = previous_hints or []
    prior_block = (
        "Earlier hints already given (do not repeat them; each hint must "
        "move one real step closer to solving it than the last):\n"
        + "\n".join(f"- {h}" for h in prior)
        if prior else "No earlier hints yet."
    )

    user = (
        f"Textbook context:\n{_context(chunks)}\n\n"
        f"Class {grade} student's question: {question}\n\n"
        f"This solution has {total_hints} step(s) in total. "
        f"Write Hint {hint_number} of {total_hints}. {guidance}\n{prior_block}\n\n"
        f"IMPORTANT: Output ONLY the hint sentence(s) themselves. Do not "
        f"include any label like 'Hint 1 of 3:' or 'Hint:' — the app adds "
        f"that automatically."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def generate_hint(question: str, grade: int, chunks: list[str], level: str,
                  hint_number: int, previous_hints: list[str] | None = None,
                  computed_answer: str | None = None,
                  total_hints: int = 3, chat_fn=None) -> str:
    """Return a single hint string. `chat_fn` is injectable for testing."""
    messages = build_hint_messages(
        question, grade, chunks, level, hint_number, previous_hints,
        computed_answer, total_hints,
    )
    if chat_fn is None:
        from . import llm_client

        chat_fn = llm_client.chat

    result = chat_fn(messages, params={"temperature": 0.3, "max_tokens": 220})
    text = (result.get("text") or "").strip()
    if not text:
        return _fallback_hint(hint_number, total_hints)
    return text
