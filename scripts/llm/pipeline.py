"""scripts/llm/pipeline.py — the single backend entry point for the site.

The Streamlit UI reveals things in stages (hints on tap, answer on tap), so
the pipeline is split to match that flow instead of forcing one big call:

    prepare(question, grade, level, student_id) -> TutorTurn
        Retrieval + prompt assembly only. Cheap, no LLM. Gives you
        .chunks and .source immediately; the answer is generated later.

    turn.stream()      -> generator[str]   (feed to st.write_stream)
    turn.finalize()    -> verification dict (run after the stream is done)

    resume(question, grade, chunks, level) -> TutorTurn
        Rebuild a turn from chunks already stored in the UI session, so the
        answer reveal doesn't re-retrieve or drift from the hints.

    get_hint(...)      -> one hint string (lazy, one LLM call)
    record_feedback / resolve_level  -> personalisation via student_tracker

Level vocabulary is bridged here: the UI speaks
needs_practice/on_track/ahead; the prompts and tracker speak
beginner/intermediate/advanced.
"""
from __future__ import annotations

from . import hints, prompt_registry, response_parser, student_tracker, verifier

ANSWER_VERSION = "v5-personalized"

# UI level  ->  backend level
_UI_TO_LEVEL = {
    "needs_practice": "beginner",
    "on_track": "intermediate",
    "ahead": "advanced",
}
_VALID_LEVELS = {"beginner", "intermediate", "advanced"}


def _norm_level(level: str | None) -> str:
    if not level:
        return "intermediate"
    if level in _VALID_LEVELS:
        return level
    return _UI_TO_LEVEL.get(level, "intermediate")


def resolve_level(student_id: str | None = None, ui_level: str | None = None) -> str:
    """Prefer the tracker's classification once there's history; otherwise
    fall back to the level the UI is showing."""
    if student_id:
        try:
            stats = student_tracker.stats(student_id)
            if stats["attempts"] >= 3:
                return student_tracker.classify(student_id)
        except Exception:
            pass
    return _norm_level(ui_level)


def _make_source(chunks_meta: list[dict]) -> str:
    """Human-readable citation from the top chunk's metadata."""
    if not chunks_meta:
        return ""
    top = chunks_meta[0]
    parts = []
    if top.get("grade") is not None:
        parts.append(f"NCERT Class {top['grade']}")
    if top.get("page") is not None:
        parts.append(f"p.{top['page']}")
    if top.get("topic"):
        parts.append(str(top["topic"]))
    return " \u00b7 ".join(parts) if parts else "NCERT textbook"


class TutorTurn:
    """One question's worth of work. Retrieval happens up front; generation
    is deferred until stream() so the UI can gate it behind the hint flow."""

    def __init__(self, question: str, grade: int, level: str,
                 chunks_meta: list[dict]):
        self.question = question
        self.grade = grade
        self.level = level
        self.chunks_meta = chunks_meta
        self.chunks = [c.get("text", "") for c in chunks_meta]
        self.source = _make_source(chunks_meta)
        self.messages = prompt_registry.build_messages(
            question, grade, self.chunks, version=ANSWER_VERSION, level=level
        )
        self._handle = None
        self._answer = None
        self._streamed = False

    # -- generation ---------------------------------------------------------
    def stream(self):
        """Yield answer tokens; accumulate the full text; log on completion."""
        from . import llm_client  # lazy import keeps pipeline offline-safe

        self._handle = llm_client.StreamHandle()
        for piece in llm_client.stream(self.messages, handle=self._handle):
            yield piece
        self._answer = (self._handle.text or "").strip()
        self._streamed = True
        self._log()

    @property
    def answer(self) -> str:
        if self._answer is None and not self._streamed:
            # Non-streaming callers: run the stream to completion silently.
            for _ in self.stream():
                pass
        return self._answer or ""

    def finalize(self) -> dict:
        """Run the sympy sanity check on the completed answer."""
        return verifier.check(self.question, self.answer)

    def _log(self) -> None:
        try:
            from . import common, llm_client

            common.log_run("tutor-pipeline", self.question, self.grade,
                           self.chunks, self.messages, llm_client.DEFAULT_PARAMS,
                           self._handle.as_result())
        except Exception:
            # Logging is best-effort; never let it break a response.
            pass


def prepare(question: str, grade: int, level: str | None = None,
            student_id: str | None = None) -> TutorTurn:
    """Retrieve context and build a TutorTurn (no generation yet)."""
    from scripts.retrieval import retrieve_with_metadata  # lazy: needs chromadb

    resolved = resolve_level(student_id, level)
    chunks_meta = retrieve_with_metadata(question, grade)
    return TutorTurn(question, grade, resolved, chunks_meta)


def resume(question: str, grade: int, chunks: list[str],
           level: str | None = None) -> TutorTurn:
    """Rebuild a turn from chunks the UI already has (no re-retrieval)."""
    chunks_meta = [{"text": c} for c in chunks]
    turn = TutorTurn(question, grade, _norm_level(level), chunks_meta)
    # The source string needs metadata we don't have on resume; the UI keeps
    # the original source from prepare(), so leaving it blank here is fine.
    return turn


# Convenience wrapper used by app.py for the ask_tutor(...) signature it knows.
def ask_tutor(question: str, grade: int, level: str | None = None,
              student_id: str | None = None) -> TutorTurn:
    return prepare(question, grade, level=level, student_id=student_id)


def get_hint(question: str, grade: int, chunks: list[str], level: str | None,
             hint_number: int, previous_hints: list[str] | None = None) -> str:
    return hints.generate_hint(
        question, grade, chunks, _norm_level(level), hint_number, previous_hints
    )


def record_feedback(student_id: str | None, topic: str, correct: bool) -> None:
    if not student_id:
        return
    try:
        student_tracker.record(student_id, topic=topic[:30], correct=correct)
    except Exception:
        pass
