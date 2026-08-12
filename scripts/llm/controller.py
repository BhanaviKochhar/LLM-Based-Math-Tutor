"""scripts/llm/controller.py — the tutoring state machine (disclosure control).

This is the brain of Tier B. It decides, on each student turn, WHAT the tutor
should do next and how much to reveal — encoding the rules we agreed:

  * Always open with concept -> example -> invite an attempt (TEACH_INVITE).
  * A restate counts as an attempt (handled by the intent classifier).
  * Correct attempt        -> celebrate + offer practice/new question (SOLVED).
  * Wrong attempt          -> acknowledge, point out the slip, nudge, try again.
  * After N wrong attempts  -> stop asking to retry, CO-SOLVE together (SHOWN).
                              N is level-tuned (beginner sooner, advanced later).
  * Hint request           -> reveal the next progressive hint, keep trying.
  * Solve request:
      - after any attempt   -> honour immediately (REVEAL / SHOWN).
      - cold (0 attempts)   -> ONE fresh-angle redirect, then honour next ask.
  * Give up                -> co-solve together (SHOWN, outcome gave_up).
  * New question           -> signal the app to start a fresh episode.

Design: this module is PURE. It never calls the LLM. `step()` returns an
Action (a mode + a generation directive + the buttons to show + whether the
episode terminated and with what outcome). The app/pipeline turns the directive
into actual words via the model. That keeps every transition unit-testable
offline — the whole point of building it before the UI.

Terminal outcomes (SOLVED/SHOWN/GAVE_UP) are what trigger a memory thread note.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import response_parser, verifier

# ---- phases -----------------------------------------------------------------
AWAITING = "awaiting_attempt"
SOLVED = "solved"       # terminal
SHOWN = "shown"         # terminal
GAVE_UP = "gave_up"     # terminal
NEW = "new_question"    # signal: start a fresh episode
TERMINAL = {SOLVED, SHOWN, GAVE_UP}

# ---- response modes (what kind of message to generate) ----------------------
MODE_TEACH_INVITE = "teach_invite"
MODE_DIAGNOSE_CORRECT = "diagnose_correct"
MODE_DIAGNOSE_WRONG = "diagnose_wrong"
MODE_ASK_ANSWER = "ask_answer"          # engaged but no clear answer stated
MODE_ACK_CONCEPTUAL = "ack_conceptual"  # non-computable: acknowledge, encourage
MODE_HINT = "hint"
MODE_CO_SOLVE = "co_solve"
MODE_REVEAL = "reveal"
MODE_REDIRECT = "redirect"              # cold solve -> re-explain, invite a try
MODE_NEW_QUESTION = "new_question"

# ---- level-tuned thresholds (personalization dial; Step 7 refines wording) --
# Wrong attempts allowed before we switch to co-solving together.
_COSOLVE_AFTER = {"beginner": 2, "intermediate": 2, "advanced": 3}

# Button sets per situation (the UI renders these as SECONDARY shortcuts; the
# text box stays primary). Labels map to intents in the app.
_BTN_AFTER_INVITE = ["I'll try", "Give me a hint", "Show me how"]
_BTN_AFTER_WRONG = ["Try again", "Give me a hint", "Just show me"]
_BTN_AFTER_HINT = ["Try again", "Another hint", "Just show me"]
_BTN_AFTER_SOLVED = ["Practice problem", "New question"]
_BTN_TERMINAL = ["New question"]


@dataclass
class TutorState:
    question: str
    grade: int
    level: str = "intermediate"
    computed_answer: str | None = None   # injected truth, or None
    is_math: bool = False
    phase: str = AWAITING
    attempts: int = 0                    # wrong attempts so far
    hints_given: int = 0
    solve_redirect_used: bool = False
    last_attempt: str | None = None

    def cosolve_threshold(self) -> int:
        return _COSOLVE_AFTER.get(self.level, 2)

    @property
    def terminal(self) -> bool:
        return self.phase in TERMINAL


@dataclass
class Action:
    mode: str
    directive: str                       # instruction for the generator
    buttons: list = field(default_factory=list)
    terminal: bool = False
    outcome: str | None = None           # solved / shown / gave_up / moved_on
    hint_number: int | None = None       # for MODE_HINT


# ---- reading a student's stated answer out of free text ---------------------
_NUM = re.compile(r"[-+]?\d+\s*/\s*\d+|[-+]?\d*\.\d+|[-+]?\d+")


def _student_answer(turn: str) -> str | None:
    """Best-effort: the number the student is offering as their answer.

    Prefers a value after '=' or 'answer', else the sole number if there's
    exactly one, else None when it's an approach with several numbers (so we
    ask them to state a final answer rather than mis-grade the working).
    """
    if not turn:
        return None
    t = turn.strip()
    # after the last '=' (e.g. "5 + 3 = 8")
    if "=" in t:
        tail = t.rsplit("=", 1)[1]
        m = _NUM.search(tail)
        if m:
            return re.sub(r"\s+", "", m.group(0))
    # after the word "answer"
    m = re.search(r"answer\D*(" + _NUM.pattern + ")", t, re.IGNORECASE)
    if m:
        return re.sub(r"\s+", "", m.group(1))
    nums = _NUM.findall(t)
    if len(nums) == 1:
        return re.sub(r"\s+", "", nums[0])
    return None  # 0 numbers, or ambiguous multi-number working


def diagnose(turn: str, computed_answer: str | None, is_math: bool) -> str:
    """Return 'correct' | 'wrong' | 'unclear' | 'engaged'.

    'engaged'  -> non-computable / no trusted value; can't grade numerically.
    'unclear'  -> computable, but we couldn't read a single stated answer.
    """
    if not is_math or computed_answer is None:
        return "engaged"
    ans = _student_answer(turn)
    if ans is None:
        return "unclear"
    student_val = verifier._safe_eval(ans)
    truth = verifier._safe_eval(computed_answer)
    if student_val is None or truth is None:
        return "unclear"
    return "correct" if verifier._close(truth, student_val) else "wrong"


# ---- directive builders (words the generator will expand) -------------------
def _d_teach_invite(s: TutorState) -> str:
    return (
        "For THIS reply: gently explain the idea behind the question in a few "
        "warm, plain sentences — NO numbered steps. You may add ONE tiny "
        "everyday example using DIFFERENT numbers, in a sentence, if it helps. "
        "Then warmly invite the child to try THIS question themselves. Do NOT "
        "solve their question, do NOT show the final answer, and do NOT write "
        "an 'Answer:' line."
    )


def _d_diagnose_wrong(s: TutorState) -> str:
    # The correct value is given here so the tutor can spot the slip, but it is
    # NOT injected into the persona/context and must be held privately.
    truth = f" The correct answer is {s.computed_answer}." if s.computed_answer else ""
    return (
        f"For THIS reply: the child tried and said \"{s.last_attempt}\".{truth} "
        "Hold that correct answer PRIVATELY — do NOT tell it to the child. Warmly "
        "say it was a good try, gently point out in one or two plain sentences "
        "where it likely slipped (an arithmetic slip vs a small misunderstanding), "
        "give ONE little nudge, and invite them to try once more. No numbered "
        "steps, no 'Answer:' line."
    )


def _d_diagnose_correct(s: TutorState) -> str:
    return (
        "For THIS reply: the child got it right! Warmly celebrate in a sentence "
        "or two and confirm the answer. Then offer either a slightly harder "
        "practice question OR a new topic — their choice. No numbered steps."
    )


def _d_ask_answer(s: TutorState) -> str:
    return (
        "For THIS reply: the child seems to be working but hasn't given a clear "
        "final answer. In one friendly sentence, ask what answer they got. Do "
        "NOT give the answer."
    )


def _d_ack_conceptual(s: TutorState) -> str:
    return (
        "For THIS reply: this is a 'what is / why' question with no single "
        "number answer. Warmly explain the idea in a few plain sentences using "
        "the textbook context, then invite a related question or a small "
        "practice. Do NOT write an 'Answer:' line and do NOT use numbered steps."
    )


def _d_co_solve(s: TutorState) -> str:
    target = f" and finish at {s.computed_answer}" if s.computed_answer else ""
    return (
        "For THIS reply: the child is stuck after trying. Do NOT just dump the "
        "answer — solve it WITH them, walking through the working in clear short "
        f"numbered steps, checking in warmly as you go{target}. Finish with the "
        "final answer on its own line as 'Answer: <value>'."
    )


def _d_reveal(s: TutorState) -> str:
    target = f" ending at {s.computed_answer}" if s.computed_answer else ""
    return (
        "For THIS reply: the child has asked to see it solved and has earned it. "
        f"Show the working in clear short numbered steps{target}, finish with "
        "'Answer: <value>' on its own line, then warmly offer a new question or "
        "a practice one."
    )


def _d_redirect(s: TutorState) -> str:
    return (
        "For THIS reply: the child wants the answer without trying yet. Don't "
        "give it. In a few warm plain sentences, explain the key idea a "
        "DIFFERENT, simpler way (not a repeat), and warmly invite ONE try. "
        "Reassure them they can ask again to see it worked out. No numbered "
        "steps, no 'Answer:' line."
    )


# ---- entry points -----------------------------------------------------------
def start(question: str, grade: int, level: str = "intermediate",
          computed_answer: str | None = None, is_math: bool = False):
    """Begin an episode: teach + invite. Returns (state, action)."""
    s = TutorState(question=question, grade=grade, level=level,
                   computed_answer=computed_answer, is_math=is_math)
    return s, Action(MODE_TEACH_INVITE, _d_teach_invite(s),
                     buttons=list(_BTN_AFTER_INVITE))


def step(state: TutorState, intent: str, turn: str | None = None):
    """Advance the machine given the student's intent (and optional text).

    Returns (state, action). state.terminal / action.terminal tell the app the
    episode ended; action.outcome feeds the memory thread note.
    """
    if intent == "NEW_QUESTION":
        state.phase = NEW
        return state, Action(MODE_NEW_QUESTION, "", terminal=True, outcome="moved_on")

    if intent == "GIVE_UP":
        state.phase = SHOWN
        return state, Action(MODE_CO_SOLVE, _d_co_solve(state),
                             buttons=list(_BTN_TERMINAL), terminal=True,
                             outcome="gave_up")

    if intent == "HINT":
        state.hints_given += 1
        return state, Action(MODE_HINT, "", buttons=list(_BTN_AFTER_HINT),
                             hint_number=min(state.hints_given, 3))

    if intent == "SOLVE":
        return _handle_solve(state)

    # ATTEMPT (and anything unrecognised) -> treat as an attempt
    return _handle_attempt(state, turn)


def _handle_solve(state: TutorState):
    # Honour if they've engaged (any attempt) or already got one redirect.
    if state.attempts >= 1 or state.solve_redirect_used:
        state.phase = SHOWN
        return state, Action(MODE_REVEAL, _d_reveal(state),
                             buttons=list(_BTN_TERMINAL), terminal=True,
                             outcome="shown")
    state.solve_redirect_used = True
    return state, Action(MODE_REDIRECT, _d_redirect(state),
                         buttons=["I'll try", "Give me a hint", "Show me anyway"])


def _handle_attempt(state: TutorState, turn: str | None):
    verdict = diagnose(turn or "", state.computed_answer, state.is_math)

    if verdict == "correct":
        state.phase = SOLVED
        return state, Action(MODE_DIAGNOSE_CORRECT, _d_diagnose_correct(state),
                             buttons=list(_BTN_AFTER_SOLVED), terminal=True,
                             outcome="solved")

    if verdict == "engaged":  # conceptual — can't grade, keep it supportive
        return state, Action(MODE_ACK_CONCEPTUAL, _d_ack_conceptual(state),
                             buttons=list(_BTN_AFTER_INVITE))

    if verdict == "unclear":  # working shown but no single answer
        return state, Action(MODE_ASK_ANSWER, _d_ask_answer(state),
                             buttons=list(_BTN_AFTER_WRONG))

    # wrong
    state.attempts += 1
    state.last_attempt = turn
    if state.attempts >= state.cosolve_threshold():
        state.phase = SHOWN
        return state, Action(MODE_CO_SOLVE, _d_co_solve(state),
                             buttons=list(_BTN_TERMINAL), terminal=True,
                             outcome="shown")
    return state, Action(MODE_DIAGNOSE_WRONG, _d_diagnose_wrong(state),
                         buttons=list(_BTN_AFTER_WRONG))