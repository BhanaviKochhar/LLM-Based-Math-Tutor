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
MODE_HINT_EXHAUSTED = "hint_exhausted"   # hint budget used up; no more model calls for hints
MODE_CONFUSION = "confusion_help"        # child didn't follow the LAST reply about THIS problem
MODE_CORRECTION = "correction_repair"    # child is rejecting/correcting the LAST reply
MODE_CLARIFY = "clarify"                 # message too ambiguous to safely act on

# ---- level-tuned thresholds (personalization dial; Step 7 refines wording) --
# Wrong attempts allowed before we switch to co-solving together.
_COSOLVE_AFTER = {"beginner": 2, "intermediate": 2, "advanced": 3}

# Hints offered per problem before the hint action is retired. Previously
# this was an implicit "min(hints_given, 3)" cap with no exhaustion state, so
# every click past the 3rd silently re-requested "Hint 3 of 3" from the model
# forever -- a wasted call each time, producing a near-duplicate of the same
# "final step" hint rather than anything new (see MODE_HINT_EXHAUSTED).
MAX_HINTS = 3

# Button sets per situation (the UI renders these as SECONDARY shortcuts; the
# text box stays primary). Labels map to intents in the app.
_BTN_AFTER_INVITE = ["I'll try", "Give me a hint", "Show me how"]
_BTN_AFTER_WRONG = ["Try again", "Give me a hint", "Just show me"]
_BTN_AFTER_HINT = ["Try again", "Another hint", "Just show me"]
_BTN_AFTER_HINT_EXHAUSTED = ["I'll try", "Just show me"]
_BTN_AFTER_SOLVED = ["Practice problem", "New question"]
_BTN_TERMINAL = ["New question"]

# Fixed, non-generated message for MODE_HINT_EXHAUSTED -- deliberately NOT an
# LLM call: the whole point of this state is to stop spending a call on a
# hint the system has already told the student everything it will say
# without solving it for them.
HINT_EXHAUSTED_MESSAGE = (
    "You've had all the hints for this one! Want to give it your best guess, "
    "or see it worked out?"
)


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


_QUESTION_SENTENCE_RE = re.compile(r"[^.!?]*\?")


def _posed_subquestions(text: str) -> list[str]:
    """Self-contained '...?'-terminated sentences in `text`, in the order
    they appear. Used only as graduate_if_computable()'s candidate list; a
    sentence ending up here is not yet known to be computable."""
    if not text:
        return []
    return [m.group(0).strip() for m in _QUESTION_SENTENCE_RE.finditer(text)]


def graduate_if_computable(state: "TutorState", generated_text: str) -> bool:
    """Let a conceptual episode (state.is_math False -- e.g. the student
    opened with a broad topic like "fractions") acquire a trusted answer
    mid-conversation, so it can stop looping through MODE_ACK_CONCEPTUAL
    forever once it has something concrete to grade.

    Tutors routinely pose a concrete follow-up exercise unprompted while
    acknowledging a conceptual turn (e.g. "What is one-third of nine
    toffees?"). This checks each '...?'-sentence in the tutor's own reply,
    most recent first, through the SAME compute-first+gate path used
    everywhere else (verifier.solve) -- deliberately not a new extraction
    mechanism. The first sentence that yields a usable value graduates the
    episode (state.computed_answer/is_math are set so the student's NEXT
    reply is diagnosed numerically); if none do, this is a no-op and
    today's unchanged ack-conceptual loop continues. Returns True iff the
    episode was graduated.
    """
    if state.is_math or state.computed_answer is not None:
        return False
    for candidate in reversed(_posed_subquestions(generated_text)):
        answer, is_math = verifier.solve(candidate, state.grade)
        if is_math and answer is not None:
            state.computed_answer = answer
            state.is_math = True
            return True
    return False


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
# A broad method/concept question ("Addition of 3 digit", "What is a
# fraction?") has no SPECIFIC problem whose answer needs protecting --
# state.is_math is False because verifier.compute() correctly found nothing
# to compute, not because there's a secret answer being withheld. Treating
# it like a specific problem (vague "idea behind it" talk, no worked steps)
# produces exactly the generic-analogy-only response this was found to
# produce in practice (e.g. "piles of objects" standing in for an actual
# worked example). A SPECIFIC computable problem (is_math=True, e.g. "What
# is 245 + 136?") keeps the original withhold-and-invite behaviour, since
# there the whole point is for the child to attempt it before being shown.
_d_teach_invite_conceptual = (
    "For THIS reply: this is a BROAD method/concept question with no single "
    "specific problem to protect an answer for (not 'solve this', but 'teach "
    "me this'). Teach it properly: show ONE complete worked example using "
    "YOUR OWN chosen numbers (not the child's, since they gave none) with "
    "the actual working shown, not just a one-line analogy — a full worked "
    "demonstration. Keep it to as many steps as the idea genuinely needs: a "
    "simple idea (like counting a handful of objects) needs only a couple of "
    "short sentences, not a long enumerated list or a bold 'method name' "
    "heading — save the longer numbered breakdown for a technique that "
    "actually has several distinct steps (like column addition). Then invite "
    "the child to try a similar one themselves. Do NOT make an analogy (like "
    "piles of objects) the ONLY explanation — the actual method must be "
    "shown, not just described."
)
_d_teach_invite_specific = (
    "For THIS reply: gently explain the idea behind the question in a few "
    "warm, plain sentences — NO numbered steps. You may add ONE tiny "
    "everyday example using DIFFERENT numbers, in a sentence, if it helps. "
    "Then warmly invite the child to try THIS question themselves. Do NOT "
    "solve their question, do NOT show the final answer, and do NOT write "
    "an 'Answer:' line."
)


def _d_teach_invite(s: TutorState) -> str:
    return _d_teach_invite_conceptual if not s.is_math else _d_teach_invite_specific


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
    # Every ungradable turn in this episode routes through this same
    # directive (there is no computed_answer to diagnose against), so without
    # an explicit instruction to vary the model tends to regenerate the same
    # explanation each time instead of building on what the child just said.
    return (
        "For THIS reply: this is a 'what is / why' question with no single "
        "number answer you can grade. First, look at what the child actually "
        "wrote: if it genuinely shows their own reasoning or a partial answer, "
        "acknowledge THAT specifically and build on their own words. If it is "
        "just a bare request or restatement (e.g. 'learn addition', 'what is "
        "a fraction') with no reasoning of their own in it, do NOT claim they "
        "already noticed, showed, or said something they didn't -- simply "
        "treat it as a request and move the teaching forward. Either way, do "
        "NOT restart with a generic definition they have already heard in "
        "this conversation. Then, if it fits naturally, end with ONE small, "
        "concrete question with a specific number in it that the child could "
        "actually work out (e.g. 'What is one-third of 9?'), phrased as a "
        "question ending in '?' — do not solve it yourself. If a concrete "
        "question doesn't fit naturally here, add one new, SHORT point that "
        "moves the conversation forward instead (do not repeat an example "
        "you already gave). Keep the textbook context as grounding, not as "
        "a script to re-read. Do NOT write an 'Answer:' line and do NOT use "
        "numbered steps."
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
    # "Show me how" / a cold solve request routes here. For a BROAD
    # method question (is_math=False) there is no specific answer to
    # protect, so honour the request directly with the same full worked
    # demonstration as the conceptual teach_invite branch -- "earn it"
    # pedagogy doesn't apply when there's nothing specific being withheld.
    # For a SPECIFIC computable problem (is_math=True), keep protecting
    # THAT problem's answer, but require an actual worked numeric example
    # (different numbers) rather than a vague "explain it another way" --
    # found to otherwise produce another generic conceptual explanation
    # instead of a real demonstration of the method.
    if not s.is_math:
        return _d_teach_invite_conceptual
    return (
        "For THIS reply: the child wants the answer without trying yet. Don't "
        "give THIS problem's answer. Instead, actually demonstrate the method: "
        "show ONE complete worked example using DIFFERENT numbers (not the "
        "child's own problem), with the real steps written out, not just a "
        "restated idea. Then warmly invite ONE try at their own question. "
        "Reassure them they can ask again to see their own worked out. No "
        "'Answer:' line for their own problem."
    )


# A child who says they don't understand the LAST reply about THIS problem is
# not asking for the next rung of the hint ladder (MODE_HINT) and is not
# giving up (GIVE_UP) -- they want the SAME idea re-explained more simply.
# Routed here from intent.CONFUSION, kept separate from MODE_HINT so it never
# consumes the hint budget and never just repeats verbatim.
_d_confusion = (
    "For THIS reply: the child says they did not follow your IMMEDIATELY "
    "PREVIOUS reply about this SAME problem. Do not restart from scratch and "
    "do not just give a generic hint. First identify, from your own last "
    "reply, the ONE specific step or idea most likely to be the sticking "
    "point. Re-explain ONLY that step, more simply (smaller numbers or fewer "
    "words if that helps), using the SAME facts and numbers as the child's "
    "actual problem -- do not introduce a different problem. If it is "
    "genuinely unclear from context what confused them, ask one short, "
    "specific clarifying question instead of guessing or repeating "
    "yourself verbatim. No 'Answer:' line."
)

# The child is rejecting or correcting the tutor's last statement. Routed
# from intent.CORRECTION; must not defend the previous reply or wander into a
# new problem.
_d_correction = (
    "For THIS reply: the child is correcting or rejecting your last "
    "response. Do not defend it or repeat it. Re-read what they actually "
    "said, work out the smallest correction it implies, acknowledge it in "
    "one short warm sentence, and continue from that corrected "
    "understanding of the SAME problem. Do not invent a new problem. The "
    "child has NOT earned the final answer yet just by correcting you -- "
    "do NOT solve their problem, do NOT show the worked-out steps for "
    "THEIR number, do NOT write an 'Answer:' line, and do NOT state the "
    "final numeric answer; go back to gently explaining and inviting them "
    "to try it, exactly as you would for a freshly started problem."
)

# The message is too incomplete/ambiguous to safely act on. Routed from
# intent.CLARIFY; must never invent numbers, retrieve, or verify -- just ask.
_d_clarify = (
    "For THIS reply: the child's message is too incomplete or ambiguous to "
    "safely act on by itself. Do NOT guess a new problem, do NOT invent "
    "numbers or examples, and do NOT solve anything. In one short, warm "
    "sentence, ask the ONE specific clarifying question that would let you "
    "help them with THIS problem."
)


# ---- entry points -----------------------------------------------------------
def start(question: str, grade: int, level: str = "intermediate",
          computed_answer: str | None = None, is_math: bool = False):
    """Begin an episode: teach + invite. Returns (state, action)."""
    s = TutorState(question=question, grade=grade, level=level,
                   computed_answer=computed_answer, is_math=is_math)
    return s, Action(MODE_TEACH_INVITE, _d_teach_invite(s),
                     buttons=list(_BTN_AFTER_INVITE))


def start_followup(previous_question: str, question: str, grade: int,
                   level: str = "intermediate", computed_answer: str | None = None,
                   is_math: bool = False):
    """Begin a new problem that the child derived from the PREVIOUS one by
    changing a value/condition (e.g. "what if it was 150 instead of 136?").

    Functionally a fresh TutorState/episode (its own attempts/hints budget),
    but the opening directive explicitly names the connection to the previous
    problem instead of silently acting as if nothing came before -- the gap
    found live: without this, a mid-value change during an open episode fell
    through to the intent classifier's ATTEMPT handling and the tutor asked
    "what answer did you get?" instead of recognising the new problem.
    Returns (state, action), same contract as start().
    """
    s = TutorState(question=question, grade=grade, level=level,
                   computed_answer=computed_answer, is_math=is_math)
    if not is_math:
        return s, Action(MODE_TEACH_INVITE, _d_teach_invite_conceptual,
                         buttons=list(_BTN_AFTER_INVITE))
    directive = (
        f"For THIS reply: the child has changed the previous problem "
        f"(\"{previous_question}\") into a new one (\"{question}\"). In one "
        "short sentence, acknowledge what they changed and how it connects "
        "to the previous problem. Then continue exactly as you would for a "
        "fresh problem: gently explain the idea in a few warm, plain "
        "sentences (NO numbered steps), and invite the child to try THIS "
        "version themselves. Do NOT solve it and do NOT reveal the final "
        "answer."
    )
    return s, Action(MODE_TEACH_INVITE, directive, buttons=list(_BTN_AFTER_INVITE))


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
        if state.hints_given >= MAX_HINTS:
            return state, Action(MODE_HINT_EXHAUSTED, "",
                                 buttons=list(_BTN_AFTER_HINT_EXHAUSTED))
        state.hints_given += 1
        return state, Action(MODE_HINT, "", buttons=list(_BTN_AFTER_HINT),
                             hint_number=state.hints_given)

    if intent == "SOLVE":
        return _handle_solve(state)

    # Conversational repair intents -- deliberately do NOT touch
    # attempts/hints_given/phase. These are not graded attempts and must not
    # consume the hint budget or end the episode; see docstrings on the
    # _d_confusion/_d_correction/_d_clarify directives above for why each is
    # kept distinct from MODE_HINT/ATTEMPT.
    if intent == "CONFUSION":
        buttons = _BTN_AFTER_WRONG if state.attempts else _BTN_AFTER_INVITE
        return state, Action(MODE_CONFUSION, _d_confusion, buttons=list(buttons))

    if intent == "CORRECTION":
        return state, Action(MODE_CORRECTION, _d_correction,
                             buttons=list(_BTN_AFTER_INVITE))

    if intent == "CLARIFY":
        return state, Action(MODE_CLARIFY, _d_clarify,
                             buttons=list(_BTN_AFTER_INVITE))

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