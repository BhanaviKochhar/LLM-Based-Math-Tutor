"""scripts/llm/pipeline.py — the single backend entry point for the site.

Tier A restructure (compute-first + inject, with a lightweight gate):

    prepare(question, grade, level, student_id) -> TutorTurn
        Retrieval + a COMPUTE-FIRST step + prompt assembly. No generation yet.
        If the question is computable AND its answer is in a grade-appropriate
        form, sympy solves it here and the trusted answer is injected so
        generation only has to EXPLAIN a known-correct number. Otherwise we take
        the plain path (conceptual, or division taught as remainder).

    turn.stream()   -> generator[str]
    turn.finalize() -> verification dict (post-generation consistency gate)
    resume(...) / get_hint(...) / record_feedback / resolve_level / reset_student

Three computed states per turn (from verifier.solve):
    injected  : computed_answer is a string  -> inject + strict verify
    remainder : is_math True, computed_answer None -> teach remainder, skip
                strict verify (avoids false "mismatch" on "5 R 5")
    conceptual: is_math False -> explain from context, nothing to verify
"""
from __future__ import annotations

from . import hints, prompt_registry, response_parser, student_tracker, verifier

ANSWER_VERSION = "v5-personalized"

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
    """Prefer the tracker's recent-window classification once there's enough
    history; otherwise fall back to the level the UI is showing."""
    if student_id:
        try:
            stats = student_tracker.stats(student_id)
            if stats.get("recent_attempts", 0) >= 3:
                return student_tracker.classify(student_id)
        except Exception:
            pass
    return _norm_level(ui_level)


def _make_source(chunks_meta: list[dict]) -> str:
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
    """One question's worth of work. Retrieval AND computation happen up front;
    only generation is deferred until stream()."""

    def __init__(self, question: str, grade: int, level: str,
                 chunks_meta: list[dict], computed_answer: str | None = None,
                 is_math: bool = False):
        self.question = question
        self.grade = grade
        self.level = level
        self.chunks_meta = chunks_meta
        self.chunks = [c.get("text", "") for c in chunks_meta]
        self.source = _make_source(chunks_meta)
        # Compute-first state:
        self.computed_answer = computed_answer      # injected string or None
        self.is_math = is_math                       # computable at all?
        self.is_injected = computed_answer is not None
        self.messages = prompt_registry.build_messages(
            question, grade, self.chunks, version=ANSWER_VERSION,
            level=level, computed_answer=computed_answer,
        )
        self._handle = None
        self._answer = None
        self._streamed = False

    def stream(self):
        from . import llm_client
        self._handle = llm_client.StreamHandle()
        for piece in llm_client.stream(self.messages, handle=self._handle):
            yield piece
        self._answer = (self._handle.text or "").strip()
        self._streamed = True
        self._log()

    @property
    def answer(self) -> str:
        if self._answer is None and not self._streamed:
            for _ in self.stream():
                pass
        return self._answer or ""

    def finalize(self) -> dict:
        """Post-generation consistency gate.

        Only strict-verify when we injected a trusted value. For the remainder
        case (computable but not injected) and conceptual questions we skip
        strict verify, so a grade-appropriate "5 R 5" isn't flagged as wrong.
        """
        if self.is_injected:
            computed_value = verifier._safe_eval(self.computed_answer)
            return verifier.check(self.question, self.answer,
                                  computed_value=computed_value)
        note = ("taught as remainder; not strictly verified"
                if self.is_math else "conceptual; nothing to verify")
        return verifier._result(False, None, None, None, note)

    def _log(self) -> None:
        try:
            from . import common, llm_client
            common.log_run("tutor-pipeline", self.question, self.grade,
                           self.chunks, self.messages, llm_client.DEFAULT_PARAMS,
                           self._handle.as_result())
        except Exception:
            pass


def _solve(question: str, grade: int) -> tuple[str | None, bool]:
    """Compute-first + gate. Never raises; a solver failure degrades to the
    conceptual path rather than breaking the turn."""
    try:
        return verifier.solve(question, grade)
    except Exception:
        return None, False


def prepare(question: str, grade: int, level: str | None = None,
            student_id: str | None = None) -> TutorTurn:
    from scripts.retrieval import retrieve_with_metadata  # lazy: needs chromadb
    resolved = resolve_level(student_id, level)
    chunks_meta = retrieve_with_metadata(question, grade)
    computed_answer, is_math = _solve(question, grade)
    return TutorTurn(question, grade, resolved, chunks_meta,
                     computed_answer=computed_answer, is_math=is_math)


def resume(question: str, grade: int, chunks: list[str],
           level: str | None = None) -> TutorTurn:
    """Rebuild a turn from stored chunks; re-solve (cheap) so the reveal is
    injected the same way prepare() did."""
    chunks_meta = [{"text": c} for c in chunks]
    computed_answer, is_math = _solve(question, grade)
    return TutorTurn(question, grade, _norm_level(level), chunks_meta,
                     computed_answer=computed_answer, is_math=is_math)


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


def reset_student(student_id: str | None) -> None:
    """Clear a student's tracked history (wire to the UI's Clear chat)."""
    if not student_id:
        return
    try:
        student_tracker.reset(student_id)
    except Exception:
        pass