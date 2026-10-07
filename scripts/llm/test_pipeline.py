"""Offline tests for the backend pieces that don't need network or ChromaDB.

Run:  python -m scripts.llm.test_pipeline
These cover the deterministic surface: number parsing, the sympy verifier
(with an injected extractor so no LLM is called), fallback ordering in the
client, hint prompt shaping, and the level mapping. The live round-trip
(Groq + ChromaDB) is exercised separately on a machine with keys/index.
"""
from __future__ import annotations

from . import (conversation_resolver, hints, intent, llm_client, pipeline,
              prompt_registry, response_parser, safety, student_tracker,
              topics, verifier)

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

    # Mixed numbers: a bare fraction match alone would silently drop the
    # whole-number part ("1 1/2" -> "1/2", losing a whole unit). Realistic
    # whenever a grade 4-5 fraction result exceeds 1.
    check("mixed number on an Answer: line -> combined into one improper fraction",
          fns("Answer: 1 1/2") == "3/2")
    check("negative mixed number",
          fns("Answer: -1 1/2") == "-3/2")
    check("mixed number via a trailing equation, no Answer: line",
          fns("So the total is = 1 1/2 cakes.") == "3/2")

    # Comma-grouped large integers (Western "1,234" or Indian "1,00,000"):
    # the plain-integer token alone would stop at the first comma. Realistic
    # for grade 4-5 "numbers up to 100,000" content.
    check("comma-grouped integer on an Answer: line",
          fns("Answer: 1,234") == "1234")
    check("Indian comma grouping on an Answer: line",
          fns("Answer: 1,00,000") == "100000")
    check("comma-grouped integer via a trailing equation",
          fns("So the total is = 1,234 pages.") == "1234")

    # A natural-language list ("3, 4") must NOT be merged into one number --
    # a real thousands separator never has a space after the comma.
    check("comma-separated list is not mistaken for a grouped integer",
          fns("Ravi has 3, 4 apples left over.") is None)


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

    # Division by zero must never evaluate to a usable value (sympy would
    # otherwise return zoo/nan, which `is_number` but is not a real result).
    check("reject division by zero", verifier._safe_eval("5/0") is None)
    check("reject division by zero, non-bare shape",
          verifier._safe_eval("5/0+3") is None)
    check("reject division by a zero-valued sub-expression",
          verifier._safe_eval("8/(3-3)") is None)


# --------------------------------------------- verifier grade-appropriate gate
def test_verifier_injection_gate() -> None:
    """solve()'s injection gate: integer results and non-integer fraction
    arithmetic are injected; a bare non-exact int/int division is withheld
    so the tutor teaches quotient+remainder instead of an improper fraction
    (see verifier._grade_appropriate_answer). Previously untested by any
    deterministic suite."""
    print("verifier — grade-appropriate injection gate")

    def solve(expr: str):
        return verifier.solve(expr, extract_fn=lambda q: expr)

    check("integer result -> injected",
          solve("6*9-32") == ("22", True))
    check("non-integer fraction arithmetic -> injected (the taught answer)",
          solve("1/2 + 1/4") == ("3/4", True))
    check("bare non-exact int/int division -> withheld (teach remainder)",
          solve("20/3") == (None, True))
    check("non-exact division WRAPPED in redundant parens -> still withheld",
          solve("(20/3)") == (None, True))
    check("non-exact division double-wrapped -> still withheld",
          solve("((20/3))") == (None, True))
    check("a division that ISN'T the whole expression is unaffected",
          solve("(1/2)*8") == ("4", True))
    check("exact division -> injected as an integer",
          solve("36/4") == ("9", True))
    check("division by zero -> not computable at all, never injected",
          solve("5/0") == (None, False))
    check("division by zero (non-bare shape) -> not computable, never injected",
          solve("5/0+3") == (None, False))

    # Fraction-vs-division disambiguation (see verifier._looks_like_fraction_
    # conversion). A bare "int/int" expression is genuinely ambiguous on its
    # own -- the question's own wording is what tells a division word
    # problem apart from a fraction-value/conversion question. Found via
    # component evaluation producing real mismatches on ar-020/cb-158
    # (general phrasing patterns reproduced here, not those literal
    # dataset rows).
    def solve_q(question: str, expr: str):
        return verifier.solve(question, extract_fn=lambda q: expr)

    check("ordinary exact division word problem -> injected as before (unaffected by this fix)",
          solve_q("Share 36 pencils among 4 students. How many each?", "36/4") == ("9", True))
    check("ordinary non-exact division word problem -> still withheld (core remainder "
         "behaviour must survive this fix)",
          solve_q("Share 20 toffees equally among 3 children.", "20/3") == (None, True))
    check("fraction-to-decimal conversion ('written as a decimal') -> now injected, "
         "not withheld",
          solve_q("What is 3/10 written as a decimal?", "3/10") == ("3/10", True))
    check("fraction-to-decimal conversion ('convert ... to a decimal') -> now injected",
          solve_q("Convert 7/20 to a decimal.", "7/20") == ("7/20", True))
    check("plain fraction-simplification question -> now injected",
          solve_q("Simplify the fraction 4/8.", "4/8") == ("1/2", True))
    check("a bare fraction value with no division/decimal wording at all defaults "
         "to the prior withholding behaviour (ambiguous in the student's favour: "
         "conservative, not silently guessed)",
          solve_q("What is 1/3 of 9?", "20/3")[0] is None)

    # KNOWN LIMITATION, documented rather than hidden: this is a wording
    # heuristic, not a semantic one. A genuine division word problem that
    # happens to mention "decimal" in an unrelated sense (e.g. rounding
    # instructions) is misread as a conversion question and gets the
    # fraction injected when it should still be withheld. Narrowing the
    # regex further to exclude this one adversarial phrasing risks new
    # false negatives elsewhere; not attempted here -- see
    # docs/tutoring_fixes_and_limitations.md.
    check("KNOWN LIMITATION: a division word problem that happens to mention "
         "'decimal' in an unrelated sense (rounding instructions) is "
         "incorrectly treated as a conversion question",
          solve_q("Share 45 rupees among 8 people. Round to 2 decimal places if needed.",
                  "45/8") == ("45/8", True))


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


def test_topic_canonicalization() -> None:
    """Track 16: weak_topics must aggregate under a small, fixed set of
    canonical topic names instead of the raw (previously 30-char-truncated)
    question text, which produced an unaggregatable key per differently-
    worded question. Covers both the classifier itself and that
    pipeline.record_feedback actually uses it end to end."""
    print("topics — deterministic canonical classification")

    cases = [
        ("What is 7 times 8?", "Multiplication"),
        ("56 + 27", "Addition & Subtraction"),
        ("add 56 and 27", "Addition & Subtraction"),
        ("What is one-third of 9?", "Fractions & Decimals"),
        ("perimeter of a rectangle", "Perimeter, Area & Volume"),
        ("what are the factors of 12", "Factors & Multiples"),
        ("89/4 explain step by step. div", "Division"),
        ("what time is it", "Time & Calendar"),
        ("how many rupees do I have", "Money"),
        ("6 x 2", "Multiplication"),
    ]
    for q, expected in cases:
        check(f"canonicalize({q!r}) -> {expected!r}", topics.canonicalize(q) == expected)
    check("an un-classifiable fragment returns None, not a guess",
         topics.canonicalize("There are 26 ba") is None)

    import os
    import tempfile

    orig_store = student_tracker.STORE
    tmpdir = tempfile.mkdtemp()
    student_tracker.STORE = os.path.join(tmpdir, "students.json")
    try:
        # Two differently-worded additions should aggregate under the SAME
        # canonical key -- the exact aggregation failure being fixed.
        pipeline.record_feedback("topic_test", "56 + 27", correct=False)
        pipeline.record_feedback("topic_test", "what is 12 plus 9", correct=False)
        stats = student_tracker.stats("topic_test")
        check("both differently-worded wrong attempts aggregate under ONE "
             "canonical topic key, not two separate raw-text keys",
             stats["weak_topics"] == ["Addition & Subtraction"])

        # A question the matcher can't place goes in the honest "Other"
        # bucket, never a fabricated specific topic.
        pipeline.record_feedback("topic_test", "There are 26 ba", correct=False)
        stats2 = student_tracker.stats("topic_test")
        check("an unclassifiable question is bucketed as 'Other', not guessed",
             "Other" in stats2["weak_topics"])
    finally:
        student_tracker.STORE = orig_store


# -------------------------------------------- intent keyword-fallback routing
def test_intent_keyword_fallback() -> None:
    """scripts/llm/intent.py's deterministic keyword fallback
    (_keyword_guess) -- previously had zero test coverage anywhere in this
    project. Regression-tests two generations of the same underlying issue:

    1. (Original fix) "I don't understand" must not resolve to GIVE_UP: a
       confused-but-still-engaged child is not quitting.
    2. (This stabilization pass) Confusion about the tutor's last explanation
       is now its OWN label, CONFUSION, distinct from HINT -- a child who
       says "I don't understand" wants the SAME idea re-explained, not the
       next rung of a hint ladder (see controller._d_confusion and
       intent.py's module docstring). "I cant understand" (no apostrophe)
       used to be a documented, accepted gap that fell through to GIVE_UP;
       it is now folded into the same CONFUSION keyword list and no longer a
       gap.
    """
    print("intent._keyword_guess -- confusion vs hint vs genuine give-up")

    check("'I dont understand' -> CONFUSION, not GIVE_UP or HINT",
         intent._keyword_guess("I dont understand") == "CONFUSION")
    check("\"I don't understand\" (apostrophe) -> CONFUSION",
         intent._keyword_guess("I don't understand this one") == "CONFUSION")
    check("'I dont get it' -> CONFUSION",
         intent._keyword_guess("I dont get it") == "CONFUSION")
    check("'confused' alone -> CONFUSION",
         intent._keyword_guess("wait, I'm confused") == "CONFUSION")
    check("genuine give-up phrasing is still GIVE_UP, unaffected by this fix",
         intent._keyword_guess("I dont know, this is too hard") == "GIVE_UP")
    check("'I cant do it' is still GIVE_UP",
         intent._keyword_guess("i cant do it") == "GIVE_UP")
    check("'I cant understand' (without an apostrophe-don't) now resolves to "
         "CONFUSION -- the previously-documented fallback gap is closed",
         intent._keyword_guess("I cant understand this at all") == "CONFUSION")
    check("an ordinary hint request is still HINT, not CONFUSION (unaffected)",
         intent._keyword_guess("give me a hint please") == "HINT")
    check("a plain SOLVE request is still SOLVE (unaffected)",
         intent._keyword_guess("just show me how") == "SOLVE")
    check("a bare attempt number still falls through to ATTEMPT",
         intent._keyword_guess("42") == "ATTEMPT")
    check("a bare rejection resolves to CORRECTION via the prefilter",
         intent._prefilter("no") == "CORRECTION")
    check("'that's wrong' resolves to CORRECTION via the prefilter",
         intent._prefilter("that's wrong") == "CORRECTION")
    check("CORRECTION is checked before CONFUSION/GIVE_UP in the keyword list",
         intent._keyword_guess("thats wrong") == "CORRECTION")


# ----------------------------------------------------- conversation_resolver
def test_conversation_resolver_deterministic_paths() -> None:
    """Pure, no-LLM-call paths of conversation_resolver.resolve_question:
    the "X instead of Y" grammar rule, the bare-correction regex, the
    no-previous-turn NEW default, and (this stabilization pass) that the
    router's own system prompt is parameterized by the REAL grade instead of
    a hardcoded "Class 3" -- found hardcoded during the architecture audit
    (Problem 1: grade must propagate into conversational routing, not just
    retrieval/verifier/prompt)."""
    print("conversation_resolver — deterministic routing paths")

    prior = [{"role": "user", "content": "What is 245 + 136?"},
             {"role": "assistant", "content": "Let's work through it..."}]

    r = conversation_resolver.resolve_question(
        "what if it was plus 150 instead of 136?", prior)
    check("'X instead of Y' resolves deterministically, no LLM call",
         r.mode == "MATH_FOLLOWUP" and r.resolved_question == "245 + 150"
         and r.confidence == 1.0)

    r_no_prev = conversation_resolver.resolve_question("What is 5 + 5?", None)
    check("no previous turn -> NEW by default, no LLM call",
         r_no_prev.mode == "NEW" and r_no_prev.use_rag and r_no_prev.use_verifier)

    r_correction = conversation_resolver.resolve_question("no", prior)
    check("a bare rejection resolves to CORRECTION deterministically",
         r_correction.mode == "CORRECTION" and not r_correction.use_rag
         and not r_correction.use_verifier)

    r_empty = conversation_resolver.resolve_question("", prior)
    check("empty input -> FRAGMENT, not a crash", r_empty.mode == "FRAGMENT")

    rendered = conversation_resolver._ROUTER_SYSTEM_TEMPLATE.replace("{grade}", "4")
    check("the router's system prompt is parameterized by grade, not "
         "hardcoded to Class 3",
         "Class 4" in rendered and "Class 3" not in rendered)


# ------------------------------------------------- verifier.check_self_consistency
def test_verifier_self_consistency_guardrail() -> None:
    """Bounded guardrail (Problem 10): checks arithmetic the MODEL invents on
    its own (e.g. a worked example in a broad teach_invite/redirect reply),
    independent of whichever mode produced it and independent of the
    student's own trusted answer. Must be conservative -- skip, not flag,
    anything it can't confidently parse."""
    print("verifier — self-consistency guardrail for self-made examples")

    check("a correct self-made equation -> no issues",
         verifier.check_self_consistency("First 4 + 4 = 8, then 8 + 4 = 12.") == [])
    check("no equation at all -> no issues",
         verifier.check_self_consistency("Let's think about this together.") == [])

    bad = verifier.check_self_consistency("So 7 + 5 = 13, write 3 carry 1.")
    check("a wrong self-made equation is caught",
         len(bad) == 1 and bad[0]["computed"] == "12" and bad[0]["stated"] == "13")

    multi = verifier.check_self_consistency(
        "9 - 3 = 6 is correct, but 2 * 2 = 5 is wrong.")
    check("multiple equations are each checked independently",
         len(multi) == 1 and multi[0]["statement"] == "2 * 2 = 5")

    check("the trusted-answer 'Answer:' line format is not mistaken for a "
         "self-made equation (no operator before '=')",
         verifier.check_self_consistency("Answer: 42") == [])


def test_self_consistency_fraction_parsing() -> None:
    """Regression for the false fraction self-check warning: the RHS of an
    equation was matched by an alternation that tried the bare-number form
    BEFORE the fraction form, so "... = 2/4" only captured "2" and silently
    dropped "/4" -- a correct "1/2 = 2/4" was reported as "1/2 = 2", a false
    mismatch. The fix reorders the alternation (fraction tried first); this
    locks that fix in and proves genuinely wrong fraction equations are
    still caught, not silently waved through."""
    print("verifier — self-consistency correctly parses fraction equations")

    correct_fraction_equations = [
        "1/2 = 2/4", "3/5 = 6/10", "2/3 = 6/9",
        "1/4 + 1/4 = 1/2", "3/4 - 1/4 = 1/2",
        "1 / 2 = 2 / 4", "3 / 5 = 6 / 10",
    ]
    for eq in correct_fraction_equations:
        check(f"correct fraction equation {eq!r} produces no false warning",
             verifier.check_self_consistency(eq) == [])

    wrong_frac = verifier.check_self_consistency("1/2 = 2/5")
    check("a genuinely WRONG fraction equation is still caught (not over-corrected)",
         len(wrong_frac) == 1
         and wrong_frac[0]["computed"] == "1/2" and wrong_frac[0]["stated"] == "2/5")

    wrong_mixed = verifier.check_self_consistency("3/4 + 1/4 = 2")
    check("a wrong fraction-sum-to-integer equation is still caught",
         len(wrong_mixed) == 1 and wrong_mixed[0]["stated"] == "2")


def test_safety_gate() -> None:
    """Track 5 (safety boundary): a bounded, deterministic (no LLM call)
    input/output safety gate. check_input must run before any LLM-based
    routing ever sees the text; check_output is a defense-in-depth scan of
    what the model itself produced."""
    print("safety — deterministic input/output gate")

    safe_inputs = ["What is 24 + 18?", "I don't understand", "give me a hint",
                  "counting", "8 + 9 = 7", "can you explain fractions"]
    for s in safe_inputs:
        check(f"safe input not blocked: {s!r}", safety.check_input(s).blocked is False)

    unsafe_cases = [
        ("I want to kill myself", "self_harm"),
        ("I'm going to kill you", "violence"),
        ("you are a fucking idiot", "sexual_profanity"),
        ("call me at 555-123-4567", "personal_info"),
        ("my home address is 12 Oak Street", "personal_info"),
    ]
    for text, _ in unsafe_cases:
        result = safety.check_input(text)
        check(f"unsafe input blocked: {text!r}", result.blocked is True)
        check(f"blocked input has a child-safe fallback (no category leaked): {text!r}",
             bool(result.fallback_text) and result.category not in result.fallback_text)

    check("safe generated text is not blocked",
         safety.check_output("Let's add 3 and 2. 3 + 2 = 5. Answer: 5").blocked is False)
    bad_output = safety.check_output("Just go kill yourself if you can't do this.")
    check("unsafe generated text IS blocked", bad_output.blocked is True)
    check("the output fallback is generic (not a copy of the unsafe text)",
         bad_output.fallback_text and "kill" not in bad_output.fallback_text)


def test_system_prompt_requires_self_contained_explanations() -> None:
    """Retrieved NCERT chunks routinely reference pictures, textbook pages,
    and physical classroom materials (matchsticks, bottle caps, dot grids)
    the child cannot see through the chat. The system prompt must explicitly
    forbid treating those as visible/available, rather than relying on the
    model to infer it -- live testing found the tutor otherwise asserting
    specific counts from an unseen 'picture' as fact."""
    print("prompt_registry — system prompt requires self-contained explanations")

    messages = prompt_registry.build_messages(
        "what is data handling", 3, ["On the dot grid given below, draw..."],
        version="v5-personalized", level="intermediate",
    )
    system = messages[0]["content"]
    check("forbids referring to a picture/page the child can't see",
         "look at the picture" in system.lower() or "cannot see any picture" in system.lower())
    check("tells the model to transform physical-material references into "
         "self-contained or explicitly imagined framing",
         "imagine" in system.lower())


def test_system_prompt_allows_simple_out_of_grade_explanations() -> None:
    """Section 6: 'out-of-grade = immediate refusal' must not be the only
    behavior. A simple 'what is X' about a topic beyond primary school
    (integration, algebra...) should get one short, honest conceptual gloss;
    only a request for the detailed procedure/formula should still defer.
    Live testing confirmed the pre-fix prompt refused 'what is integration'
    outright with no conceptual attempt at all."""
    print("prompt_registry — simple out-of-grade concepts get a gloss, not a flat refusal")

    messages = prompt_registry.build_messages(
        "what is integration", 5, [], version="v5-personalized", level="intermediate",
    )
    system = messages[0]["content"]
    check("allows a simple conceptual explanation of an advanced topic's name",
         "simple" in system.lower() and "beyond primary school" in system.lower())
    check("still reserves refusal for a DETAILED procedure/formula request, "
         "not just an advanced-sounding topic name",
         "detailed" in system.lower() and "procedure" in system.lower())


def main() -> None:
    test_response_parser()
    test_final_number_str_fallback_tiers()
    test_student_tracker_atomic_save()
    test_verifier_math()
    test_verifier_injection_gate()
    test_verifier_check()
    test_client_fallback()
    test_client_skips_missing_keys()
    test_hints_and_levels()
    test_intent_keyword_fallback()
    test_conversation_resolver_deterministic_paths()
    test_verifier_self_consistency_guardrail()
    test_self_consistency_fraction_parsing()
    test_safety_gate()
    test_topic_canonicalization()
    test_system_prompt_requires_self_contained_explanations()
    test_system_prompt_allows_simple_out_of_grade_explanations()
    print(f"\n{_passed} passed, {_failed} failed")
    if _failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
