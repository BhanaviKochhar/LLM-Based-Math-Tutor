"""eval/controller_walk.py — offline walkthrough of the tutoring state machine.

No LLM, no API. Feeds scripted intents/turns through controller.step and checks
the mode, phase, buttons, and terminal outcome at each step against what the
agreed rules say should happen. Run:

    python -m eval.controller_walk
"""
from __future__ import annotations

from scripts.llm import controller as C

_passed = 0
_failed = 0


def check(name, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok   {name}")
    else:
        _failed += 1
        print(f"  FAIL {name}")


def scenario(title):
    print(f"\n{title}")


# 1) correct on first attempt -> SOLVED
scenario("1. correct first attempt -> SOLVED")
s, a = C.start("What is 7 times 8?", 3, "intermediate", computed_answer="56", is_math=True)
check("opens with teach+invite", a.mode == C.MODE_TEACH_INVITE)
check("invite buttons offered", "Give me a hint" in a.buttons)
s, a = C.step(s, "ATTEMPT", "is it 56?")
check("correct -> diagnose_correct", a.mode == C.MODE_DIAGNOSE_CORRECT)
check("terminal solved", a.terminal and a.outcome == "solved" and s.phase == C.SOLVED)
check("offers practice/new", "Practice problem" in a.buttons)

# 2) wrong twice (intermediate) -> CO_SOLVE
scenario("2. two wrong attempts (intermediate) -> CO_SOLVE")
s, a = C.start("What is 7 times 8?", 3, "intermediate", computed_answer="56", is_math=True)
s, a = C.step(s, "ATTEMPT", "54")
check("1st wrong -> diagnose_wrong, not terminal", a.mode == C.MODE_DIAGNOSE_WRONG and not a.terminal)
check("attempt counter = 1", s.attempts == 1)
s, a = C.step(s, "ATTEMPT", "55")
check("2nd wrong -> co_solve terminal", a.mode == C.MODE_CO_SOLVE and a.terminal)
check("outcome shown", a.outcome == "shown" and s.phase == C.SHOWN)

# 3) advanced held longer (needs 3 wrong)
scenario("3. advanced student held for 3 attempts")
s, a = C.start("q", 5, "advanced", computed_answer="56", is_math=True)
s, a = C.step(s, "ATTEMPT", "1")
s, a = C.step(s, "ATTEMPT", "2")
check("advanced: 2 wrong still not terminal", not a.terminal and a.mode == C.MODE_DIAGNOSE_WRONG)
s, a = C.step(s, "ATTEMPT", "3")
check("advanced: 3rd wrong -> co_solve", a.terminal and a.mode == C.MODE_CO_SOLVE)

# 4) hint then correct -> SOLVED
scenario("4. hint then correct")
s, a = C.start("q", 3, "intermediate", computed_answer="56", is_math=True)
s, a = C.step(s, "HINT")
check("hint mode + number", a.mode == C.MODE_HINT and a.hint_number == 1)
check("hints don't count as wrong attempts", s.attempts == 0)
s, a = C.step(s, "ATTEMPT", "56")
check("then correct -> solved", a.terminal and a.outcome == "solved")

# 5) cold solve -> redirect once -> honour on 2nd ask
scenario("5. cold 'just tell me' -> one redirect -> honoured")
s, a = C.start("q", 3, "intermediate", computed_answer="56", is_math=True)
s, a = C.step(s, "SOLVE")
check("cold solve -> redirect, not terminal", a.mode == C.MODE_REDIRECT and not a.terminal)
check("redirect flag set", s.solve_redirect_used)
s, a = C.step(s, "SOLVE")
check("2nd solve -> revealed", a.mode == C.MODE_REVEAL and a.terminal and a.outcome == "shown")

# 6) solve is honoured immediately AFTER an attempt (no redirect)
scenario("6. solve after an attempt -> honoured immediately")
s, a = C.start("q", 3, "intermediate", computed_answer="56", is_math=True)
s, a = C.step(s, "ATTEMPT", "50")           # one wrong attempt
s, a = C.step(s, "SOLVE")
check("solve after attempt -> reveal (no redirect)", a.mode == C.MODE_REVEAL and a.terminal)

# 7) give up -> co-solve, gave_up outcome
scenario("7. give up -> co-solve")
s, a = C.start("q", 3, "intermediate", computed_answer="56", is_math=True)
s, a = C.step(s, "GIVE_UP")
check("give_up -> co_solve terminal", a.mode == C.MODE_CO_SOLVE and a.terminal)
check("outcome gave_up", a.outcome == "gave_up")

# 8) new question -> signals fresh episode
scenario("8. new question signal")
s, a = C.start("q", 3, "intermediate", computed_answer="56", is_math=True)
s, a = C.step(s, "NEW_QUESTION", "what is 9 times 9")
check("new_question -> NEW phase, moved_on", s.phase == C.NEW and a.outcome == "moved_on")

# 9) unclear answer (multi-number working) -> ask for the answer
scenario("9. approach with several numbers -> ask for final answer")
s, a = C.start("q", 3, "intermediate", computed_answer="35", is_math=True)
s, a = C.step(s, "ATTEMPT", "i did 40 then took away 5")
check("ambiguous working -> ask_answer, not graded wrong",
      a.mode == C.MODE_ASK_ANSWER and not a.terminal and s.attempts == 0)

# 10) '5 + 3 = 8' reads the post-'=' value
scenario("10. reads answer after '='")
check("student_answer('5 + 3 = 8') == 8", C._student_answer("5 + 3 = 8") == "8")
check("student_answer('is it 12?') == 12", C._student_answer("is it 12?") == "12")
check("student_answer('maybe 7 left') == 7", C._student_answer("maybe 7 left") == "7")
s, a = C.start("q", 3, "intermediate", computed_answer="8", is_math=True)
s, a = C.step(s, "ATTEMPT", "5 + 3 = 8")
check("'5+3=8' vs truth 8 -> correct", a.outcome == "solved")

# 11) conceptual question -> engaged, supportive (not graded)
scenario("11. conceptual attempt -> engaged")
s, a = C.start("what is a fraction", 3, "intermediate", computed_answer=None, is_math=False)
s, a = C.step(s, "ATTEMPT", "a part of something?")
check("conceptual -> ack_conceptual, not terminal", a.mode == C.MODE_ACK_CONCEPTUAL and not a.terminal)

# 12) conceptual episode graduates to math once the tutor poses a computable
# exercise, and the NEXT attempt is then genuinely diagnosed (not a forever-loop)
scenario("12. conceptual episode graduates when the reply poses a computable exercise")
s, a = C.start("fractions", 3, "intermediate", computed_answer=None, is_math=False)
s, a = C.step(s, "ATTEMPT", "a fraction is part of a whole")
check("still ack_conceptual before graduation", a.mode == C.MODE_ACK_CONCEPTUAL)
graduated = C.graduate_if_computable(
    s, "Good thinking! Here's one to try: what is 1/3 of 9?"
)
check("graduated to a trusted answer", graduated and s.is_math and s.computed_answer == "3")
s, a = C.step(s, "ATTEMPT", "3")
check("next attempt now genuinely diagnosed as correct", a.mode == C.MODE_DIAGNOSE_CORRECT and a.terminal)

scenario("13. no computable sentence in the reply -> no graduation (unchanged loop)")
s, a = C.start("fractions", 3, "intermediate", computed_answer=None, is_math=False)
s, a = C.step(s, "ATTEMPT", "a fraction is part of a whole")
graduated = C.graduate_if_computable(
    s, "Fractions show parts of a whole. Does that make sense so far?"
)
check("not graduated: no computable sentence", not graduated and not s.is_math and s.computed_answer is None)
s, a = C.step(s, "ATTEMPT", "yes")
check("still loops through ack_conceptual, as before", a.mode == C.MODE_ACK_CONCEPTUAL and not a.terminal)

scenario("14. already-math episode is never re-graduated (guard against overwrite)")
s, a = C.start("q", 3, "intermediate", computed_answer="56", is_math=True)
graduated = C.graduate_if_computable(s, "Try this too: what is 2 + 2?")
check("already-math episode untouched", not graduated and s.computed_answer == "56")

# 15) hint lifecycle: state-driven numbering, progression, exhaustion, and
# idempotent repeated clicks after exhaustion. Previously untested: the
# prior "min(hints_given, 3)" cap had no exhaustion state at all, so every
# click past the 3rd silently re-requested the model for "Hint 3 of 3"
# forever (see controller.MODE_HINT_EXHAUSTED).
scenario("15. hint lifecycle: H1 -> H2 -> H3 -> exhausted -> repeated click is idempotent")
s, a = C.start("What is 56 - 29?", 3, "intermediate", computed_answer="27", is_math=True)
s, a = C.step(s, "HINT")
check("Hint 1: mode=hint, hint_number=1 (state-driven, not LLM-chosen)",
     a.mode == C.MODE_HINT and a.hint_number == 1 and s.hints_given == 1)
s, a = C.step(s, "HINT")
check("Hint 2: hint_number=2", a.mode == C.MODE_HINT and a.hint_number == 2 and s.hints_given == 2)
s, a = C.step(s, "HINT")
check("Hint 3: hint_number=3 (== MAX_HINTS)",
     a.mode == C.MODE_HINT and a.hint_number == 3 and s.hints_given == C.MAX_HINTS)
s, a = C.step(s, "HINT")
check("4th HINT request -> MODE_HINT_EXHAUSTED, not another 'Hint 3' call, "
     "hints_given does NOT increment past MAX_HINTS",
     a.mode == C.MODE_HINT_EXHAUSTED and s.hints_given == C.MAX_HINTS)
check("exhausted buttons drop 'Another hint', offering a real next action instead",
     "Another hint" not in a.buttons and "Just show me" in a.buttons)
check("the episode is NOT terminal just because hints are exhausted -- the "
     "student can still try or ask to be shown",
     not a.terminal and s.phase == C.AWAITING)
# Repeated click after exhaustion (simulating a double-submit / rerender):
# calling step() again on the SAME already-exhausted state must be
# idempotent, not compound.
s2, a2 = C.step(s, "HINT")
check("a second request after exhaustion is still MODE_HINT_EXHAUSTED, and "
     "hints_given is unchanged (idempotent, not compounding)",
     a2.mode == C.MODE_HINT_EXHAUSTED and s2.hints_given == C.MAX_HINTS)

scenario("16. hint generation failure does not corrupt hint-count state")
# A failed generation must not have already incremented hints_given before
# the caller can roll back -- controller.step() mutates state SYNCHRONOUSLY
# before any generation call happens (generation is the caller's problem,
# in frontend/app.py's commit-only-after-success pattern), so this checks
# the controller side of that contract: hints_given reflects exactly the
# number of HINT steps actually taken, independent of what the (separate)
# generation layer does with that hint_number afterward.
s, a = C.start("What is 12 x 4?", 3, "intermediate", computed_answer="48", is_math=True)
s, a = C.step(s, "HINT")
pre_fail_hints_given = s.hints_given
# Simulate: the caller's generation step for this hint fails and rolls back
# to a COPY of the state from before this step() call (the actual rollback
# mechanism lives in frontend/app.py; here we confirm the controller-side
# invariant the rollback depends on -- hint_number is a pure function of
# hints_given, so retrying the identical state produces the identical
# hint_number, not a skipped or duplicated one).
import copy as _copy
retry_state = _copy.copy(s)
retry_state.hints_given -= 1  # what frontend/app.py's rollback restores to
s_retry, a_retry = C.step(retry_state, "HINT")
check("retrying after a simulated generation failure reproduces the SAME "
     "hint_number, not the next one (no hint silently skipped or double-counted)",
     a_retry.hint_number == a.hint_number == pre_fail_hints_given)

scenario("17. broad-method vs specific-problem teaching directive selection")
# A broad method/concept question ("Addition of 3 digit") has is_math=False
# (nothing for verifier.compute() to extract) and must get the worked-
# example directive, not the withhold-and-invite one that's correct for a
# SPECIFIC computable problem. See controller._d_teach_invite_conceptual.
s_broad, a_broad = C.start("Addition of 3 digit", 3, "intermediate",
                           computed_answer=None, is_math=False)
check("broad method question -> the worked-example directive variant is used",
     a_broad.directive == C._d_teach_invite_conceptual)
check("the worked-example directive actually asks for real steps, not just an analogy",
     "step by step" in a_broad.directive and "ONE complete worked example" in a_broad.directive)

s_specific, a_specific = C.start("What is 245 + 136?", 3, "intermediate",
                                 computed_answer="381", is_math=True)
check("a specific computable problem -> the withhold-and-invite directive variant is used",
     a_specific.directive == C._d_teach_invite_specific)
check("directives differ between the two cases (not the same text for both)",
     a_broad.directive != a_specific.directive)

scenario("18. 'Show me how' (cold SOLVE) directive also distinguishes broad vs specific")
s_broad2, a_broad2 = C.step(s_broad, "SOLVE")
check("cold 'Show me how' on a broad method question -> honoured directly with "
     "the SAME worked-example directive (no answer to protect, so no redirect gate)",
     a_broad2.mode == C.MODE_REDIRECT and a_broad2.directive == C._d_teach_invite_conceptual)

s_specific2, a_specific2 = C.step(s_specific, "SOLVE")
check("cold 'Show me how' on a specific problem -> still redirected (protects "
     "THIS problem's answer), but now requires an actual worked different-numbers example",
     a_specific2.mode == C.MODE_REDIRECT
     and "DIFFERENT numbers" in a_specific2.directive
     and "381" not in a_specific2.directive)

scenario("19. CONFUSION/CORRECTION/CLARIFY are generation-only (no state mutation)")
for intent_label, expected_mode in (
    ("CONFUSION", C.MODE_CONFUSION),
    ("CORRECTION", C.MODE_CORRECTION),
    ("CLARIFY", C.MODE_CLARIFY),
):
    s0, _ = C.start("What is 7 times 8?", 3, "intermediate",
                    computed_answer="56", is_math=True)
    s0.attempts = 1  # mid-episode, one prior wrong attempt
    pre_attempts, pre_hints, pre_phase = s0.attempts, s0.hints_given, s0.phase
    s1, a1 = C.step(s0, intent_label, "huh?")
    check(f"{intent_label} -> mode {expected_mode}", a1.mode == expected_mode)
    check(f"{intent_label} does not touch attempts", s1.attempts == pre_attempts)
    check(f"{intent_label} does not touch hints_given", s1.hints_given == pre_hints)
    check(f"{intent_label} does not change phase / end the episode",
         s1.phase == pre_phase and not a1.terminal)
    check(f"{intent_label} never reveals the computed answer in its directive",
         "56" not in a1.directive)

s_corr, a_corr = C.step(s0, "CORRECTION", "no thats not what i meant")
check("CORRECTION's directive explicitly forbids solving/revealing the "
     "answer -- live walkthrough found the model otherwise happily solving "
     "a freshly-started problem the moment the child said 'no'",
     "do NOT solve" in a_corr.directive and "do NOT state the final" in a_corr.directive)

scenario("20. start_followup connects a changed value to the previous problem")
s_follow, a_follow = C.start_followup(
    "245 + 136", "245 + 150", 3, "intermediate",
    computed_answer="395", is_math=True,
)
check("opens as teach_invite (same disclosure policy as a fresh episode)",
     a_follow.mode == C.MODE_TEACH_INVITE and not a_follow.terminal)
check("fresh attempts/hints budget for the follow-up sub-episode",
     s_follow.attempts == 0 and s_follow.hints_given == 0)
check("the new problem's trusted answer is NOT leaked into the teach directive",
     "395" not in a_follow.directive)
check("the directive explicitly names BOTH the previous and the new problem, "
     "so the tutor states the connection instead of pretending nothing came before",
     "245 + 136" in a_follow.directive and "245 + 150" in a_follow.directive)

s_follow_conceptual, a_follow_conceptual = C.start_followup(
    "fractions", "what about thirds", 4, "intermediate",
    computed_answer=None, is_math=False,
)
check("a follow-up that resolves to non-computable falls back to the ordinary "
     "conceptual teach_invite directive (no previous-problem text needed)",
     a_follow_conceptual.directive == C._d_teach_invite_conceptual)

print(f"\n{_passed} passed, {_failed} failed")
if _failed:
    raise SystemExit(1)