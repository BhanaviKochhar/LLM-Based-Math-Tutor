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

print(f"\n{_passed} passed, {_failed} failed")
if _failed:
    raise SystemExit(1)