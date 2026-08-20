"""scripts/llm/pipeline.py — backend entry point with conversational question resolution.

Pass 2 memory fix:
    * Resolve elliptical follow-up questions against the current episode BEFORE
      RAG retrieval and BEFORE verifier.solve().
    * Keep the child's original wording for the tutor prompt, while also making
      the resolved mathematical question available to RAG/verifier.
    * Example: previous `3/7+1`, current `if it were plus 5 instead of 1?`
      resolves to `3/7+5`, so RAG and compute-first operate on the right problem.

This file is intended to replace scripts/llm/pipeline.py locally for testing.
"""
from __future__ import annotations

from . import conversation_resolver, hints, prompt_registry, response_parser, student_tracker, verifier

ANSWER_VERSION = "v5-personalized"

_UI_TO_LEVEL = {
    "needs_practice": "beginner",
    "on_track": "intermediate",
    "ahead": "advanced",
}
_VALID_LEVELS = {"beginner", "intermediate", "advanced"}

# Temporary, compact diagnostics for Pass 2 testing.
# Set to False after the follow-up tests pass.
DEBUG_MEMORY = False


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
    return " · ".join(parts) if parts else "NCERT textbook"


class TutorTurn:
    """One question's worth of work. Retrieval and computation happen up front;
    only generation is deferred until stream()."""

    def __init__(
        self,
        question: str,
        grade: int,
        level: str,
        chunks_meta: list[dict],
        computed_answer: str | None = None,
        is_math: bool = False,
        thread_notes: list[str] | None = None,
        active_turns: list[dict] | None = None,
        resolved_question: str | None = None,
        conversation_mode: str = "NEW",
        retrieval_query: str | None = None,
        conversational_directive: str | None = None,
    ):
        self.question = question
        self.resolved_question = resolved_question or question
        self.grade = grade
        self.level = level
        self.chunks_meta = chunks_meta
        self.chunks = [c.get("text", "") for c in chunks_meta]
        self.source = _make_source(chunks_meta)
        self.computed_answer = computed_answer
        self.is_math = is_math
        self.is_injected = computed_answer is not None
        self.thread_notes = thread_notes or []
        self.active_turns = active_turns or []
        self.conversation_mode = conversation_mode
        self.retrieval_query = retrieval_query or self.resolved_question
        self.conversational_directive = conversational_directive

        # Keep the original child wording in the actual tutor conversation,
        # while exposing the resolved problem explicitly to the model when it
        # differs. This lets the child see a natural answer and prevents the
        # model from losing the antecedent of words like "it" or "instead".
        prompt_question = self.question
        if self.resolved_question.strip() != self.question.strip():
            prompt_question = (
                f"Student's message: {self.question}\n\n"
                f"Resolved question for this turn: {self.resolved_question}"
            )
        if self.conversational_directive:
            prompt_question += (
                f"\n\n[Conversation handling: {self.conversational_directive}]"
            )

        self.messages = prompt_registry.build_messages(
            prompt_question,
            grade,
            self.chunks,
            version=ANSWER_VERSION,
            level=level,
            computed_answer=computed_answer,
            thread_notes=self.thread_notes,
            active_turns=self.active_turns,
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
        if self.is_injected:
            computed_value = verifier._safe_eval(self.computed_answer)
            return verifier.check(
                self.resolved_question,
                self.answer,
                computed_value=computed_value,
            )
        note = (
            "taught as remainder; not strictly verified"
            if self.is_math
            else "conceptual; nothing to verify"
        )
        return verifier._result(False, None, None, None, note)

    def _log(self) -> None:
        try:
            from . import common, llm_client
            common.log_run(
                "tutor-pipeline",
                self.question,
                self.grade,
                self.chunks,
                self.messages,
                llm_client.DEFAULT_PARAMS,
                self._handle.as_result(),
            )
        except Exception:
            pass


def _solve(question: str, grade: int) -> tuple[str | None, bool]:
    """Compute-first + gate. Never raises."""
    try:
        return verifier.solve(question, grade)
    except Exception:
        return None, False


def _resolve_question(
    question: str,
    active_turns: list[dict] | None,
):
    """Route the current message using generic conversation understanding."""
    resolution = conversation_resolver.resolve_question(question, active_turns)

    if DEBUG_MEMORY:
        print("\n" + "=" * 80)
        print("DEBUG CONVERSATION ROUTING")
        print(f"ORIGINAL : {resolution.original!r}")
        print(f"MODE     : {resolution.mode}")
        print(f"RESOLVED : {resolution.resolved_question!r}")
        print(f"RAG QUERY: {resolution.retrieval_query!r}")
        print(f"CONF     : {resolution.confidence:.2f}")
        print(f"USE RAG  : {resolution.use_rag}")
        print(f"VERIFY   : {resolution.use_verifier}")
        print("=" * 80)

    return resolution


def _conversation_directive(resolution) -> str | None:
    mode = resolution.mode
    if mode == "CONFUSION":
        return (
            "The child says they do not understand your immediately previous "
            "explanation. Do not treat this as a new question. Re-read the "
            "previous exchange and re-explain the exact idea or step that was "
            "just discussed, using the same numbers and facts. Do not introduce "
            "a different textbook problem. Keep it short and concrete. If the "
            "source of confusion is genuinely unclear, ask one short clarifying "
            "question instead of guessing."
        )
    if mode == "CORRECTION":
        return (
            "The child is correcting or rejecting the previous response. Do not "
            "defend or continue the previous answer blindly. Re-read the recent "
            "conversation, identify the smallest correction implied by the child, "
            "acknowledge it, and answer from that corrected context. Do not invent "
            "a new problem."
        )
    if mode == "FRAGMENT":
        return (
            "This is an incomplete or ambiguous continuation of the current "
            "conversation. Use the recent turns to interpret it conservatively. "
            "Do not invent a new textbook problem or unrelated example. If the "
            "meaning is still unclear, ask one short clarifying question."
        )
    if mode == "CONCEPT_FOLLOWUP":
        return (
            "This is a follow-up about an idea or step already discussed. Build "
            "directly on the previous explanation. The retrieved textbook context "
            "is supplemental and must not override the established conversation. "
            "Answer the child's actual why/how question rather than starting a new "
            "example."
        )
    if mode == "MATH_FOLLOWUP":
        return (
            "This is a modification of the previous mathematical problem. Keep "
            "all unchanged parts of that problem and apply only the change the "
            "child explicitly made. Explain the connection to the previous turn "
            "before giving the result."
        )
    return None


def prepare(
    question: str,
    grade: int,
    level: str | None = None,
    student_id: str | None = None,
    thread_notes: list[str] | None = None,
    active_turns: list[dict] | None = None,
) -> TutorTurn:
    from scripts.retrieval import retrieve_with_metadata

    resolution = _resolve_question(question, active_turns)
    resolved_level_value = resolve_level(student_id, level)

    # RAG is used only when the router says the message contains a substantive
    # knowledge request. Conversational repair messages do not become garbage
    # standalone search queries such as "i dont understand" or "no".
    if resolution.use_rag:
        chunks_meta = retrieve_with_metadata(resolution.retrieval_query, grade)
    else:
        chunks_meta = []

    # The verifier is reserved for a new/modified mathematical problem. A
    # clarification or correction must never be forced through the arithmetic
    # extractor.
    if resolution.use_verifier:
        computed_answer, is_math = _solve(resolution.resolved_question, grade)
    else:
        computed_answer, is_math = None, False

    return TutorTurn(
        question,
        grade,
        resolved_level_value,
        chunks_meta,
        computed_answer=computed_answer,
        is_math=is_math,
        thread_notes=thread_notes,
        active_turns=active_turns,
        resolved_question=resolution.resolved_question,
        conversation_mode=resolution.mode,
        retrieval_query=resolution.retrieval_query,
        conversational_directive=_conversation_directive(resolution),
    )


def resume(
    question: str,
    grade: int,
    chunks: list[str],
    level: str | None = None,
    active_turns: list[dict] | None = None,
) -> TutorTurn:
    """Rebuild a turn from stored chunks while preserving conversation routing."""
    resolution = _resolve_question(question, active_turns)
    if resolution.use_verifier:
        computed_answer, is_math = _solve(resolution.resolved_question, grade)
    else:
        computed_answer, is_math = None, False
    return TutorTurn(
        question,
        grade,
        _norm_level(level),
        [{"text": c} for c in chunks],
        computed_answer=computed_answer,
        is_math=is_math,
        active_turns=active_turns,
        resolved_question=resolution.resolved_question,
        conversation_mode=resolution.mode,
        retrieval_query=resolution.retrieval_query,
        conversational_directive=_conversation_directive(resolution),
    )


def ask_tutor(
    question: str,
    grade: int,
    level: str | None = None,
    student_id: str | None = None,
    active_turns: list[dict] | None = None,
) -> TutorTurn:
    return prepare(
        question,
        grade,
        level=level,
        student_id=student_id,
        active_turns=active_turns,
    )


def get_hint(
    question: str,
    grade: int,
    chunks: list[str],
    level: str | None,
    hint_number: int,
    previous_hints: list[str] | None = None,
    total_hints: int = 3,
    active_turns: list[dict] | None = None,
) -> str:
    resolution = _resolve_question(question, active_turns)
    resolved_question = resolution.resolved_question
    computed_answer, _is_math = _solve(resolved_question, grade)
    return hints.generate_hint(
        resolved_question,
        grade,
        chunks,
        _norm_level(level),
        hint_number,
        previous_hints,
        computed_answer=computed_answer,
        total_hints=total_hints,
    )


def record_feedback(student_id: str | None, topic: str, correct: bool) -> None:
    if not student_id:
        return
    try:
        student_tracker.record(student_id, topic=topic[:30], correct=correct)
    except Exception:
        pass


def reset_student(student_id: str | None) -> None:
    if not student_id:
        return
    try:
        student_tracker.reset(student_id)
    except Exception:
        pass


class TurnStream:
    """Streamable wrapper for a controller-driven turn."""

    def __init__(self, messages: list[dict]):
        self.messages = messages
        self._handle = None
        self.text = ""

    def stream(self):
        from . import llm_client
        self._handle = llm_client.StreamHandle()
        for piece in llm_client.stream(self.messages, handle=self._handle):
            yield piece
        self.text = (self._handle.text or "").strip()
        self._log()

    def _log(self):
        try:
            from . import common, llm_client
            common.log_run(
                "tutor-turn",
                "",
                0,
                [],
                self.messages,
                llm_client.DEFAULT_PARAMS,
                self._handle.as_result(),
            )
        except Exception:
            pass


def generate_turn(
    state,
    action,
    chunks: list[str] | None = None,
    thread_notes: list[str] | None = None,
    active_turns: list[dict] | None = None,
    previous_hints: list[str] | None = None,
):
    """Bridge the controller to the model."""
    from . import controller as C

    chunks = chunks or []

    if action.mode == C.MODE_HINT:
        return get_hint(
            state.question,
            state.grade,
            chunks,
            state.level,
            action.hint_number or 1,
            previous_hints,
            active_turns=active_turns,
        )

    if action.mode == C.MODE_NEW_QUESTION:
        return None

    reveal_modes = {C.MODE_CO_SOLVE, C.MODE_REVEAL}
    injected = state.computed_answer if action.mode in reveal_modes else None

    # Controller state should already contain the resolved question in
    # state.question for Tier B. If it doesn't, retain the existing behaviour.
    messages = prompt_registry.build_messages(
        state.question,
        state.grade,
        chunks,
        version=ANSWER_VERSION,
        level=state.level,
        computed_answer=injected,
        thread_notes=thread_notes,
        active_turns=active_turns,
        directive=action.directive,
    )
    return TurnStream(messages)
