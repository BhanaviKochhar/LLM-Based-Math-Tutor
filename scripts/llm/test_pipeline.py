"""Offline tests for the backend pieces that don't need network or ChromaDB.

Run:  python -m scripts.llm.test_pipeline
These cover the deterministic surface: number parsing, the sympy verifier
(with an injected extractor so no LLM is called), fallback ordering in the
client, hint prompt shaping, and the level mapping. The live round-trip
(Groq + ChromaDB) is exercised separately on a machine with keys/index.
"""
from __future__ import annotations

from . import hints, llm_client, pipeline, response_parser, verifier

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
    check("hint level-2 guidance present", "first concrete step" in user_msg)

    check("map needs_practice", pipeline._norm_level("needs_practice") == "beginner")
    check("map on_track", pipeline._norm_level("on_track") == "intermediate")
    check("map ahead", pipeline._norm_level("ahead") == "advanced")
    check("passthrough backend level", pipeline._norm_level("advanced") == "advanced")
    check("default level", pipeline._norm_level(None) == "intermediate")

    src = pipeline._make_source([{"grade": 4, "page": 12, "topic": "Fractions"}])
    check("source built", "NCERT Class 4" in src and "p.12" in src)


def main() -> None:
    test_response_parser()
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
