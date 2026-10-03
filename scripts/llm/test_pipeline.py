"""Offline tests for the backend pieces that don't need network or ChromaDB.

Run:  python -m scripts.llm.test_pipeline
These cover the deterministic surface: number parsing, the sympy verifier
(with an injected extractor so no LLM is called), fallback ordering in the
client, hint prompt shaping, and the level mapping. The live round-trip
(Groq + ChromaDB) is exercised separately on a machine with keys/index.
"""
from __future__ import annotations

from . import hints, llm_client, pipeline, response_parser, student_tracker, verifier

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


# --------------------------------------------------------------- response_parser
def test_response_parser() -> None:
    print("response_parser")
    check("answer line, last wins",
          response_parser.extract_answer("Answer: 7\nmore\nAnswer: 42") == "42")
    check("answer with star/bold",
          response_parser.extract_answer("**Answer:** 12 apples") == "12 apples")
    check("no answer line", response_parser.extract_answer("just text") is None)
    check("fraction preferred", response_parser.extract_number_str("about 3/4 done") == "3/4")
    check("fraction whitespace collapsed",
          response_parser.extract_number_str("3 / 4") == "3/4")
    check("decimal", response_parser.extract_number_str("it is 1.8 metres") == "1.8")
    check("integer in words", response_parser.extract_number_str("So 27 + 15 = 42.") == "27")
    check("final_number_str uses answer line",
          response_parser.final_number_str("steps 2+3\nAnswer: 5") == "5")
    check("refusal detected", response_parser.is_refusal("Let's ask your teacher about this one!"))


# ------------------------------------------- response_parser.final_number_str tiers
def test_final_number_str_fallback_tiers() -> None:
    """Regression tests for the confidence-tiered fallback (see
    response_parser.py's module docstring and final_number_str's docstring).
    Added when the fallback was changed from 'first number in the whole
    text' (wrong: grabs an early input number) to this tiered approach.
    Cases ex-009/ex-010 motivated the fix but these tests exercise the
    general design, not just those two literal strings."""
    print("response_parser.final_number_str — confidence-tiered fallback")
    fns = response_parser.final_number_str

    # Tier 1: explicit "Answer:" line, including bold/star formatting.
    check("explicit Answer: line",
          fns("some steps\nAnswer: 42") == "42")
    check("explicit **Answer:** line (bold)",
          fns("some steps\n**Answer:** 42") == "42")
    check("Answer: line wins even with other numbers earlier",
          fns("We started with 3 groups of 4.\nAnswer: 12") == "12")

    # Tier 2: last "= value" / "equals value" statement, final answer buried
    # in prose with no Answer: line and multiple intermediate values.
    check("final answer in prose via last equation (ex-009-style)",
          fns("We have 3 groups, and each group has 4 apples. "
             "4 + 4 = 8, then 8 + 4 = 12. So 3 times 4 is 12.") == "12")
    check("final answer in prose, single equation (ex-010-style)",
          fns("Let's add these two numbers. 27 + 15 = 42. "
             "So the answer is 42 toffees.") == "42")
    check("multiple intermediate equations -> LAST one wins",
          fns("Add the ones: 7 + 5 = 12, write 2 carry 1. "
             "Add the tens: 2 + 1 + 1 = 4.") == "4")
    check("'equals' spelled out, not just '='",
          fns("Nine times six equals 54.") == "54")
    check("trailing follow-up suggestion AFTER the answer is not picked up",
          fns("Well done! 9 times 6 equals 54. Would you like to try a "
             "little tougher one, like 8 times 7, or would you prefer "
             "to explore a new topic?") == "54")
    check("fraction as an equation result",
          fns("First we simplify 2/4 = 1/2. Then 1/2 + 1/4 = 3/4.") == "3/4")
    check("negative equation result",
          fns("5 minus 8 = -3.") == "-3")

    # Tier 3: no Answer: line, no equation -- sole number by elimination.
    check("single bare number, no structure -> accepted by elimination",
          fns("I think it's 7.") == "7")
    check("single bare fraction, no structure -> accepted by elimination",
          fns("I think it's 3/4.") == "3/4")

    # Ambiguous: multiple bare numbers, no Answer:/equation to disambiguate
    # -> None (unverifiable), not a guess.
    check("multiple bare numbers with no structure -> ambiguous, None",
          fns("I have 3 apples and my friend has 4 apples.") is None)

    # Missing / no number at all.
    check("no number anywhere -> None",
          fns("Let's think about this together.") is None)
    check("empty string -> None", fns("") is None)
    check("None input -> None", fns(None) is None)

    # Contradictory: two different Answer: lines -> last one wins (existing
    # extract_answer behaviour, re-asserted here through final_number_str).
    check("contradictory Answer: lines -> last wins",
          fns("First attempt.\nAnswer: 10\nActually let me redo that.\n"
             "Answer: 12") == "12")

    # Malformed: an "=" with no usable number after it must not crash or
    # fabricate a value; should fall through to the next tier instead.
    check("malformed equation (nothing numeric after '=') falls through safely",
          fns("This equals something unclear, but 9 works.") == "9")

    # Irrelevant numbers mixed with a clear equation result.
    check("irrelevant numbers (dates/counts) do not override the equation result",
          fns("On day 3 of 5, we calculated 6 + 6 = 12 toffees in total.") == "12")


# --------------------------------------------------------------- verifier maths
def test_verifier_math() -> None:
    print("verifier — sympy eval + safety")
    check("addition", str(verifier._safe_eval("2 + 3")) == "5")
    check("fraction sum", str(verifier._safe_eval("1/2 + 1/4")) == "3/4")
    check("parens/mult", str(verifier._safe_eval("(1/2) * 8")) == "4")
    check("reject letters", verifier._safe_eval("sqrt(2)") is None)
    check("reject dunder", verifier._safe_eval("__import__('os')") is None)
    check("reject symbol", verifier._safe_eval("x + 1") is None)
    check("close exact", verifier._close(verifier._safe_eval("3/4"),
                                         verifier._safe_eval("0.75")))
    check("close reject", not verifier._close(verifier._safe_eval("5"),
                                              verifier._safe_eval("6")))


# ------------------------------------------------------- verifier check (no LLM)
def test_verifier_check() -> None:
    print("verifier — check() with injected extractor")

    # A computable question the model answered correctly.
    out_ok = "Add the ones and tens.\nAnswer: 42"
    r = verifier.check("How do I add 27 and 15?", out_ok,
                       extract_fn=lambda q: "27 + 15")
    check("correct -> match True", r["verifiable"] and r["match"] is True)

    # Model got the number wrong.
    r = verifier.check("What is 7 times 8?", "Answer: 54",
                       extract_fn=lambda q: "7 * 8")
    check("wrong -> match False", r["verifiable"] and r["match"] is False)

    # Conceptual question: extractor says NONE.
    r = verifier.check("What is a fraction?", "A fraction is part of a whole.",
                       extract_fn=lambda q: "NONE")
    check("conceptual -> not verifiable", r["verifiable"] is False and r["match"] is None)

    # Computable, but the answer states no number.
    r = verifier.check("What is 2 + 3?", "Let's think about it together.",
                       extract_fn=lambda q: "2 + 3")
    check("no number -> match None", r["verifiable"] and r["match"] is None)

    # Refusal short-circuits before any extraction.
    called = {"n": 0}

    def counting_extractor(q):
        called["n"] += 1
        return "2 + 3"

    r = verifier.check("What is the square root of 144?",
                       "Let's ask your teacher about this one!",
                       extract_fn=counting_extractor)
    check("refusal -> skipped, extractor not called",
          r["verifiable"] is False and called["n"] == 0)


# --------------------------------------------------------------- client fallback
class _FakeChunk:
    def __init__(self, content=None, finish=None):
        self.choices = [type("C", (), {
            "delta": type("D", (), {"content": content})(),
            "finish_reason": finish,
        })()]


class _FakeCompletions:
    def __init__(self, behaviour):
        self._behaviour = behaviour

    def create(self, model, messages, stream, **params):
        return self._behaviour(model)


class _FakeClient:
    def __init__(self, behaviour):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(behaviour)})()


def test_client_fallback(monkeypatched=True) -> None:
    print("llm_client — fallback ordering")

    calls = []

    def behaviour(model):
        calls.append(model)
        if "groq" in model.lower() or model == llm_client.DEFAULT_MODEL:
            # primary raises BEFORE yielding anything -> should fall through
            raise RuntimeError("primary down")
        # fallback streams two tokens then finishes
        def gen():
            yield _FakeChunk("Hel")
            yield _FakeChunk("lo", finish="stop")
        return gen()

    # Point every target at our fake client, regardless of missing keys.
    orig = llm_client._client_for
    llm_client._client_for = lambda target: _FakeClient(behaviour)
    try:
        h = llm_client.StreamHandle()
        text = "".join(llm_client.stream([{"role": "user", "content": "hi"}], handle=h))
    finally:
        llm_client._client_for = orig

    check("primary tried first", calls and ("groq" in calls[0].lower()
                                            or calls[0] == llm_client.DEFAULT_MODEL))
    check("fell back to second target", len(calls) >= 2)
    check("streamed text assembled", text == "Hello")
    check("handle committed to fallback", h.ok and h.provider == "hf-nscale")


def test_client_skips_missing_keys() -> None:
    print("llm_client — missing keys skipped")
    orig = llm_client._client_for
    llm_client._client_for = lambda target: None  # all keys "missing"
    try:
        h = llm_client.StreamHandle()
        list(llm_client.stream([{"role": "user", "content": "hi"}], handle=h))
    finally:
        llm_client._client_for = orig
    check("no key -> not ok", not h.ok)
    check("attempts recorded", len(h.attempts) == 3 and all("skipped" in a for a in h.attempts))


# --------------------------------------------------------------- hints + levels
def test_hints_and_levels() -> None:
    print("hints + level mapping")

    captured = {}

    def fake_chat(messages, params=None):
        captured["messages"] = messages
        return {"text": "Think about equal groups.", "ok": True}

    hint = hints.generate_hint("What is 3 x 4?", 3, ["mult is repeated add"],
                               "beginner", 2, previous_hints=["think groups"],
                               chat_fn=fake_chat)
    check("hint returned", hint == "Think about equal groups.")
    sys_msg = captured["messages"][0]["content"]
    user_msg = captured["messages"][1]["content"]
    check("hint system has grade", "Class 3" in sys_msg)
    check("hint user has prior hints", "think groups" in user_msg)
    # This call is hint 2 of the default total_hints=3, i.e. a MIDDLE hint, not
    # the LAST or SINGLE case — so it must use hints._GUIDANCE_MIDDLE's wording
    # ("...one real step closer..."), not "first concrete step" (that phrase is
    # unique to _GUIDANCE_SINGLE, for problems with only one hint total, and
    # never appears when total_hints=3). The previous assertion checked for
    # the wrong guidance tier's wording and would fail even though hints.py's
    # step-scaled guidance (_guidance_for) is working correctly.
    check("hint level-2 (of 3) uses middle-tier escalating guidance, not first/last/single wording",
          "one real step closer" in user_msg)

    check("map needs_practice", pipeline._norm_level("needs_practice") == "beginner")
    check("map on_track", pipeline._norm_level("on_track") == "intermediate")
    check("map ahead", pipeline._norm_level("ahead") == "advanced")
    check("passthrough backend level", pipeline._norm_level("advanced") == "advanced")
    check("default level", pipeline._norm_level(None) == "intermediate")

    src = pipeline._make_source([{"grade": 4, "page": 12, "topic": "Fractions"}])
    check("source built", "NCERT Class 4" in src and "p.12" in src)


def test_student_tracker_atomic_save() -> None:
    """Regression test for the atomic-write fix in student_tracker._save():
    uses a temp STORE path so the real data/students.json is never touched."""
    print("student_tracker — atomic save")
    import os
    import tempfile

    orig_store = student_tracker.STORE
    tmpdir = tempfile.mkdtemp()
    student_tracker.STORE = os.path.join(tmpdir, "students.json")
    try:
        student_tracker.record("test_student", topic="fractions", correct=True)
        student_tracker.record("test_student", topic="fractions", correct=False)
        stats = student_tracker.stats("test_student")
        check("attempts recorded", stats["attempts"] == 2)
        check("no leftover .tmp file after save",
              not os.path.exists(student_tracker.STORE + ".tmp"))
        import json
        with open(student_tracker.STORE, encoding="utf-8") as f:
            reloaded = json.load(f)
        check("saved file is valid, re-loadable JSON",
              reloaded["test_student"]["attempts"] == 2)
    finally:
        student_tracker.STORE = orig_store


def main() -> None:
    test_response_parser()
    test_final_number_str_fallback_tiers()
    test_student_tracker_atomic_save()
    test_verifier_math()
    test_verifier_check()
    test_client_fallback()
    test_client_skips_missing_keys()
    test_hints_and_levels()
    print(f"\n{_passed} passed, {_failed} failed")
    if _failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
