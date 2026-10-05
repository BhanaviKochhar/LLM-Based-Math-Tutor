"""frontend/test_app.py — offline tests for the controller-integration glue
in frontend/app.py (start_episode / advance_episode / submit_turn / the
per-turn helpers).

These are deterministic unit tests: all LLM/generation calls are mocked, so
nothing here calls Groq/HF or spends an API credit. They verify WIRING and
STATE-MACHINE CORRECTNESS, not response quality. A few tests (marked below)
exercise scripts.llm.controller directly against the REAL state machine
(cheap, pure, no LLM) to pin down a behavioural root cause found during
manual review — see test_conceptual_episode_never_advances.

Response-quality questions (does a generated explanation actually recognise
a child's reasoning, is a hint relevant, etc.) cannot be asserted
deterministically and are NOT covered here; see the development checkpoint
notes for the manual/evidence-based findings on that.

Run:  python -m frontend.test_app
"""
from __future__ import annotations

from scripts.llm import controller as C, hints, pipeline, safety, verifier
from frontend import app

_passed = 0
_failed = 0


def check(name: str, cond: bool) -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok   {name}")
    else:
        _failed += 1
        print(f"  FAIL {name}")


# --------------------------------------------------------------------------- helpers
class _FakeStream:
    """Stand-in for pipeline.TurnStream: .stream() yields once, then .text
    holds the full reply, matching what _run_generation expects."""

    def __init__(self, text: str):
        self.text = text

    def stream(self):
        yield self.text


def _new_chat(episode=None) -> dict:
    return {"messages": [], "episode": episode}


def _math_episode(attempts: int = 0, computed_answer: str = "56") -> dict:
    state = C.TutorState(
        question="What is 7 times 8?", grade=3, level="intermediate",
        computed_answer=computed_answer, is_math=True, attempts=attempts,
    )
    return {"state": state, "chunks": [], "source": "", "hints_shown": []}


class _Patch:
    """Minimal monkeypatch-and-restore context manager (no pytest in this repo)."""

    def __init__(self, obj, name, value):
        self.obj, self.name, self.value = obj, name, value

    def __enter__(self):
        self._orig = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)
        return self

    def __exit__(self, *exc):
        setattr(self.obj, self.name, self._orig)


# --------------------------------------------------------- A: generation-failure rollback
def test_generation_failure_rolls_back_state() -> None:
    print("A. state consistency on generation failure")

    chat = _new_chat(_math_episode(attempts=0))
    pre_attempts = chat["episode"]["state"].attempts
    pre_phase = chat["episode"]["state"].phase

    def boom(*a, **kw):
        raise RuntimeError("provider down")

    # record_feedback is mocked throughout: this test exercises state/rollback
    # wiring, not the tracker, and must not touch the real data/students.json.
    with _Patch(app, "record_feedback", lambda *a, **kw: None):
        with _Patch(pipeline, "generate_turn", boom):
            reply = app.submit_turn(chat, "54", 3, "on_track", [])

        check("failure returns a reply, not a crash", isinstance(reply, dict))
        check("failure message is distinguishable from the ambiguous-input fallback",
              reply.get("reply") != app._friendly_reply("54"))
        check("controller attempts NOT incremented after a failed generation",
              chat["episode"]["state"].attempts == pre_attempts)
        check("controller phase unchanged after a failed generation",
              chat["episode"]["state"].phase == pre_phase)

        # Retry the SAME input once generation works — should advance exactly
        # once, not be double-counted from the failed attempt above.
        with _Patch(pipeline, "generate_turn",
                   lambda *a, **kw: _FakeStream("Nice try! Add 7 eight times again.")):
            reply2 = app.submit_turn(chat, "54", 3, "on_track", [])
    check("retry after failure succeeds", reply2.get("mode") == "diagnose_wrong")
    check("retry advances attempts exactly once (no duplication from the failure)",
          chat["episode"]["state"].attempts == pre_attempts + 1)


# -------------------------------------------- A4: hint lifecycle integration
def test_hint_lifecycle_integration() -> None:
    """Integration-level (through submit_turn/_apply_action), complementing
    eval/controller_walk.py's pure-controller hint-lifecycle scenario. Covers
    what the controller test can't: the actual generated/fixed TEXT reaching
    the reply dict, hints_shown bookkeeping, and a hint-specific
    generation-failure+retry (the existing test above only exercises an
    ATTEMPT failure)."""
    print("A4. hint lifecycle through submit_turn: numbering, exhaustion, failure+retry")

    chat = _new_chat(_math_episode(attempts=0))

    def _hint_fn(n):
        # hints.generate_hint returns an already-generated plain STRING
        # (pipeline.get_hint/generate_turn pass it straight through, no
        # TurnStream wrapping) -- patch at THIS level, not pipeline.generate_turn
        # itself, so the real MODE_HINT/MODE_HINT_EXHAUSTED dispatch logic in
        # pipeline.generate_turn actually runs and is genuinely exercised,
        # rather than being bypassed by the mock.
        return lambda *a, **kw: f"hint text #{n}"

    with _Patch(app, "record_feedback", lambda *a, **kw: None):
        for n in (1, 2, 3):
            with _Patch(hints, "generate_hint", _hint_fn(n)):
                reply = app.submit_turn(chat, "Another hint", 3, "on_track", [],
                                        forced_intent="HINT")
            check(f"hint {n}: mode=hint, hint_number={n} (state-driven)",
                 reply.get("mode") == "hint" and reply.get("hint_number") == n)
            check(f"hint {n}: text is the generated hint, not a placeholder",
                 reply.get("text") == f"hint text #{n}")
        check("3 real hints were generated and spent an LLM call each",
             len(chat["episode"]["hints_shown"]) == 3)

        # 4th request: the REAL pipeline.generate_turn/controller.step run
        # unmocked; only hints.generate_hint is instrumented, so this
        # genuinely proves the LLM-calling function is never reached once
        # exhausted, rather than just proving a mock wasn't called.
        called = {"n": 0}

        def _should_not_be_called(*a, **kw):
            called["n"] += 1
            return "should never see this"

        with _Patch(hints, "generate_hint", _should_not_be_called):
            reply4 = app.submit_turn(chat, "Another hint", 3, "on_track", [],
                                     forced_intent="HINT")
            check("4th hint request -> mode=hint_exhausted, not another generated hint",
                 reply4.get("mode") == "hint_exhausted")
            check("4th hint request's fixed message does not repeat an earlier hint string",
                 reply4.get("text") not in {"hint text #1", "hint text #2", "hint text #3"})
            check("the exhausted-hint message does NOT get appended to hints_shown "
                 "(it isn't a real hint and must not pollute future hint context)",
                 len(chat["episode"]["hints_shown"]) == 3)
            check("'Another hint' is no longer offered once exhausted",
                 "Another hint" not in reply4.get("buttons", []))
            check("hints.generate_hint was never called for the exhausted request "
                 "(no LLM call spent)", called["n"] == 0)

            # Repeated click on the already-exhausted state: still
            # idempotent, still zero LLM calls.
            reply5 = app.submit_turn(chat, "Another hint", 3, "on_track", [],
                                     forced_intent="HINT")
        check("a second click after exhaustion is still hint_exhausted, "
             "no further LLM call made (called['n'] stayed 0 across both attempts)",
             reply5.get("mode") == "hint_exhausted" and called["n"] == 0)

    # Hint-specific generation failure + retry (distinct from the ATTEMPT
    # failure already covered above): a failed hint call must not consume a
    # hint slot, and retrying must produce the SAME hint number, not skip one.
    chat2 = _new_chat(_math_episode(attempts=0))
    with _Patch(app, "record_feedback", lambda *a, **kw: None):
        with _Patch(hints, "generate_hint",
                   lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("provider down"))):
            fail_reply = app.submit_turn(chat2, "Give me a hint", 3, "on_track", [],
                                         forced_intent="HINT")
        check("a failed hint generation returns a reply, not a crash",
             isinstance(fail_reply, dict))
        check("hints_given is NOT incremented after a failed hint generation",
             chat2["episode"]["state"].hints_given == 0)

        with _Patch(hints, "generate_hint", _hint_fn(1)):
            retry_reply = app.submit_turn(chat2, "Give me a hint", 3, "on_track", [],
                                          forced_intent="HINT")
        check("retrying after a failed hint generation produces Hint 1 "
             "(not Hint 2 -- no hint silently skipped by the failed attempt)",
             retry_reply.get("hint_number") == 1
             and chat2["episode"]["state"].hints_given == 1)


def test_empty_generation_treated_as_failure() -> None:
    print("A2. empty generation (no exception) also rolls back")

    chat = _new_chat(_math_episode(attempts=0))
    pre_attempts = chat["episode"]["state"].attempts

    with _Patch(app, "record_feedback", lambda *a, **kw: None):
        with _Patch(pipeline, "generate_turn", lambda *a, **kw: _FakeStream("")):
            reply = app.submit_turn(chat, "54", 3, "on_track", [])

    check("empty text does not crash", isinstance(reply, dict))
    check("empty text is not presented as a successful tutoring turn",
          reply.get("mode") is None)
    check("attempts not committed on empty generation",
          chat["episode"]["state"].attempts == pre_attempts)


def test_start_episode_does_not_commit_on_failure() -> None:
    print("A3. a failed FIRST turn leaves no silently-started episode")

    chat = _new_chat(episode=None)

    class _Resolution:
        resolved_question = "What is 2 + 2?"
        retrieval_query = "What is 2 + 2?"
        use_rag = False
        use_verifier = False

    with _Patch(app, "record_feedback", lambda *a, **kw: None), \
         _Patch(pipeline, "generate_turn",
               lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("down"))), \
         _Patch(pipeline, "resolve_level", lambda *a, **kw: "intermediate"), \
         _Patch(pipeline, "resolve_conversation", lambda *a, **kw: _Resolution()):
        # Avoid network for resolution/retrieval/solve too, since this test is
        # about the commit-on-failure contract, not the resolver/retriever.
        reply = app.submit_turn(chat, "What is 2 + 2?", 3, "on_track", [])
    check("failure on the first turn still returns a reply", isinstance(reply, dict))
    check("no episode is left behind after a failed first turn",
          chat["episode"] is None)


# --------------------------------------------------------------- B: practice-problem shortcut
def test_practice_problem_shortcut_disabled() -> None:
    print("B. practice-problem shortcut")
    check("'Practice problem' is not rendered as an actionable button "
         "(no generator exists to back it — documented known limitation)",
          "Practice problem" not in app._ACTIONABLE_LABELS)
    check("'New question' remains the actionable way to close a finished episode",
          "New question" in app._CLOSE_EPISODE_LABELS)


# ----------------------------------------------------------- C: feedback/tracking semantics
def test_attempt_recording_semantics() -> None:
    print("C. feedback recording distinguishes correct / wrong / give-up / reveal")

    calls = []

    def fake_record(question, correct):
        calls.append((question, correct))

    with _Patch(app, "record_feedback", fake_record):
        correct_state = C.TutorState(question="q", grade=3, level="intermediate",
                                     computed_answer="56", is_math=True)
        app._record_outcome(correct_state, C.Action(C.MODE_DIAGNOSE_CORRECT, "", outcome="solved"))
        check("correct attempt recorded as True", calls[-1] == ("q", True))

        wrong_state = C.TutorState(question="q", grade=3, level="intermediate",
                                   computed_answer="56", is_math=True, attempts=1)
        app._record_outcome(wrong_state, C.Action(C.MODE_DIAGNOSE_WRONG, "", outcome=None))
        check("non-terminal wrong attempt recorded as False", calls[-1] == ("q", False))

        cosolve_state = C.TutorState(question="q", grade=3, level="intermediate",
                                     computed_answer="56", is_math=True, attempts=2)
        app._record_outcome(cosolve_state, C.Action(C.MODE_CO_SOLVE, "", outcome="shown", terminal=True))
        check("threshold-reached co_solve (a real final wrong attempt) recorded as False",
              calls[-1] == ("q", False))

        n_before = len(calls)
        gaveup_state = C.TutorState(question="q", grade=3, level="intermediate",
                                    computed_answer="56", is_math=True, attempts=0)
        app._record_outcome(gaveup_state, C.Action(C.MODE_CO_SOLVE, "", outcome="gave_up", terminal=True))
        check("giving up is NOT recorded as a wrong attempt (no attempt was made)",
              len(calls) == n_before)

        n_before = len(calls)
        cold_reveal_state = C.TutorState(question="q", grade=3, level="intermediate",
                                         computed_answer="56", is_math=True, attempts=0)
        app._record_outcome(cold_reveal_state, C.Action(C.MODE_REVEAL, "", outcome="shown", terminal=True))
        check("a cold reveal (asked to be shown, never attempted) is NOT recorded",
              len(calls) == n_before)

        warm_reveal_state = C.TutorState(question="q", grade=3, level="intermediate",
                                         computed_answer="56", is_math=True, attempts=1)
        app._record_outcome(warm_reveal_state, C.Action(C.MODE_REVEAL, "", outcome="shown", terminal=True))
        check("a reveal after at least one real attempt IS recorded as False",
              calls[-1] == ("q", False))

        n_before = len(calls)
        app._record_outcome(correct_state, C.Action(C.MODE_HINT, "", outcome=None))
        app._record_outcome(correct_state, C.Action(C.MODE_ACK_CONCEPTUAL, "", outcome=None))
        check("hints and conceptual acknowledgements are not graded attempts",
              len(calls) == n_before)


# --------------------------------------------------------------- D: public verifier/pipeline API
def test_public_api_wrappers() -> None:
    print("D. frontend uses public wrappers, not private package internals")

    check("verifier.parse_trusted_value matches the internal evaluator",
          verifier.parse_trusted_value("3/4") == verifier._safe_eval("3/4"))

    calls = []
    with _Patch(pipeline, "_resolve_question",
               lambda q, at, grade=3: calls.append(("resolve", q, at, grade)) or "R"):
        result = pipeline.resolve_conversation("q", None)
    check("resolve_conversation forwards to the resolver",
         calls == [("resolve", "q", None, 3)] and result == "R")

    calls.clear()
    with _Patch(pipeline, "_solve", lambda q, g: calls.append(("solve", q, g)) or ("5", True)):
        result = pipeline.compute_trusted_answer("q", 3)
    check("compute_trusted_answer forwards to the solver",
          calls == [("solve", "q", 3)] and result == ("5", True))

    calls.clear()
    with _Patch(pipeline, "_make_source", lambda meta: calls.append(("source", meta)) or "SRC"):
        result = pipeline.source_citation([{"grade": 4}])
    check("source_citation forwards to the source builder",
          calls == [("source", [{"grade": 4}])] and result == "SRC")

    import frontend.app as app_mod
    check("app.py no longer reaches into pipeline._* / verifier._* internals", True
          if _no_private_calls_in_app() else False)


def _no_private_calls_in_app() -> bool:
    import re
    src = open(app.__file__, encoding="utf-8").read()
    return not re.search(r"pipeline\._|verifier\._", src)


# ----------------------------------------------------------- E: verification success/failure
def test_post_check_paths() -> None:
    print("E. post-generation verification paths")

    state = C.TutorState(question="q", grade=3, level="intermediate",
                         computed_answer="56", is_math=True)
    reveal = C.Action(C.MODE_REVEAL, "", outcome="shown", terminal=True)

    v_match = app._post_check(state, reveal, "working...\nAnswer: 56")
    check("matching stated answer -> verifiable + match True",
          v_match is not None and v_match["verifiable"] and v_match["match"] is True)

    v_mismatch = app._post_check(state, reveal, "working...\nAnswer: 50")
    check("disagreeing stated answer -> verifiable + match False",
          v_mismatch["verifiable"] and v_mismatch["match"] is False)

    v_unreadable = app._post_check(state, reveal, "I think we're done here.")
    check("no readable number -> verifiable but match None (unverifiable, not silently correct)",
          v_unreadable["verifiable"] and v_unreadable["match"] is None)

    hint_action = C.Action(C.MODE_HINT, "", outcome=None)
    check("a mode with no injected answer (e.g. hint) is not checked at all",
          app._post_check(state, hint_action, "a hint") is None)

    no_truth_state = C.TutorState(question="q", grade=3, level="intermediate",
                                  computed_answer=None, is_math=False)
    check("reveal/co_solve with no computed answer is not checked",
          app._post_check(no_truth_state, reveal, "some text") is None)

    # diagnose_correct: the controller already graded the STUDENT's stated
    # answer before this runs; this covers the separate case of the model's
    # own celebratory restatement naming the wrong number (see
    # docs/current_state_evaluation.md Section 2 — previously uncaught).
    diagnose_correct = C.Action(C.MODE_DIAGNOSE_CORRECT, "", outcome="solved", terminal=True)

    v_confirm_match = app._post_check(state, diagnose_correct, "Great job! The answer is 56.")
    check("diagnose_correct: model's restatement matching the computed answer -> match True",
          v_confirm_match is not None and v_confirm_match["verifiable"]
          and v_confirm_match["match"] is True)

    v_confirm_mismatch = app._post_check(state, diagnose_correct, "Great job! The answer is 50.")
    check("diagnose_correct: model's restatement naming a DIFFERENT number -> match False",
          v_confirm_mismatch["verifiable"] and v_confirm_mismatch["match"] is False)


# ----------------------------------- root-cause diagnostic for the reviewed conversation
def test_conceptual_episode_never_advances() -> None:
    """Pins down the root cause behind the observed repetition / non-recognition
    behaviour in the reviewed "fractions" conversation (see checkpoint notes,
    Cases A & C): once an episode starts from a non-computable prompt
    (is_math=False, computed_answer=None), controller.diagnose() can only ever
    return "engaged" for ANY student reply, so every subsequent turn routes to
    the same non-terminal MODE_ACK_CONCEPTUAL action regardless of what the
    student actually wrote. This is a real controller/architecture property,
    confirmed live against scripts.llm.controller (no mocking) — it is NOT a
    frontend wiring bug. controller.step()/diagnose() still behave exactly
    this way by design; this test exercises that directly and its assertions
    remain correct. The episode is no longer stuck here forever, though:
    controller.graduate_if_computable(), wired into frontend/app.py's
    _apply_action, can lift it out of this exact loop once the model's own
    MODE_ACK_CONCEPTUAL reply poses a computable follow-up question — a
    mitigation this test deliberately does not exercise, since it calls
    C.step() directly rather than going through _apply_action."""
    print("Diagnostic: conceptual (ungradable) episodes never progress past teach_invite via controller.step() alone")

    state, action = C.start("fractions", 4, "intermediate", computed_answer=None, is_math=False)
    check("a non-computable topic starts with teach_invite, not terminal",
          action.mode == C.MODE_TEACH_INVITE and not action.terminal)

    for turn in ("3/9", "8/10 means i have 8 of the 10 total pieces.",
                "I have one mango, cut in 2 pieces. I have both pieces."):
        state, action = C.step(state, "ATTEMPT", turn)
        check(f"ATTEMPT {turn[:30]!r}... -> ack_conceptual, non-terminal, no attempt counted",
              action.mode == C.MODE_ACK_CONCEPTUAL and not action.terminal and state.attempts == 0)


# ------------------------------------------------- F: active-episode routing fixes
def test_math_followup_preserves_relationship() -> None:
    """Stabilization-pass fix (Problem 2 / Step 10): a contextual follow-up
    that changes a number in the CURRENT problem ("what if it was 150
    instead of 136?") used to fall through to intent.py's ATTEMPT handling
    (the only vocabulary an open episode's turns were routed through),
    which — seeing two numbers and no single stated answer — asked "what
    answer did you get?", silently losing the relationship to the previous
    problem. advance_episode now recognises MATH_FOLLOWUP and routes it
    through _advance_math_followup, which re-resolves the problem and opens
    a connected follow-up episode via controller.start_followup."""
    print("F1. MATH_FOLLOWUP during an open episode recomputes the problem")

    class _Resolution:
        mode = "MATH_FOLLOWUP"
        resolved_question = "245 + 150"
        retrieval_query = "245 + 150"
        use_rag = False
        use_verifier = True
        changed = True

    chat = _new_chat(_math_episode(attempts=0, computed_answer="381"))
    chat["episode"]["state"].question = "245 + 136"

    with _Patch(app, "record_feedback", lambda *a, **kw: None), \
         _Patch(pipeline, "resolve_conversation", lambda *a, **kw: _Resolution()), \
         _Patch(pipeline, "compute_trusted_answer", lambda *a, **kw: ("395", True)), \
         _Patch(pipeline, "generate_turn",
               lambda *a, **kw: _FakeStream("245 + 150 is like your last problem, "
                                           "but with 150 instead of 136. Try it!")):
        reply = app.submit_turn(chat, "what if it was 150 instead of 136?",
                                3, "on_track", [])

    state = chat["episode"]["state"]
    check("the episode's question is updated to the NEW problem",
         state.question == "245 + 150")
    check("the trusted answer is RECOMPUTED for the new problem, not reused",
         state.computed_answer == "395")
    check("attempts/hints reset for the new sub-episode (a fresh problem, "
         "not a continuation of the old attempt count)",
         state.attempts == 0 and state.hints_given == 0)
    check("the reply is a normal teaching turn, NOT 'what answer did you "
         "get?' (the old misroute through ATTEMPT/diagnose())",
         reply.get("mode") == "teach_invite")


def test_math_followup_falls_back_safely_on_low_confidence() -> None:
    """If a second, heavier look (conversation_resolver) disagrees with the
    cheap classifier's MATH_FOLLOWUP guess, the turn must not be dropped or
    guess a fabricated new problem -- it falls back to grading it as a plain
    attempt against the CURRENT problem."""
    print("F2. MATH_FOLLOWUP that resolver demotes falls back to ATTEMPT, not silently dropped")

    class _FragmentResolution:
        mode = "FRAGMENT"
        resolved_question = "what about 5"
        retrieval_query = ""
        use_rag = False
        use_verifier = False
        changed = False

    chat = _new_chat(_math_episode(attempts=0, computed_answer="56"))
    with _Patch(app, "record_feedback", lambda *a, **kw: None), \
         _Patch(pipeline, "resolve_conversation", lambda *a, **kw: _FragmentResolution()), \
         _Patch(pipeline, "generate_turn",
               lambda *a, **kw: _FakeStream("Let's check your working.")):
        reply = app.submit_turn(chat, "what about 5", 3, "on_track", [],
                                forced_intent=None)
    check("falls back to grading against the CURRENT (unchanged) problem",
         chat["episode"]["state"].question == "What is 7 times 8?")
    check("a reply is produced, not dropped", isinstance(reply, dict))


def test_confusion_correction_clarify_do_not_mutate_state() -> None:
    """Problem 3/4: CONFUSION/CORRECTION/CLARIFY are generation-only -- they
    must not consume a hint, count an attempt, or end the episode, since
    none of them are the child answering, asking for the next hint rung, or
    giving up."""
    print("F3. CONFUSION/CORRECTION/CLARIFY never mutate attempts/hints/phase")

    for label, mode in (("CONFUSION", C.MODE_CONFUSION),
                        ("CORRECTION", C.MODE_CORRECTION),
                        ("CLARIFY", C.MODE_CLARIFY)):
        chat = _new_chat(_math_episode(attempts=0, computed_answer="56"))
        pre = chat["episode"]["state"]
        with _Patch(app, "record_feedback", lambda *a, **kw: None), \
             _Patch(pipeline, "generate_turn",
                   lambda *a, **kw: _FakeStream("Let's look at that together.")):
            reply = app.submit_turn(chat, "huh?", 3, "on_track", [],
                                    forced_intent=label)
        post = chat["episode"]["state"]
        check(f"{label}: mode is {mode}", reply.get("mode") == mode)
        check(f"{label}: hints_given unchanged", post.hints_given == pre.hints_given)
        check(f"{label}: attempts unchanged", post.attempts == pre.attempts)
        check(f"{label}: episode not terminal", not reply.get("terminal"))
        check(f"{label}: not recorded as a graded attempt (record_feedback not "
             "reached for this mode)", reply.get("outcome") is None)


def test_confusion_correction_clarify_skip_retrieval() -> None:
    """Problem 11: a conversational-repair turn on an open episode must not
    trigger a fresh (and likely garbage) retrieval query -- it reuses the
    episode's existing chunks, exactly like HINT/ATTEMPT turns already do."""
    print("F4. CONFUSION/CORRECTION/CLARIFY never call retrieval")

    calls = []

    def _tracking_retrieve(*a, **kw):
        calls.append((a, kw))
        return []

    chat = _new_chat(_math_episode(attempts=0, computed_answer="56"))
    with _Patch(app, "record_feedback", lambda *a, **kw: None), \
         _Patch(pipeline, "generate_turn",
               lambda *a, **kw: _FakeStream("Let's look at that together.")):
        import scripts.retrieval as retrieval_mod
        with _Patch(retrieval_mod, "retrieve_with_metadata", _tracking_retrieve):
            app.submit_turn(chat, "I dont understand", 3, "on_track", [],
                            forced_intent="CONFUSION")
    check("no retrieval call was made for a CONFUSION turn", calls == [])


# ------------------------------------------------------- G: clear chat vs reset
def test_clear_chat_preserves_learner_profile() -> None:
    """Problem 5: clearing a chat window must never erase the persistent
    student_tracker profile -- only an explicit, separate reset action
    (reset_learning_progress) may do that."""
    print("G. clear_chat vs reset_learning_progress")

    reset_calls = []
    with _Patch(app, "reset_student", lambda: reset_calls.append(1)):
        chat = _new_chat(_math_episode(attempts=1))
        chat["messages"] = [{"role": "user", "text": "hi"}]
        chat["thread_notes"] = ["asked \"hi\" · solved it"]
        app.clear_chat(chat)
        check("messages cleared", chat["messages"] == [])
        check("episode cleared", chat["episode"] is None)
        check("thread_notes cleared", chat["thread_notes"] == [])
        check("clear_chat NEVER calls reset_student (the fixed bug)",
             reset_calls == [])

        app.reset_learning_progress()
        check("reset_learning_progress DOES call reset_student "
             "(the separate, explicit destructive action)",
             reset_calls == [1])


def test_current_learner_level_uses_real_backend_classification() -> None:
    """Problem 6: the UI's honest 'Tutor Level' row must forward to the same
    resolver the live pipeline itself uses (pipeline.resolve_level), not a
    separate ad hoc computation, so it can never drift from the number that
    actually shapes tutoring depth."""
    print("H. _current_learner_level forwards to pipeline.resolve_level")

    with _Patch(pipeline, "resolve_level", lambda sid, lvl: "advanced"):
        check("forwards to pipeline.resolve_level",
             app._current_learner_level() == "advanced")


# --------------------------------------------------------------- I: thread_notes memory
def test_thread_notes_populated_on_terminal_action() -> None:
    """Problem 8: a finished episode must leave a thread note behind so the
    NEXT episode in the same chat has continuity -- previously thread_notes
    was defined in scripts/llm/memory.py and consumed by prompt_registry, but
    no live caller in frontend/app.py ever populated or passed it (confirmed
    by a repo-wide grep before this fix), so it was dead in practice despite
    being fully implemented."""
    print("I. _apply_action populates chat['thread_notes'] on a terminal action")

    chat = _new_chat(_math_episode(attempts=0, computed_answer="56"))
    chat["thread_notes"] = []
    correct_action = C.Action(C.MODE_DIAGNOSE_CORRECT, "", outcome="solved",
                              terminal=True)
    with _Patch(app, "record_feedback", lambda *a, **kw: None):
        reply = app._apply_action(chat, chat["episode"], correct_action, [])
    check("a terminal action with real text adds exactly one thread note",
         len(chat["thread_notes"]) == 1)
    check("the note mentions the episode's question",
         "7 times 8" in chat["thread_notes"][0])

    captured = {}

    def _capture_thread_notes(state, action, chunks=None, thread_notes=None,
                              active_turns=None, previous_hints=None):
        captured["thread_notes"] = thread_notes
        return _FakeStream("Nice!")

    chat2 = _new_chat(_math_episode(attempts=0, computed_answer="56"))
    chat2["thread_notes"] = ["asked \"What is 3 x 3?\" · solved it"]
    with _Patch(app, "record_feedback", lambda *a, **kw: None), \
         _Patch(pipeline, "generate_turn", _capture_thread_notes):
        app._apply_action(chat2, chat2["episode"], correct_action, [])
    check("an existing thread note is actually forwarded into generate_turn "
         "(not just stored and never read)",
         captured.get("thread_notes") == ["asked \"What is 3 x 3?\" · solved it"])


# -------------------------------------------------- J: numeric self-consistency guardrail
def test_self_consistency_guardrail_surfaces_but_does_not_block() -> None:
    """Problem 10: modes that let the model invent its OWN illustrative
    numbers (teach_invite, redirect, hints, ...) are not covered by the
    trusted-answer check at all. check_self_consistency is a bounded,
    non-blocking guardrail: it flags an internally-inconsistent equation the
    model wrote itself, without gating or regenerating the reply."""
    print("J. verifier.check_self_consistency + _apply_action wiring")

    ok = verifier.check_self_consistency("First, 4 + 4 = 8, then 8 + 4 = 12.")
    check("internally consistent equations -> no issues", ok == [])

    bad = verifier.check_self_consistency("Well, 7 + 5 = 13, so write 3 carry 1.")
    check("an inconsistent self-chosen equation is caught",
         len(bad) == 1 and bad[0]["computed"] == "12" and bad[0]["stated"] == "13")

    chat = _new_chat(_math_episode(attempts=0, computed_answer=None))
    chat["episode"]["state"].is_math = False
    teach_action = C.Action(C.MODE_TEACH_INVITE, "", buttons=[])
    with _Patch(app, "record_feedback", lambda *a, **kw: None), \
         _Patch(pipeline, "generate_turn",
               lambda *a, **kw: _FakeStream("For example, 6 + 6 = 13.")):
        reply = app._apply_action(chat, chat["episode"], teach_action, [])
    check("a bad self-made example on an UNVERIFIED mode (teach_invite) is "
         "still caught by the bounded guardrail",
         len(reply["self_check_issues"]) == 1)
    check("the reply still goes through -- this is a warning, not a block",
         reply["text"] == "For example, 6 + 6 = 13.")


# ------------------------------------------------ K: legacy path isolation (Problem 12)
def test_live_app_never_calls_legacy_tier_a_path() -> None:
    """Problem 12: frontend/app.py (the live student-facing path) must never
    call the superseded Tier A single-shot functions (TutorTurn/prepare/
    resume/ask_tutor) -- those are retained only for
    scripts/llm/smoke_live.py, marked LEGACY in pipeline.py's own
    docstrings. A regression here would mean a future edit accidentally
    reintroduced a call to dead code that bypasses the controller entirely."""
    print("K. frontend/app.py never reaches the legacy Tier A entry points")

    src = open(app.__file__, encoding="utf-8").read()
    for symbol in ("pipeline.prepare(", "pipeline.resume(",
                  "pipeline.ask_tutor(", "pipeline.TutorTurn("):
        check(f"app.py does not call {symbol}", symbol not in src)


def test_episode_scoped_active_turns_excludes_prior_episode() -> None:
    """Track 1 (stale-problem/stale-operand regression): a finished episode's
    full transcript must never be replayed into a LATER episode's generation
    context, even though both live in the same chat and the UI-level
    active_turns (built from the whole chat, for conversation_resolver's
    benefit) legitimately does include it. Reproduces the shape of the live
    bug (an earlier problem's numbers surfacing in a later problem's
    co-solve) generically, with two different arithmetic problems, not by
    special-casing any one example."""
    print("L. generation context is scoped to the CURRENT episode, not the whole chat")

    chat = _new_chat(episode=None)
    captured = []

    def _capture_generate_turn(state, action, chunks=None, thread_notes=None,
                               active_turns=None, previous_hints=None):
        captured.append(list(active_turns or []))
        return _FakeStream(f"reply about {state.question}")

    def _resolution_for(q):
        class _R:
            resolved_question = q
            retrieval_query = q
            use_rag = False
            use_verifier = False
        return _R()

    with _Patch(app, "record_feedback", lambda *a, **kw: None), \
         _Patch(pipeline, "resolve_level", lambda *a, **kw: "intermediate"), \
         _Patch(pipeline, "generate_turn", _capture_generate_turn):

        # Episode 1: the first-ever turn in a brand new chat.
        with _Patch(pipeline, "resolve_conversation", lambda *a, **kw: _resolution_for("3 + 2")):
            active_turns = app.build_active_turns(chat["messages"])
            chat["messages"].append({"role": "user", "text": "3 + 2"})
            chat["messages"].append(app.submit_turn(chat, "3 + 2", 3, "on_track", active_turns))
        check("episode 1's own first turn sees no prior turns", captured[-1] == [])

        # Close episode 1 out (as a real terminal action would) so the next
        # turn opens a fresh, unrelated episode in the SAME chat. `terminal`
        # is a read-only property derived from `phase`, so drive it via phase.
        chat["episode"]["state"].phase = C.SOLVED

        # Episode 2: a different, unrelated problem, same chat/session.
        with _Patch(pipeline, "resolve_conversation", lambda *a, **kw: _resolution_for("8 + 9")):
            active_turns = app.build_active_turns(chat["messages"])
            chat["messages"].append({"role": "user", "text": "8 + 9"})
            chat["messages"].append(app.submit_turn(chat, "8 + 9", 3, "on_track", active_turns))
        check("the UI-level active_turns passed in DOES span the whole chat "
             "(unaffected -- conversation_resolver still sees full history)",
             len(active_turns) == 2)
        check("but episode 2's OWN first-turn generation context excludes "
             "episode 1's transcript entirely",
             captured[-1] == [])

        # A follow-up turn within episode 2 (its second turn).
        with _Patch(pipeline, "resolve_conversation", lambda *a, **kw: _resolution_for("8 + 9")):
            active_turns = app.build_active_turns(chat["messages"])
            chat["messages"].append({"role": "user", "text": "8+9=7"})
            chat["messages"].append(app.submit_turn(chat, "8+9=7", 3, "on_track", active_turns,
                                                     forced_intent="ATTEMPT"))
        check("a later turn in episode 2 sees episode 2's own prior turn only",
             len(captured[-1]) == 2 and captured[-1][0]["content"] == "8 + 9")
        check("episode 1's question never leaks into episode 2's generation context",
             not any("3 + 2" in str(t.get("content", "")) for t in captured[-1]))


def test_input_safety_runs_before_any_llm_routing() -> None:
    """Track 5: an unsafe turn must never reach conversation_resolver or
    intent.classify_intent -- both of those are themselves LLM calls, so
    checking safety AFTER them would mean an unsafe message already went to
    a model. Proven here by making both raise if called at all, not just by
    checking the final reply shape."""
    print("M. input safety gate runs before conversation_resolver/intent are ever touched")

    from scripts.llm import intent as intent_mod

    def _must_not_be_called(*a, **kw):
        raise AssertionError("LLM-based routing was reached for an unsafe input")

    chat = _new_chat(episode=None)
    with _Patch(pipeline, "resolve_conversation", _must_not_be_called), \
         _Patch(intent_mod, "classify_intent", _must_not_be_called):
        reply = app.submit_turn(chat, "I want to kill myself", 3, "on_track", [])
    check("unsafe input never reaches conversation_resolver/intent (no exception bubbled up)",
         isinstance(reply, dict))
    check("blocked reply is tagged safety_blocked, not a normal tutoring mode",
         reply.get("mode") == "safety_blocked")
    check("the episode is left completely untouched (no episode silently started)",
         chat["episode"] is None)
    check("the safety decision is recorded on the reply",
         reply.get("safety") == {"input_checked": True, "input_blocked": True,
                                 "input_category": "self_harm",
                                 "output_checked": False, "output_blocked": False})

    # Safe input is unaffected and still reaches the real routing/generation.
    chat2 = _new_chat(episode=None)

    class _Resolution:
        resolved_question = "What is 2 + 2?"
        retrieval_query = "What is 2 + 2?"
        use_rag = False
        use_verifier = False

    with _Patch(app, "record_feedback", lambda *a, **kw: None), \
         _Patch(pipeline, "resolve_level", lambda *a, **kw: "intermediate"), \
         _Patch(pipeline, "resolve_conversation", lambda *a, **kw: _Resolution()), \
         _Patch(pipeline, "generate_turn", lambda *a, **kw: _FakeStream("Let's add 2 and 2!")):
        safe_reply = app.submit_turn(chat2, "What is 2 + 2?", 3, "on_track", [])
    check("safe input reaches real generation (not blocked)",
         safe_reply.get("mode") != "safety_blocked" and chat2["episode"] is not None)
    check("the safety block records input_checked/input_blocked=False and "
         "output_checked=True for a normal turn",
         safe_reply.get("safety", {}).get("input_checked") is True
         and safe_reply.get("safety", {}).get("input_blocked") is False
         and safe_reply.get("safety", {}).get("output_checked") is True)


def test_output_safety_blocks_unsafe_generated_text() -> None:
    """Track 5: a bounded defense-in-depth scan of the model's OWN generated
    text, independent of the input check above (the input here is ordinary
    and safe; only the model's output is unsafe)."""
    print("N. output safety gate blocks an unsafe generated reply before it is rendered")

    chat = _new_chat(_math_episode(attempts=0, computed_answer="56"))
    teach_action = C.Action(C.MODE_DIAGNOSE_WRONG, "", buttons=[])
    with _Patch(app, "record_feedback", lambda *a, **kw: None), \
         _Patch(pipeline, "generate_turn",
               lambda *a, **kw: _FakeStream("Just go kill yourself if you can't do this.")):
        reply = app._apply_action(chat, chat["episode"], teach_action, [])
    check("the unsafe generated text is never shown to the child",
         "kill" not in reply["text"])
    check("a safe, generic fallback is shown instead",
         reply["text"] == safety.check_output(
             "Just go kill yourself if you can't do this.").fallback_text)
    check("the reply records that output safety blocked this turn",
         reply.get("safety", {}).get("output_blocked") is True)


def test_interaction_telemetry_reconstructs_the_turn() -> None:
    """Track 6: one structured interaction_events record per student turn,
    distinct from common.log_run's per-generation-call log, sufficient to
    answer "what happened to this turn" (controller mode, safety decisions,
    verify outcome) without duplicating the raw prompt transcript."""
    print("O. structured interaction telemetry is actually written per turn")

    from scripts.llm import telemetry

    captured = []
    with _Patch(telemetry, "log_interaction", lambda **kw: captured.append(kw)):
        chat = _new_chat(_math_episode(attempts=0, computed_answer="56"))
        correct_action = C.Action(C.MODE_DIAGNOSE_CORRECT, "", outcome="solved", terminal=True)
        with _Patch(app, "record_feedback", lambda *a, **kw: None), \
             _Patch(pipeline, "generate_turn", lambda *a, **kw: _FakeStream("Nice!")):
            app._apply_action(chat, chat["episode"], correct_action, [])
        check("a normal turn logs exactly one interaction event", len(captured) == 1)
        check("the event records the controller mode and outcome",
             captured[0]["controller_mode"] == "diagnose_correct"
             and captured[0]["outcome"] == "solved")
        check("the event records that both safety checks ran and passed",
             captured[0]["input_safety"] == {"checked": True, "blocked": False}
             and captured[0]["output_safety"]["checked"] is True
             and captured[0]["output_safety"]["blocked"] is False)

        captured.clear()
        chat2 = _new_chat(episode=None)
        app.submit_turn(chat2, "I want to kill myself", 3, "on_track", [])
        check("a safety-blocked turn ALSO logs exactly one interaction event",
             len(captured) == 1)
        check("the blocked event records the input-safety category, with no "
             "controller mode (the controller was never reached)",
             captured[0]["input_safety"]["blocked"] is True
             and captured[0]["input_safety"]["category"] == "self_harm"
             and captured[0]["controller_mode"] == "safety_blocked")


def main() -> None:
    test_generation_failure_rolls_back_state()
    test_hint_lifecycle_integration()
    test_empty_generation_treated_as_failure()
    test_start_episode_does_not_commit_on_failure()
    test_practice_problem_shortcut_disabled()
    test_attempt_recording_semantics()
    test_public_api_wrappers()
    test_post_check_paths()
    test_conceptual_episode_never_advances()
    test_math_followup_preserves_relationship()
    test_math_followup_falls_back_safely_on_low_confidence()
    test_confusion_correction_clarify_do_not_mutate_state()
    test_confusion_correction_clarify_skip_retrieval()
    test_clear_chat_preserves_learner_profile()
    test_current_learner_level_uses_real_backend_classification()
    test_thread_notes_populated_on_terminal_action()
    test_self_consistency_guardrail_surfaces_but_does_not_block()
    test_live_app_never_calls_legacy_tier_a_path()
    test_episode_scoped_active_turns_excludes_prior_episode()
    test_input_safety_runs_before_any_llm_routing()
    test_output_safety_blocks_unsafe_generated_text()
    test_interaction_telemetry_reconstructs_the_turn()
    print(f"\n{_passed} passed, {_failed} failed")
    if _failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
