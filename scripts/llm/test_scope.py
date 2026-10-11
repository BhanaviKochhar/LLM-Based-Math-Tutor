"""Offline tests for scripts/llm/scope.py -- the deterministic NCERT-1-5
syllabus scope gate. check() is pure pattern-matching (no LLM call);
generate_gloss() is tested with an injected chat_fn.

Run:  python -m scripts.llm.test_scope
"""
from __future__ import annotations

from scripts.llm import scope

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


def test_live_reported_scenarios() -> None:
    """The exact three probes from the live report, which exposed that the
    out-of-grade boundary had no code-level check at all."""
    print("scope.check -- the exact live-reported probes")

    r = scope.check("what is matrix algebra")
    check("'what is matrix algebra' -> out of scope, gloss allowed (bare "
         "definition ask)", not r.in_scope and r.allow_gloss and r.topic == "matrix algebra")

    r = scope.check("what is integration")
    check("'what is integration' -> out of scope, gloss allowed",
         not r.in_scope and r.allow_gloss and r.topic == "integration")

    r = scope.check("solve this integral: integral of x dx")
    check("'solve this integral...' -> HARD REFUSE (the case that "
         "previously got a full worked-example walkthrough instead of "
         "being refused at all)",
         not r.in_scope and not r.allow_gloss and r.fallback_text == scope.REFUSAL_TEXT)

    r = scope.check("what is algebra")
    check("'what is algebra' -> out of scope, gloss allowed (the case "
         "that over-delivered a full worked example despite this being "
         "a bare definition ask)",
         not r.in_scope and r.allow_gloss and r.topic == "algebra")


def test_solve_signal_forces_refuse_regardless_of_topic() -> None:
    print("scope.check -- any 'solve/calculate/perform' phrasing forces REFUSE")
    for text in [
        "calculate the derivative of x^2",
        "differentiate x^3 + 2x",
        "can you factorise this polynomial: x^2 - 4",
        "find the value of the integral of 2x dx",
        "please expand (x+1)^2",
        "prove that the square root of 2 is irrational",
    ]:
        r = scope.check(text)
        check(f"{text!r} -> refused (solve-signal present)",
             not r.in_scope and not r.allow_gloss)


def test_bare_definition_allows_gloss_for_each_topic_family() -> None:
    print("scope.check -- a bare 'what is X' allows a gloss for every topic family")
    for text, expected_topic in [
        ("what is a quadratic equation", "quadratic equations"),
        ("what is a logarithm", "logarithms"),
        ("what is a complex number", "complex numbers"),
        ("what is trigonometry", "trigonometry"),
        ("what is probability", "probability"),
        ("what is a polynomial", "polynomials"),
        ("what is coordinate geometry", "coordinate geometry"),
        ("define calculus", "calculus"),
        ("tell me about vectors", "vectors"),
    ]:
        r = scope.check(text)
        check(f"{text!r} -> gloss allowed, topic={expected_topic!r}",
             not r.in_scope and r.allow_gloss and r.topic == expected_topic)


def test_mixed_content_defaults_to_refuse_not_gloss() -> None:
    """Names a beyond-primary topic but isn't a clean bare-definition ask
    (extra content mixed in) -- conservative default is refuse."""
    print("scope.check -- a beyond-primary topic mixed with extra content defaults to refuse")
    for text in [
        "what is algebra and can you also solve 2x+3=7 for me",
        "I need help with my algebra homework, question 5",
        "what is integration used for in physics problems like velocity",
    ]:
        r = scope.check(text)
        check(f"{text!r} -> refused, not glossed (not a clean bare ask)",
             not r.in_scope and not r.allow_gloss)


def test_ordinary_in_syllabus_questions_are_never_flagged() -> None:
    """Broad sanity sweep across genuinely in-grade NCERT 1-5 content --
    none of these should ever be flagged out-of-scope. Specifically
    exercises words that are superficially similar to a beyond-primary
    topic trigger (square the SHAPE vs square ROOT, angle vs trig
    functions, bar graphs vs formal statistics, 'what do you mean' vs
    mean/median/mode)."""
    print("scope.check -- ordinary in-syllabus questions are never flagged")
    for text in [
        "what is a square",                              # shape, Class 1 -- NOT square root
        "what is the area of a rectangle 5cm by 3cm",
        "what is the perimeter of a square",
        "find the LCM of 4 and 6",
        "find the HCF of 12 and 18",
        "what are the factors of 12",
        "what is 2 + 3",
        "what is 1/2 + 1/4",
        "what time is it if it is 3 hours after 5 o'clock",
        "what is a triangle",
        "what is an angle",                               # Class 5, NOT trigonometry
        "round off 4567 to the nearest hundred",
        "read this bar graph and tell me the total",
        "read this pictograph",
        "I don't understand what you mean by subtraction", # "mean" as ordinary English
        "what do you mean by regrouping",
        "what is the mode of transport you like",          # "mode", non-statistics sense
        "convert 3 km to meters",
        "what is the volume of this cube",
        "is this shape symmetric",
        "how many rupees do I have",
        "what is a fraction",
        "divide 20 by 4",
        "multiply 6 by 7",
    ]:
        r = scope.check(text)
        check(f"{text!r} -> in scope, not flagged", r.in_scope)


def test_non_math_subjects_always_refuse_never_gloss() -> None:
    """Different, stricter case than beyond-primary MATH topics: the
    system prompt's own existing policy for a genuinely non-maths subject
    is refuse outright, with no bare-definition-gloss exception at all --
    "what is photosynthesis" should never get even a short science gloss
    from a maths tutor, unlike "what is algebra"."""
    print("scope.check -- non-maths subjects always refuse, even a bare 'what is X'")
    for text, expected_subject in [
        ("what is photosynthesis", "biology"),
        ("tell me about the chemical reaction between acid and base", "chemistry"),
        ("what is gravity", "physics"),
        ("how many planets are in the solar system", "astronomy"),
        ("what is a noun", "language arts"),
        ("what is python programming", "computer science"),
        ("who were the freedom fighters of India", "history"),
        ("what is the capital of France", "geography"),
    ]:
        r = scope.check(text)
        check(f"{text!r} -> refused outright, NOT glossed (topic={expected_subject!r})",
             not r.in_scope and not r.allow_gloss and r.topic == expected_subject
             and r.fallback_text == scope.REFUSAL_TEXT)


def test_non_math_deny_list_does_not_false_positive_on_word_problems() -> None:
    """The non-maths deny-list uses SPECIFIC subject-identifying terms
    (photosynthesis, chemical reaction, solar system...), never a generic
    noun that could appear in an ordinary NCERT word problem -- a plant,
    an animal, water, or electricity-adjacent everyday objects are all
    fair game for a real maths question and must never be flagged."""
    print("scope.check -- ordinary word problems mentioning everyday nouns are not flagged as non-maths")
    for text in [
        "if a plant grows 2cm every day, how tall will it be after 5 days",
        "a farmer has 12 animals, 5 are cows and the rest are goats, how many goats",
        "a water tank holds 20 litres, how many 4-litre buckets fill it",
        "a train travels at a certain speed, how far does it go in 3 hours",
        "there are 6 countries' flags in the picture, how many stars in total",
        "the capital letters in this word problem are A, B, C -- how many are there",
    ]:
        r = scope.check(text)
        check(f"{text!r} -> in scope, not flagged", r.in_scope)


def test_generate_gloss_injected_chat_fn() -> None:
    print("scope.generate_gloss -- injected chat_fn, no live LLM call")
    captured = []

    def fake_chat(messages):
        captured.append(messages)
        return {"text": "A short honest gloss. You'll learn it later!"}

    text = scope.generate_gloss("algebra", chat_fn=fake_chat)
    check("returns the model's text", text == "A short honest gloss. You'll learn it later!")
    check("the topic is named in the final user message",
         "algebra" in captured[0][-1]["content"].lower())

    def empty_chat(messages):
        return {"text": ""}

    text2 = scope.generate_gloss("trigonometry", chat_fn=empty_chat)
    check("an empty model response still returns a safe, non-empty fallback gloss",
         bool(text2) and "trigonometry" in text2.lower())


def main() -> None:
    test_live_reported_scenarios()
    test_solve_signal_forces_refuse_regardless_of_topic()
    test_bare_definition_allows_gloss_for_each_topic_family()
    test_mixed_content_defaults_to_refuse_not_gloss()
    test_ordinary_in_syllabus_questions_are_never_flagged()
    test_non_math_subjects_always_refuse_never_gloss()
    test_non_math_deny_list_does_not_false_positive_on_word_problems()
    test_generate_gloss_injected_chat_fn()
    print(f"\n{_passed} passed, {_failed} failed")
    if _failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
