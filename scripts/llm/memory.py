"""scripts/llm/memory.py — conversation memory for the tutor.

Two layers, kept deliberately cheap (see the Tier B memory design):

  * ACTIVE SESSION — the current tutoring episode in full detail (prior
    user/assistant turns). The controller needs all of it to diagnose attempts
    and avoid re-teaching within a question. Represented as a list of
    {"role", "content"} dicts, ready to drop straight into the message list.

  * THREAD — a capped list of one-line notes summarising EARLIER finished
    episodes ("light thread"). Gives the tutor continuity ("you found this
    tricky earlier") without dragging whole explanations along.

Design choices this file encodes:
  * We do NOT classify the topic of a note. Per the agreed design, the model
    judges concept similarity itself from the raw question text in the note.
    So a note records the question + outcome, not a labelled topic.
  * The thread is capped so context can't balloon; the persistent tracker still
    holds the hard performance numbers, so ageing a note out loses only texture.
  * This module is pure/stateless — no Streamlit, no I/O. The UI owns storage
    and passes history in, mirroring the Tier A backend split.
"""
from __future__ import annotations

MAX_THREAD_NOTES = 5
_Q_PREVIEW = 60  # trim long questions in notes so the thread stays compact

# outcome codes correspond to controller terminal states
_OUTCOME_TEXT = {
    "solved": "solved it",
    "shown": "was shown the solution",
    "gave_up": "gave up",
    "moved_on": "moved on",
}


def build_thread_note(question: str, outcome: str,
                      attempts: int = 0, hints: int = 0) -> str:
    """Templated one-line summary of a finished episode (no LLM call).

    Records the raw question so the model can judge concept similarity itself;
    we deliberately don't label the topic.
    """
    q = (question or "").strip().replace("\n", " ")
    if len(q) > _Q_PREVIEW:
        q = q[: _Q_PREVIEW - 1].rstrip() + "\u2026"
    parts = [f'asked "{q}"', _OUTCOME_TEXT.get(outcome, outcome or "moved on")]
    if hints:
        parts.append(f"{hints} hint{'s' if hints != 1 else ''}")
    if attempts:
        parts.append(f"{attempts} attempt{'s' if attempts != 1 else ''}")
    return " \u00b7 ".join(parts)


def cap_thread(notes: list[str]) -> list[str]:
    """Keep only the most recent notes so the thread stays bounded."""
    return list(notes or [])[-MAX_THREAD_NOTES:]


def add_note(thread: list[str], question: str, outcome: str,
             attempts: int = 0, hints: int = 0) -> list[str]:
    """Append a note for a finished episode and return the capped thread."""
    note = build_thread_note(question, outcome, attempts, hints)
    return cap_thread(list(thread or []) + [note])


def thread_summary(thread_notes: list[str]) -> str:
    """Render the thread as a short block for the system prompt, or '' if empty.

    Framed explicitly as context-for-continuity, not content to expand, so the
    model uses it for tone/pacing and doesn't re-teach from it.
    """
    notes = cap_thread(thread_notes)
    if not notes:
        return ""
    lines = "\n".join(f"- {n}" for n in notes)
    return (
        "\n\nEarlier in this session (brief notes, for continuity only — do NOT "
        "re-teach from these, and don't mention them unless relevant):\n" + lines
    )


def active_messages(active_turns) -> list[dict]:
    """Normalise stored active-session turns into chat messages.

    Accepts dicts with 'role'/'content' (or 'text'); ignores anything malformed
    so a stray entry can't break prompt assembly.
    """
    out = []
    for t in active_turns or []:
        if not isinstance(t, dict):
            continue
        role = t.get("role")
        content = t.get("content", t.get("text"))
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": str(content)})
    return out