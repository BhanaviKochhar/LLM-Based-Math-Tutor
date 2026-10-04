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

from scripts.llm import controller as C, hints, pipeline, verifier
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
    with _Patch(pipeline, "_resolve_question", lambda q, at: calls.append(("resolve", q, at)) or "R"):
        result = pipeline.resolve_conversation("q", None)
    check("resolve_conversation forwards to the resolver", calls == [("resolve", "q", None)] and result == "R")

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
    print(f"\n{_passed} passed, {_failed} failed")
    if _failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
