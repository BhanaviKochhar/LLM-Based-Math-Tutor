"""frontend/episode.py -- controller-driven tutoring episode: turn
generation, verification, attempt recording, and the two-phase
queue/process pending-turn mechanism the main chat page drives.
"""
from __future__ import annotations

import copy
import logging
import random
import time

import streamlit as st

from frontend.config import MOCK_MODE
from frontend.state import _student_id, record_feedback

logger = logging.getLogger(__name__)

# Longer, kid-friendly worked explanations + 3 escalating hints each.
MOCK_RESPONSES = [
    {
        "answer": (
            "Let's work through this one together, nice and slowly.\n\n"
            "We have 3 groups, and each group has 4 apples. Whenever we have equal "
            "groups like this, multiplication is really just a quick way of adding "
            "the same number again and again. So instead of counting every apple, "
            "we can add the group size three times.\n\n"
            "1. Write it as repeated addition: 4 + 4 + 4.\n"
            "2. Add the first two groups: 4 + 4 = 8.\n"
            "3. Add the last group: 8 + 4 = 12.\n\n"
            "So 3 × 4 = 12. There are 12 apples in total! 🍎"
        ),
        "final_answer": "12",
        "hints": [
            "Think about what 'groups of' means — you have 3 equal groups of 4.",
            "Try writing it out as an addition: 4 + 4 + 4.",
            "Now add step by step: 4 + 4 = 8, then 8 + 4 = ?",
        ],
        "source": "NCERT Class 3, Chapter 5: Fun with Multiplication",
    },
    {
        "answer": (
            "Great question — let's picture it before we do any maths.\n\n"
            "A fraction tells us how many equal parts we split something into, and "
            "how many of those parts we take. Imagine a roti. If you cut it straight "
            "down the middle, you get 2 equal halves. Each of those halves is one "
            "part out of two.\n\n"
            "1. The bottom number (2) tells us the roti was cut into 2 equal pieces.\n"
            "2. The top number (1) tells us we are taking 1 of those pieces.\n\n"
            "So 1/2 means one out of two equal halves. 🫓"
        ),
        "final_answer": "1/2",
        "hints": [
            "A fraction is about equal parts — how many pieces did we cut?",
            "The bottom number is the total equal parts; the top is how many we take.",
            "One piece out of two equal pieces — how do we write that?",
        ],
        "source": "NCERT Class 4, Chapter 7: Jugs and Mugs (Fractions)",
    },
    {
        "answer": (
            "Let's add these two numbers the careful way, column by column.\n\n"
            "When we add bigger numbers, we always start from the ones place on the "
            "right, and if a column goes past 9 we 'carry' the extra ten over to the "
            "next column. That keeps everything lined up neatly.\n\n"
            "1. Add the ones: 7 + 5 = 12. Write down 2, and carry the 1.\n"
            "2. Add the tens: 2 + 1 + 1 (the carried one) = 4.\n\n"
            "So 27 + 15 = 42. ✏️"
        ),
        "final_answer": "42",
        "hints": [
            "Start from the ones place on the right — add those digits first.",
            "7 + 5 = 12, so write 2 and carry the 1 to the tens.",
            "Now add the tens: 2 + 1 + the carried 1 — what do you get?",
        ],
        "source": "NCERT Class 2, Chapter 4: Add Our Points",
    },
]


def build_active_turns(chat_messages):
    """Convert stored UI messages into LLM conversation history.

    Only prior turns are returned. The new user question is appended to the
    UI chat after this helper is called and is therefore not duplicated in the
    backend prompt.
    """
    turns = []
    for msg in chat_messages:
        if not isinstance(msg, dict):
            continue

        role = msg.get("role")
        if role == "user":
            text = (msg.get("text") or "").strip()
            if text:
                turns.append({"role": "user", "content": text})

        elif role == "assistant":
            if msg.get("kind") == "chat":
                text = (msg.get("reply") or "").strip()
            else:
                text = (msg.get("text") or "").strip()
            if text:
                turns.append({"role": "assistant", "content": text})

    return turns


def _group_chat_history(messages: list[dict]) -> list[dict]:
    """Group every follow-up turn (an answer attempt, a hint tap, "I don't
    understand"...) under the question that opened its episode, instead of
    listing each one as its own indistinguishable top-level row -- see
    U-05: one problem with a wrong attempt, 3 hints, and a correct answer
    previously produced 7 flat rows ("50", "Give me a hint", "42"...) with
    no way to tell them apart from a real new question.

    A reply is a follow-up exactly when advance_episode/
    _advance_math_followup marked it continues_episode=True; anything else
    (a fresh start_episode, a math follow-up that opened its own new
    sub-episode, a safety block, or plain small talk) starts a new group.

    Returns a list of {"text": question, "follow_ups": int}, oldest first.
    """
    groups: list[dict] = []
    for i, m in enumerate(messages):
        if m.get("role") != "user":
            continue
        nxt = messages[i + 1] if i + 1 < len(messages) else None
        continues = bool(nxt and nxt.get("role") == "assistant"
                        and nxt.get("continues_episode"))
        if continues and groups:
            groups[-1]["follow_ups"] += 1
        else:
            groups.append({"text": m["text"], "follow_ups": 0})
    return groups


def _friendly_reply(q: str) -> str:
    """Local fallback reply used only when the backend errors or produces
    nothing usable for this turn (mirrors the old route_message contract)."""
    low = q.lower()
    if any(w in low for w in ("understand", "confus", "lost", "don't get", "dont get", "stuck", "help")):
        return ("No worries — that happens to everyone! Tell me which part is confusing, "
                "or just type the math problem you're stuck on (like 24 + 18) and I'll "
                "walk you through it step by step. 🙂")
    if any(w in low for w in ("hi", "hello", "hey", "namaste", "good morning", "good evening")):
        return ("Hi there! 👋 I'm Math Buddy. Ask me any math question — for example "
                "\"What is 3 × 4?\" — and I'll explain it step by step!")
    if any(w in low for w in ("thank", "bye", "cool", "nice", "great", "awesome")):
        return "You're welcome! 🌟 Ask me another math question whenever you're ready."
    return ("I'm your math helper, so I do best with math questions! Try something like "
            "\"What is 24 + 18?\" or \"Explain fractions.\" ✏️")



# ===========================================================================
# Controller-driven tutoring episode
#
# One "episode" = one math problem/question, tracked end-to-end by the
# tutoring state machine in scripts.llm.controller (teach_invite -> diagnose
# -> hint -> co_solve -> reveal). This is the integration point described in
# the project plans: the controller — not frontend flags — now decides what
# the tutor says and how much it discloses on every turn. Post-generation
# verification (scripts.llm.verifier.check) also runs here, so the "verify"
# tag reflects a real result instead of a static placeholder.
# ===========================================================================
# Controller button labels this UI renders as clickable shortcuts (bypassing
# the intent classifier, exactly as scripts/llm/intent.py documents buttons
# should). Labels not listed here ("I'll try", "Try again") are purely
# instructional and are shown as plain text, not buttons.
_LABEL_TO_INTENT = {
    "Give me a hint": "HINT",
    "Another hint": "HINT",
    "Show me how": "SOLVE",
    "Just show me": "SOLVE",
    "Show me anyway": "SOLVE",
}
# This ends the open episode instead of advancing it; there is no math
# question to interpret in the button label itself.
#
# KNOWN LIMITATION: the controller also offers "Practice problem" after a
# correct answer (controller._BTN_AFTER_SOLVED), intended to serve up a new,
# similar-difficulty problem. There is no practice-problem generator
# anywhere in scripts/llm/* to back that — building one (a grounded,
# difficulty-matched problem generator with its own extraction/verification)
# is a new capability, not a frontend wiring fix, so it is out of scope for
# this integration pass. The label is deliberately left off
# _ACTIONABLE_LABELS below so it renders as inert text rather than a button
# that promises something the system doesn't do; "New question" remains the
# only actionable way to close a finished episode.
_CLOSE_EPISODE_LABELS = {"New question"}
_ACTIONABLE_LABELS = set(_LABEL_TO_INTENT) | _CLOSE_EPISODE_LABELS


# Single source of truth for both the Badges panel and the "progress to next
# badge" bar, so the two can never silently drift out of sync. (name, color,
# icon, solved-count threshold to unlock).
_BADGES = [
    ("Quick Thinker", "#f5a623", "⚡", 1),
    ("Rising Star", "#2f9e5a", "🌟", 3),
    ("Problem Solver", "#9b5de5", "🏆", 5),
    ("Math Genius", "#e5484d", "🎓", 8),
]


def _progress_to_next_badge(solved: int) -> tuple[int, int | None, float]:
    """(solved, next_threshold, fraction) -- how close this chat's solved
    count is to the next not-yet-earned badge in _BADGES, as a fraction of
    the span SINCE the last badge (so it reads as 0% right after a badge is
    unlocked, climbing to 100% just before the next one -- the familiar
    "XP bar resets on level-up" shape, not a drop). next_threshold is None
    once every badge is earned; fraction is then 1.0.

    Replaces a previous `(solved % 3) / 3` formula: that cycled back to 0%
    every 3rd solve regardless of any badge, and "3" bore no relationship to
    the actual badge thresholds (1, 3, 5, 8, not evenly spaced), so the bar
    measured nothing a label could honestly describe. A simpler
    solved/next_threshold formula was tried and rejected too -- it still
    DROPS by a few percent at the exact moment a badge is earned (e.g. 2/3 =
    67% then 3/5 = 60% the instant the 3rd question is solved), which reads
    as the child's progress going backward right when they succeeded."""
    prev_threshold = 0
    for _, _, _, threshold in _BADGES:
        if solved < threshold:
            span = threshold - prev_threshold
            return solved, threshold, (solved - prev_threshold) / span if span else 1.0
        prev_threshold = threshold
    return solved, None, 1.0


class GenerationFailed(RuntimeError):
    """Raised when a controller-directed turn produced no usable text —
    either the model/backend call raised, or every provider returned empty.
    Deliberately raised (rather than returned as "") so a single rollback
    path in advance_episode/start_episode covers both failure shapes and the
    controller state they were about to commit is never left stranded ahead
    of what the student actually saw."""


def _mock_episode_turn(question: str) -> dict:
    time.sleep(0.5 + random.random() * 0.4)
    r = random.choice(MOCK_RESPONSES)
    return {
        "role": "assistant", "kind": "turn", "mode": "reveal", "text": r["answer"],
        "buttons": ["New question"], "terminal": True, "outcome": "shown",
        "hint_number": None, "source": r["source"],
        "verify": {"verifiable": True, "match": True, "computed": r["final_answer"],
                  "model_value": r["final_answer"], "note": "mock mode"},
    }


def _run_generation(state, action, chunks, active_turns, previous_hints,
                    thread_notes=None):
    """Call the controller->model bridge for this turn's text.

    MODE_HINT and MODE_HINT_EXHAUSTED both return an already-generated
    string (hints.generate_hint is not streamed; MODE_HINT_EXHAUSTED's text
    is a fixed constant, no LLM call at all); every other mode returns a
    TurnStream that must be streamed to populate .text. MODE_NEW_QUESTION
    legitimately has nothing to say. Raises GenerationFailed for every other
    mode that comes back empty, so a silent provider outage is treated the
    same as an exception by callers."""
    from scripts.llm import pipeline, controller as C, response_parser

    result = pipeline.generate_turn(
        state, action, chunks=chunks, active_turns=active_turns,
        previous_hints=previous_hints, thread_notes=thread_notes,
    )
    if action.mode == C.MODE_NEW_QUESTION:
        return ""
    if action.mode in (C.MODE_HINT, C.MODE_HINT_EXHAUSTED):
        text = (result or "").strip()
    elif result is None:
        text = ""
    else:
        for _ in result.stream():
            pass
        text = (result.text or "").strip()
    if not text:
        raise GenerationFailed(f"empty generation for controller mode={action.mode!r}")
    # Single choke point every generated turn passes through -- sanitizing
    # here (not at display time) means the number-extraction/verification
    # below, the self-consistency check, and what gets stored for FUTURE
    # turns' conversation context all see the same clean text the child
    # does, not just the on-screen rendering. See response_parser.strip_latex
    # and .collapse_excess_blank_lines for why these exist instead of a
    # regenerate-on-detection approach.
    text = response_parser.strip_latex(text)
    return response_parser.collapse_excess_blank_lines(text)


def _post_check(state, action, text):
    """Real post-generation verification for turns where a trusted answer was
    injected (co-solve/reveal) — the live counterpart of pipeline.TutorTurn's
    finalize(), which the old ask_tutor() path never called. Returns a
    verifier.check()-shaped dict, or None when there is nothing to verify.

    Also covers MODE_DIAGNOSE_CORRECT: the controller already graded the
    *student's* stated answer against state.computed_answer before this
    runs, but the directive separately tells the model to "confirm the
    answer" in its own words, and nothing previously checked that
    restatement. Without this, a model that confirms with the wrong number
    would go uncaught (see docs/current_state_evaluation.md Section 2)."""
    from scripts.llm import controller as C, verifier

    checked_modes = (C.MODE_CO_SOLVE, C.MODE_REVEAL, C.MODE_DIAGNOSE_CORRECT)
    if action.mode not in checked_modes or not state.computed_answer:
        return None
    computed_value = verifier.parse_trusted_value(state.computed_answer)
    return verifier.check(state.question, text, computed_value=computed_value)


def _record_outcome(state, action) -> None:
    """Attempt recording tied to the controller's own diagnosis, not a
    separate frontend heuristic. Only genuine graded attempts move the
    tracker: every DIAGNOSE_WRONG is one real wrong attempt, and the terminal
    DIAGNOSE_CORRECT / CO_SOLVE-by-threshold turns are the correct/final-wrong
    attempt respectively. Giving up, or asking to be shown the solution
    without ever having attempted the problem, is a request for help, not an
    answer — recording it as "incorrect" would be false evidence that the
    child tried and failed when they may never have tried at all."""
    from scripts.llm import controller as C

    if action.mode == C.MODE_DIAGNOSE_CORRECT:
        record_feedback(state.question, True)
    elif action.mode == C.MODE_DIAGNOSE_WRONG:
        record_feedback(state.question, False)
    elif action.mode == C.MODE_CO_SOLVE and action.outcome == "shown":
        # Reached only by exhausting the wrong-attempt threshold (the
        # give-up path uses the same mode but outcome == "gave_up").
        record_feedback(state.question, False)
    elif action.mode == C.MODE_REVEAL and action.outcome == "shown" and state.attempts >= 1:
        # Honoured a solve request after at least one real wrong attempt.
        record_feedback(state.question, False)
    # Anything else (GIVE_UP, a cold REVEAL with zero attempts, hints,
    # teach/diagnose-in-progress turns) is not a graded attempt.


def _apply_action(chat, episode, action, active_turns) -> dict:
    """Generate + verify this turn. May raise (GenerationFailed or any other
    exception from generation) — callers must not commit episode/chat state
    until this returns successfully. Mutates episode's hint history and
    chat's thread_notes, which is safe because that only happens after text
    generation has already succeeded."""
    from scripts.llm import controller as C, memory, safety, telemetry, verifier

    state = episode["state"]
    thread_notes = chat.get("thread_notes", [])
    # The caller's `active_turns` is built from the WHOLE chat (every earlier
    # episode too) -- fine for conversation_resolver's routing decisions, but
    # wrong for what the model actually sees while generating THIS reply: an
    # earlier finished episode's full transcript would otherwise sit right
    # before the current problem in the prompt, and a model narrating a
    # co-solve/hint can pick up a stray number from it. When the episode
    # tracks where it started (msg_start, set by start_episode/
    # start_followup), scope generation strictly to this episode's own prior
    # turns instead. Falls back to the caller's active_turns when msg_start
    # isn't set (e.g. hand-built episodes in tests).
    msg_start = episode.get("msg_start")
    episode_turns = (build_active_turns(chat["messages"][msg_start:-1])
                     if msg_start is not None else active_turns)
    text = _run_generation(state, action, episode["chunks"], episode_turns,
                           episode["hints_shown"], thread_notes=thread_notes)

    # Output safety: bounded defense-in-depth (see scripts/llm/safety.py) in
    # case the model drifts past the system prompt's own scope instruction.
    # Blocked text never reaches hint bookkeeping, graduation, the
    # trusted-answer check, or the self-consistency scan below -- none of
    # those are meaningful against a generic safety fallback string, and
    # running them against raw unsafe text serves no purpose either.
    output_check = safety.check_output(text) if text else safety.SafetyResult(blocked=False)
    if output_check.blocked:
        text = output_check.fallback_text
        verify = None
        self_check_issues: list = []
    else:
        if action.mode == C.MODE_HINT and text:
            episode["hints_shown"].append(text)

        if action.mode == C.MODE_ACK_CONCEPTUAL:
            # Conceptual episodes have no trusted answer to grade against and
            # would otherwise loop through ACK_CONCEPTUAL forever (controller.py
            # diagnose()). If this reply itself posed a concrete, computable
            # exercise, graduate the episode so the student's next reply is
            # diagnosed numerically instead. No-op (unchanged behaviour) if it
            # didn't -- see controller.graduate_if_computable.
            C.graduate_if_computable(state, text)

        verify = _post_check(state, action, text)

        # Bounded guardrail (Problem 10): the trusted-answer check above only
        # ever covers the STUDENT's own problem, and only for 3 modes. Every
        # mode is free to narrate its OWN illustrative arithmetic (a worked
        # example with different numbers, a hint's partial step); nothing else
        # checks whether THAT narrated arithmetic is internally consistent. This
        # never blocks the reply — only surfaces a non-blocking warning tag.
        self_check_issues = verifier.check_self_consistency(text) if text else []

    _record_outcome(state, action)

    if action.terminal and text:
        chat["thread_notes"] = memory.add_note(
            thread_notes, state.question, action.outcome,
            attempts=state.attempts, hints=state.hints_given,
        )

    # Structured interaction telemetry (distinct from common.log_run's
    # per-generation-call log): one compact record per student turn, enough
    # to reconstruct what was decided without duplicating the raw prompt.
    telemetry.log_interaction(
        chat_id=chat.get("id"), student_id=_student_id(),
        resolved_question=state.question, grade=state.grade, level=state.level,
        is_math=state.is_math, has_trusted_answer=state.computed_answer is not None,
        controller_mode=action.mode, hint_number=action.hint_number,
        attempts=state.attempts, hints_given=state.hints_given,
        terminal=action.terminal, outcome=action.outcome,
        verify=verify, self_check_issue_count=len(self_check_issues),
        input_safety={"checked": True, "blocked": False},
        output_safety={"checked": True, "blocked": output_check.blocked,
                      "category": output_check.category},
    )

    return {
        "role": "assistant", "kind": "turn", "mode": action.mode, "text": text,
        "buttons": list(action.buttons), "terminal": action.terminal,
        "outcome": action.outcome, "hint_number": action.hint_number,
        "source": episode.get("source", ""), "verify": verify,
        "self_check_issues": self_check_issues,
        "safety": {"output_checked": True, "output_blocked": output_check.blocked,
                  "output_category": output_check.category},
    }


def start_episode(chat, question: str, grade: int, ui_level: str, active_turns) -> dict:
    """Begin a new tutoring episode: resolve conversational context, ground it
    in retrieval, compute the trusted answer first (compute-first), then let
    the controller open with its TEACH_INVITE move.

    chat['episode'] is only committed once generation has actually succeeded
    — if it raises, the previous episode (terminal or None) is left exactly
    as it was, so a failed first turn doesn't leave a silently-started
    episode the student never saw and can't now make sense of."""
    if MOCK_MODE:
        reply = _mock_episode_turn(question)
        chat["episode"] = {"state": None, "chunks": [], "source": "", "hints_shown": []}
        return reply

    from scripts.llm import pipeline, controller as C
    from scripts.retrieval import retrieve_with_metadata

    resolution = pipeline.resolve_conversation(question, active_turns, grade=grade)
    level = pipeline.resolve_level(_student_id(), ui_level)

    is_opener = not any(t.get("role") == "user" for t in (active_turns or []))
    if is_opener and getattr(resolution, "mode", "NEW") == "FRAGMENT":
        # A first message with nothing to act on ("Which is the bigger
        # one?"): ask what the child means, and open NO episode, so their
        # next message -- usually the actual problem -- starts a fresh,
        # gradable one through the normal path.
        state, _ = C.start(question, grade, level)
        state, action = C.step(state, "CLARIFY", question)
        scratch = {"state": state, "chunks": [], "source": "", "hints_shown": [],
                   "msg_start": len(chat["messages"]) - 1}
        return _apply_action(chat, scratch, action, active_turns)  # chat["episode"] untouched

    chunks_meta = (retrieve_with_metadata(resolution.retrieval_query, grade)
                  if resolution.use_rag else [])
    chunks = [c.get("text", "") for c in chunks_meta]
    source = pipeline.source_citation(chunks_meta)

    if resolution.use_verifier:
        computed_answer, is_math, answer_type = pipeline.compute_trusted_answer(
            resolution.resolved_question, grade)
    else:
        computed_answer, is_math, answer_type = None, False, "numeric"

    state, action = C.start(
        resolution.resolved_question, grade, level,
        computed_answer=computed_answer, is_math=is_math, answer_type=answer_type,
    )
    # msg_start anchors this episode to the user message that opened it, so
    # _apply_action only ever shows the model turns from THIS problem, never
    # an earlier finished episode's transcript (which can carry stray
    # numbers from an unrelated problem into this one's generation context).
    episode = {"state": state, "chunks": chunks, "source": source, "hints_shown": [],
              "msg_start": len(chat["messages"]) - 1}
    reply = _apply_action(chat, episode, action, active_turns)  # may raise
    chat["episode"] = episode  # commit only after generation succeeded
    return reply


def _advance_math_followup(chat, episode, text, grade, active_turns) -> dict:
    """Handle intent.MATH_FOLLOWUP: the child changed a number/condition in
    the CURRENT problem (e.g. "what if it was 150 instead of 136?") instead
    of answering it.

    This is the fix for the architectural gap found live: an open episode's
    turns previously went ONLY through intent.py's ATTEMPT/HINT/SOLVE/
    GIVE_UP/NEW_QUESTION classifier, which has no notion of "the problem
    itself changed" — a mid-value change fell through to ATTEMPT, and
    diagnose() (seeing several numbers, no single stated answer) replied
    "what answer did you get?", silently losing the relationship to the
    previous problem. Here we reuse conversation_resolver (the same
    resolver new episodes already get) to actually compute the new resolved
    question and trusted answer, then open a fresh sub-episode via
    controller.start_followup so the tutor explicitly connects it to the
    problem it came from, rather than pretending nothing came before.

    Same commit-after-success discipline as advance_episode: episode["state"]
    is only overwritten once _apply_action's generation has succeeded.
    """
    from scripts.llm import pipeline, controller as C

    state = episode["state"]
    resolution = pipeline.resolve_conversation(text, active_turns, grade=grade)

    if resolution.mode != "MATH_FOLLOWUP" or not resolution.changed:
        # A second, heavier look disagreed with the cheap classifier (e.g.
        # low-confidence rewrite demoted to FRAGMENT) -- don't silently drop
        # the turn; fall back to grading it as a plain attempt against the
        # CURRENT problem instead of guessing a new one.
        trial_state = copy.copy(state)
        new_state, action = C.step(trial_state, "ATTEMPT", text)
        trial_episode = dict(episode, state=new_state)
        reply = _apply_action(chat, trial_episode, action, active_turns)
        episode["state"] = new_state
        reply["continues_episode"] = True
        return reply

    if resolution.use_verifier:
        computed_answer, is_math, answer_type = pipeline.compute_trusted_answer(
            resolution.resolved_question, grade)
    else:
        computed_answer, is_math, answer_type = None, False, "numeric"

    new_state, action = C.start_followup(
        state.question, resolution.resolved_question, grade, state.level,
        computed_answer=computed_answer, is_math=is_math, answer_type=answer_type,
    )
    # This is functionally a new episode (own attempts/hints budget) derived
    # from the old one, so it gets its own msg_start too -- its generation
    # context should start from the follow-up turn, not replay the whole
    # parent problem's transcript (the directive above already names the
    # connection to the previous problem in words).
    msg_start = len(chat["messages"]) - 1
    trial_episode = dict(episode, state=new_state, msg_start=msg_start)
    reply = _apply_action(chat, trial_episode, action, active_turns)  # may raise
    episode["state"] = new_state  # commit only after generation succeeded
    episode["msg_start"] = msg_start
    return reply


def advance_episode(
    chat, text: str, grade: int, ui_level: str, active_turns,
    forced_intent: str | None = None,
) -> dict:
    """Classify the student's turn against the open episode and let the
    controller decide the next tutoring move. A terminal/missing episode, or
    a NEW_QUESTION intent, closes out and starts fresh from this same text.

    intent.py's classifier (not conversation_resolver) is still the FIRST
    stop for an open episode, so the common ATTEMPT/HINT/SOLVE/GIVE_UP turns
    cost exactly one classification call, same as before. It now also
    recognises CONFUSION/CORRECTION/CLARIFY/MATH_FOLLOWUP (see intent.py's
    module docstring); CONFUSION/CORRECTION/CLARIFY are generation-only
    (controller.step handles them directly, no state mutation, no RAG/
    verifier re-run) and MATH_FOLLOWUP is the one branch that needs the
    heavier conversation_resolver to actually compute what changed, handled
    by _advance_math_followup above.

    State-consistency note: controller.step() mutates its TutorState argument
    in place. To keep a failed generation from leaving the controller state
    advanced (attempt counted, phase flipped) ahead of what the student
    actually saw, step() runs on a snapshot copy; the live episode's state is
    only overwritten with that snapshot after _apply_action's generation has
    actually succeeded. A raised exception therefore leaves the episode
    exactly as it was before this turn, so a retry re-evaluates cleanly
    instead of double-counting an attempt or silently dropping one."""
    episode = chat.get("episode")
    state = episode.get("state") if episode else None
    if MOCK_MODE or state is None or state.terminal:
        return start_episode(chat, text, grade, ui_level, active_turns)

    from scripts.llm import intent as intent_mod, controller as C

    if forced_intent:
        label = forced_intent
    else:
        prior_msgs = chat["messages"][:-1]  # exclude the turn just appended
        last_turn = next((m for m in reversed(prior_msgs) if m.get("role") == "assistant"), None)
        context = (last_turn or {}).get("text") or (last_turn or {}).get("reply") or None
        label = intent_mod.classify_intent(text, context=context)

    if label == "NEW_QUESTION":
        return start_episode(chat, text, grade, ui_level, active_turns)

    if label == "MATH_FOLLOWUP":
        return _advance_math_followup(chat, episode, text, grade, active_turns)

    trial_state = copy.copy(state)
    new_state, action = C.step(trial_state, label, text)
    trial_episode = dict(episode, state=new_state)
    reply = _apply_action(chat, trial_episode, action, active_turns)  # may raise
    episode["state"] = new_state  # commit only after generation succeeded
    # Marks this as a follow-up turn on the SAME problem, not a fresh
    # question -- History groups turns under their opening question using
    # this flag (see U-05: every answer attempt/hint tap/"I don't
    # understand" used to appear as its own indistinguishable top-level row).
    reply["continues_episode"] = True
    return reply


def submit_turn(
    chat, text: str, grade: int, ui_level: str, active_turns,
    forced_intent: str | None = None,
) -> dict:
    """Advance (or start) the episode for one piece of student input.

    Never raises. Two distinct failure shapes are kept apart deliberately
    (finding E): a genuine backend/generation failure is logged (visible in
    the server console during development) and shown as an explicit,
    recoverable error — never dressed up as a normal tutoring reply, and
    never silently presented as if the turn succeeded — while a falsy result
    that isn't an exception falls back to the old conversational reply used
    for unparseable input.

    Input safety runs FIRST, before conversation_resolver/intent.classify_intent
    (both of which can themselves make an LLM call) -- a blocked turn never
    reaches the resolver, retrieval, verifier, or generation at all, and the
    open episode's state is left completely untouched. The syllabus SCOPE
    gate (scripts/llm/scope.py) runs right after it, in the same slot and
    for the same reason: live-reported, "solve this integral: integral of x
    dx" was never refused at all -- it got a full worked-example
    walkthrough -- because the out-of-grade boundary previously had no
    code-level check, only a prose rule inside the much larger tutoring
    prompt. A hard-refuse scope result short-circuits here with ZERO LLM
    call, the same way a safety block does."""
    from scripts.llm import safety, scope, telemetry

    input_check = safety.check_input(text)
    if input_check.blocked:
        logger.info("submit_turn: input safety blocked turn (category=%s)",
                   input_check.category)
        telemetry.log_interaction(
            chat_id=chat.get("id"), student_id=_student_id(),
            controller_mode="safety_blocked", terminal=False,
            input_safety={"checked": True, "blocked": True,
                         "category": input_check.category},
            output_safety={"checked": False, "blocked": False},
        )
        return {
            "role": "assistant", "kind": "turn", "mode": "safety_blocked",
            "text": input_check.fallback_text, "buttons": [], "terminal": False,
            "outcome": None, "hint_number": None, "source": "", "verify": None,
            "self_check_issues": [],
            "safety": {"input_checked": True, "input_blocked": True,
                      "input_category": input_check.category,
                      "output_checked": False, "output_blocked": False},
        }

    scope_check = scope.check(text)
    if not scope_check.in_scope and not scope_check.allow_gloss:
        logger.info("submit_turn: scope gate refused (topic=%s)", scope_check.topic)
        telemetry.log_interaction(
            chat_id=chat.get("id"), student_id=_student_id(),
            controller_mode="scope_refused", terminal=False,
            input_safety={"checked": True, "blocked": False},
            output_safety={"checked": False, "blocked": False},
        )
        return {
            "role": "assistant", "kind": "turn", "mode": "scope_refused",
            "text": scope_check.fallback_text, "buttons": [], "terminal": False,
            "outcome": None, "hint_number": None, "source": "", "verify": None,
            "self_check_issues": [],
            "safety": {"input_checked": True, "input_blocked": False,
                      "output_checked": False, "output_blocked": False},
        }
    if not scope_check.in_scope and scope_check.allow_gloss:
        # A bare "what is X" for a topic beyond primary school -- still
        # needs real generation, but routed through scope.generate_gloss's
        # small, single-purpose prompt rather than the much larger
        # multi-purpose tutoring prompt, whose prose "no formulas, no
        # worked example" rule was NOT reliably followed (confirmed live:
        # "what is algebra" got a full worked example anyway).
        # The child's own word ("median"), not the topic label
        # ("statistics"): v1 glossed "What is a median?" as statistics.
        gloss_text = scope.generate_gloss(scope_check.matched_term or scope_check.topic)
        telemetry.log_interaction(
            chat_id=chat.get("id"), student_id=_student_id(),
            controller_mode="scope_gloss", terminal=False,
            input_safety={"checked": True, "blocked": False},
            output_safety={"checked": False, "blocked": False},
        )
        return {"role": "assistant", "kind": "chat", "question": text, "reply": gloss_text}

    try:
        reply = advance_episode(chat, text, grade, ui_level, active_turns,
                                forced_intent=forced_intent)
    except Exception:
        logger.exception("submit_turn: generation failed for input %r", text)
        return {
            "role": "assistant", "kind": "chat", "question": text,
            "reply": ("Hmm, something went wrong on my end and I couldn't finish "
                     "that — nothing was recorded, so please try again. 🙂"),
        }
    if not reply or not (reply.get("text") or "").strip():
        return {"role": "assistant", "kind": "chat", "question": text,
               "reply": _friendly_reply(text)}
    reply.setdefault("safety", {})
    reply["safety"]["input_checked"] = True
    reply["safety"]["input_blocked"] = False
    return reply


def queue_pending_turn(chat, text: str, forced_intent: str | None = None) -> None:
    """Append the student's message NOW, before any generation happens, and
    record it as pending rather than calling submit_turn synchronously.

    Streamlit renders a script top-to-bottom in one pass per rerun: the
    message list is drawn long before the ask-bar's submit handler runs, so
    appending the user's message AND calling the (slow, LLM-backed)
    submit_turn in that same handler meant the browser never saw the
    question on screen until the ENTIRE reply had also finished generating
    -- both appeared together, seconds later, with nothing but a bare
    spinner in between. Splitting into two passes (append + rerun here;
    generate in process_pending_turn on the NEXT pass, once the message
    loop has already drawn this bubble) makes the question appear
    immediately, the way a chat UI is expected to behave."""
    chat["messages"].append({"role": "user", "text": text})
    chat["pending_turn"] = {"text": text, "forced_intent": forced_intent}


def process_pending_turn(chat, grade: int, ui_level: str) -> bool:
    """Run the generation queued by queue_pending_turn, if any. Must be
    called AFTER the message list has been rendered (so the queued user
    bubble from the rerun above is already on screen) and BEFORE the ask
    bar (so it can be disabled while this runs). Returns True iff it
    actually ran a turn (caller should st.rerun() afterward)."""
    pending = chat.get("pending_turn")
    if not pending:
        return False
    with st.container(border=True):
        st.markdown('<div class="tt-q tt-thinking">🤖 <i>Math Buddy is thinking…</i></div>',
                    unsafe_allow_html=True)
    # The pending user message is already the last entry in chat["messages"]
    # (appended by queue_pending_turn) -- active_turns must exclude it, same
    # contract as every other call site in this file.
    active_turns = build_active_turns(chat["messages"][:-1])
    reply = submit_turn(chat, pending["text"], grade, ui_level, active_turns,
                        forced_intent=pending.get("forced_intent"))
    # The safety gate blocks phone numbers/addresses/emails/etc. from ever
    # reaching the model -- but the raw text was already appended to
    # chat["messages"] by queue_pending_turn (deliberately, before this
    # function even runs, so the question bubble appears immediately; see
    # that function's docstring). Without this, a child's real PII sat in
    # plaintext in both the chat transcript and the History list forever,
    # even though the AI itself never saw or used it (U-12). The reply
    # itself already never echoes it back; this just stops the child's OWN
    # input from being the leak.
    if reply.get("safety", {}).get("input_blocked"):
        chat["messages"][-1]["text"] = "[hidden for privacy]"
    chat["messages"].append(reply)
    chat["pending_turn"] = None
    return True
