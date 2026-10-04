import copy
import logging
import re
import sys
import time
import html
import random
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

logger = logging.getLogger(__name__)

# Put the repo root on sys.path so `scripts.llm` resolves, like the old frontend.
# Launch from the repo root so data/ paths resolve too:  streamlit run frontend/app.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Flip to False to use the real NCERT backend (scripts.llm). The backend itself
# is untouched — the functions below only call into it.
MOCK_MODE = False

STUDENT_ID = "session_user"   # single-user MVP; drives the personalisation loop

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


def record_feedback(question: str, correct: bool) -> None:
    if MOCK_MODE:
        return
    try:
        from scripts.llm import pipeline
        pipeline.record_feedback(STUDENT_ID, topic=question, correct=correct)
    except Exception:
        pass


def reset_student() -> None:
    if MOCK_MODE:
        return
    try:
        from scripts.llm import pipeline
        pipeline.reset_student(STUDENT_ID)
    except Exception:
        pass


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


def _run_generation(state, action, chunks, active_turns, previous_hints):
    """Call the controller->model bridge for this turn's text.

    MODE_HINT returns an already-generated string (hints.generate_hint is not
    streamed); every other mode returns a TurnStream that must be streamed to
    populate .text. MODE_NEW_QUESTION legitimately has nothing to say.
    Raises GenerationFailed for every other mode that comes back empty, so a
    silent provider outage is treated the same as an exception by callers."""
    from scripts.llm import pipeline, controller as C

    result = pipeline.generate_turn(
        state, action, chunks=chunks, active_turns=active_turns,
        previous_hints=previous_hints,
    )
    if action.mode == C.MODE_NEW_QUESTION:
        return ""
    if action.mode == C.MODE_HINT:
        text = (result or "").strip()
    elif result is None:
        text = ""
    else:
        for _ in result.stream():
            pass
        text = (result.text or "").strip()
    if not text:
        raise GenerationFailed(f"empty generation for controller mode={action.mode!r}")
    return text


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


def _apply_action(episode, action, active_turns) -> dict:
    """Generate + verify this turn. May raise (GenerationFailed or any other
    exception from generation) — callers must not commit episode state until
    this returns successfully. Mutates episode's hint history, which is safe
    because that only happens after text generation has already succeeded."""
    from scripts.llm import controller as C

    state = episode["state"]
    text = _run_generation(state, action, episode["chunks"], active_turns,
                           episode["hints_shown"])
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
    _record_outcome(state, action)

    return {
        "role": "assistant", "kind": "turn", "mode": action.mode, "text": text,
        "buttons": list(action.buttons), "terminal": action.terminal,
        "outcome": action.outcome, "hint_number": action.hint_number,
        "source": episode.get("source", ""), "verify": verify,
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

    resolution = pipeline.resolve_conversation(question, active_turns)
    level = pipeline.resolve_level(STUDENT_ID, ui_level)

    chunks_meta = (retrieve_with_metadata(resolution.retrieval_query, grade)
                  if resolution.use_rag else [])
    chunks = [c.get("text", "") for c in chunks_meta]
    source = pipeline.source_citation(chunks_meta)

    if resolution.use_verifier:
        computed_answer, is_math = pipeline.compute_trusted_answer(resolution.resolved_question, grade)
    else:
        computed_answer, is_math = None, False

    state, action = C.start(
        resolution.resolved_question, grade, level,
        computed_answer=computed_answer, is_math=is_math,
    )
    episode = {"state": state, "chunks": chunks, "source": source, "hints_shown": []}
    reply = _apply_action(episode, action, active_turns)  # may raise
    chat["episode"] = episode  # commit only after generation succeeded
    return reply


def advance_episode(
    chat, text: str, grade: int, ui_level: str, active_turns,
    forced_intent: str | None = None,
) -> dict:
    """Classify the student's turn against the open episode and let the
    controller decide the next tutoring move. A terminal/missing episode, or
    a NEW_QUESTION intent, closes out and starts fresh from this same text.

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

    trial_state = copy.copy(state)
    new_state, action = C.step(trial_state, label, text)
    trial_episode = dict(episode, state=new_state)
    reply = _apply_action(trial_episode, action, active_turns)  # may raise
    episode["state"] = new_state  # commit only after generation succeeded
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
    for unparseable input."""
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
    return reply


# ===========================================================================
# Page config + session state
# ===========================================================================
st.set_page_config(page_title="TinyThinker — NCERT Math Tutor", page_icon="🔵", layout="wide")

ss = st.session_state
ss.setdefault("page", "name")
ss.setdefault("name", "")
ss.setdefault("name_field", "")
ss.setdefault("grade", 3)
ss.setdefault("level", "on_track")
ss.setdefault("chat_seq", 1)
ss.setdefault("chats", [{"id": "chat-1", "messages": [], "episode": None}])
ss.setdefault("active", "chat-1")

GRADE_LABEL = {1: "①", 2: "②", 3: "③", 4: "④", 5: "⑤"}


def display_name() -> str:
    return html.escape(ss.name.strip()) if ss.name.strip() else "friend"


def active_chat():
    for c in ss.chats:
        if c["id"] == ss.active:
            return c
    ss.active = ss.chats[0]["id"]
    return ss.chats[0]


def chat_title(chat) -> str:
    for m in chat["messages"]:
        if m["role"] == "user":
            return m["text"]
    return "New chat"


def start_new_chat():
    ss.chat_seq += 1
    cid = f"chat-{ss.chat_seq}"
    ss.chats.append({"id": cid, "messages": [], "episode": None})
    ss.active = cid


# ===========================================================================
# Global CSS — fonts + hide Streamlit chrome
# ===========================================================================
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Baloo+2:wght@500;600;700;800&family=Nunito:wght@400;600;700;800&display=swap');
    [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"],
    #MainMenu, footer { display: none !important; }
    header, [data-testid="stHeader"] {
        background: transparent !important; background-color: transparent !important;
        height: 0 !important; min-height: 0 !important; box-shadow: none !important;
    }
    [data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stMainBlockContainer"],
    [data-testid="stBottom"], [data-testid="stBottomBlockContainer"], [data-testid="stSidebar"],
    section.main, .main, #root > div:first-child { background: transparent !important; }
    ::-webkit-scrollbar { width: 10px; height: 10px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: rgba(120,140,180,0.45); border-radius: 999px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ===========================================================================
# PAGE 1 — NAME
# ===========================================================================
def render_name_page():
    st.markdown(
        """
        <style>
        .stApp, [data-testid="stAppViewContainer"], html, body { background: #3a4a78 !important; }
        .block-container {
            max-width: 900px !important; margin-top: 12vh !important;
            background: rgba(255,255,255,0.06) !important;
            border: 1px solid rgba(255,255,255,0.14) !important;
            border-radius: 34px !important; padding: 60px 64px 66px !important;
            box-shadow: 0 30px 80px rgba(0,0,0,0.30) !important;
        }
        .tt-title {
            font-family: 'Baloo 2', sans-serif !important; font-weight: 800 !important;
            font-size: clamp(52px, 7vw, 96px) !important; line-height: 1.02 !important;
            text-align: center !important; color: #ffffff !important; margin: 0 0 8px 0 !important;
        }
        .tt-title .accent { color: #f5b301 !important; }
        .tt-sub {
            text-align: center !important; font-family: 'Nunito', sans-serif !important;
            font-weight: 700 !important; font-size: clamp(22px, 2.4vw, 30px) !important;
            color: #cdd6e8 !important; margin: 2px 0 30px 0 !important;
        }
        div[data-testid="stTextInput"] input {
        font-family: 'Nunito', sans-serif !important; font-weight: 700 !important;
        font-size: 22px !important; color: #2f4d80 !important;
        border: 4px solid #f5b301 !important; border-radius: 16px !important;
        padding: 16px 20px !important; background: #ffffff !important;
        box-shadow: 0 10px 26px rgba(0,0,0,0.22) !important;
        }
        [data-testid="stHorizontalBlock"] { align-items: center !important; }
        [class*="st-key-go_btn"] button {
            font-family: 'Baloo 2', sans-serif !important; font-weight: 800 !important;
            font-size: 22px !important; width: 100% !important; border: none !important;
            border-radius: 16px !important; padding: 18px !important;
            background: #e08a1e !important; color: #ffffff !important;
            box-shadow: 0 10px 26px rgba(0,0,0,0.28) !important;
        }
        [class*="st-key-go_btn"] button p { color:#fff !important; font-size:22px !important; font-weight:800 !important; }
        [class*="st-key-go_btn"] button:hover { background:#d47d13 !important; transform: translateY(-2px); }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<p class="tt-title">Welcome, <span class="accent">Tiny&nbsp;Thinker!</span></p>', unsafe_allow_html=True)
    st.markdown('<p class="tt-sub">What is your name?</p>', unsafe_allow_html=True)

    c_in, c_btn = st.columns([3, 1])
    with c_in:
        st.text_input("Your name", key="name_field",
                      placeholder="Type your name here…", label_visibility="collapsed")
    with c_btn:
        if st.button("Let's go →", key="go_btn", use_container_width=True):
            ss.name = ss.name_field.strip()
            ss.page = "greeting"
            st.rerun()
    st.stop()


# ===========================================================================
# PAGE 2 — GREETING
# ===========================================================================
def render_greeting_page():
    st.markdown(
        """
        <style>
        .stApp, [data-testid="stAppViewContainer"], html, body { background: #3a4a78 !important; }
        .block-container {
            max-width: 820px !important; margin-top: 14vh !important;
            background: rgba(255,255,255,0.06) !important;
            border: 1px solid rgba(255,255,255,0.14) !important;
            border-radius: 34px !important; padding: 52px 60px 56px !important;
            box-shadow: 0 30px 80px rgba(0,0,0,0.30) !important;
        }
        .tt-sun { font-size: 84px !important; text-align: center !important; line-height: 1 !important; margin-bottom: 8px !important; }
        .tt-hi {
            font-family: 'Baloo 2', sans-serif !important; font-weight: 800 !important;
            font-size: clamp(44px, 6vw, 76px) !important; text-align: center !important;
            color: #ffffff !important; margin: 0 !important;
        }
        .tt-hi .wave { display:inline-block; animation: wave 1.8s ease-in-out infinite; transform-origin:70% 70%; }
        @keyframes wave { 0%,60%,100%{transform:rotate(0)} 15%{transform:rotate(16deg)} 35%{transform:rotate(12deg)} }
        .tt-hi-sub {
            font-family: 'Nunito', sans-serif !important; font-weight: 700 !important;
            font-size: clamp(20px, 2.3vw, 28px) !important; text-align: center !important;
            color: #cdd6e8 !important; margin: 18px auto 32px !important; max-width: 560px !important; line-height: 1.4 !important;
        }
        [class*="st-key-back_btn"] button, [class*="st-key-start_btn"] button {
            font-family: 'Baloo 2', sans-serif !important; font-weight: 800 !important;
            font-size: 22px !important; width: 100% !important; border-radius: 16px !important;
            padding: 16px !important; box-shadow: 0 10px 26px rgba(0,0,0,0.26) !important;
        }
        [class*="st-key-back_btn"] button {
            background: rgba(255,255,255,0.14) !important; border: 1px solid rgba(255,255,255,0.28) !important; color:#fff !important;
        }
        [class*="st-key-start_btn"] button { background:#e08a1e !important; border:none !important; color:#fff !important; }
        [class*="st-key-back_btn"] button p, [class*="st-key-start_btn"] button p { color:#fff !important; font-size:22px !important; font-weight:800 !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="tt-sun">🌞</div>', unsafe_allow_html=True)
    st.markdown(f'<p class="tt-hi">Hi {display_name()}! <span class="wave">👋</span></p>', unsafe_allow_html=True)
    st.markdown('<p class="tt-hi-sub">Hope you\'re having a wonderful day. Ready to ask some math questions?</p>', unsafe_allow_html=True)

    b1, b2 = st.columns(2)
    with b1:
        if st.button("← Back", key="back_btn", use_container_width=True):
            ss.page = "name"; st.rerun()
    with b2:
        if st.button("Start asking →", key="start_btn", use_container_width=True):
            ss.page = "main"; st.rerun()
    st.stop()


# ===========================================================================
# PAGE 3 — MAIN
# ===========================================================================
MAIN_CSS = """
<style>
.stApp, [data-testid="stAppViewContainer"], html, body { background: #eef4fd !important; }
/* top clears the fixed app bar; bottom clears the fixed footer */
.block-container { max-width: 100% !important; padding: 104px 1.6rem 170px !important; }

[data-testid="stHorizontalBlock"] { align-items: flex-start !important; }
/* ONLY the side columns (1 & 3) are sticky; the centre scrolls normally */
[data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-of-type(1),
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-of-type(1),
[data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-of-type(3),
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-of-type(3) {
    position: sticky !important; top: 104px !important; align-self: flex-start !important;
}
h1,h2,h3 { font-family: 'Baloo 2', sans-serif !important; }

/* App bar — fixed across the top */
.tt-appbar {
    position: fixed; top: 0; left: 0; right: 0; z-index: 1000;
    display:flex; align-items:center; justify-content:space-between;
    background: linear-gradient(90deg,#1f57d6,#2f6bea);
    margin: 0; border-radius: 0 0 20px 20px;
    padding:16px 34px; box-shadow:0 10px 28px rgba(31,87,214,0.28);
}
.tt-brand { font-family:'Baloo 2',sans-serif; font-weight:800; font-size:26px; color:#fff; }
.tt-brand .y { color:#ffd23f; }
.tt-bar-right { display:flex; align-items:center; gap:16px; }
.tt-stars { background:rgba(0,0,0,0.18); color:#fff; font-weight:800; border-radius:999px; padding:7px 16px; font-size:15px; }
.tt-user { color:#fff; font-weight:800; font-size:15px; display:flex; align-items:center; gap:8px; }
.tt-user .av { width:30px;height:30px;border-radius:50%;background:#ffd23f;color:#1f57d6;display:inline-flex;align-items:center;justify-content:center;font-weight:800;font-family:'Baloo 2',sans-serif; }

/* Cards */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background:#fff !important; border:1px solid #e4ecfa !important; border-radius:16px !important;
    box-shadow:0 8px 22px rgba(31,87,214,0.10) !important; padding:16px !important;
    margin-bottom:16px !important;
}
.tt-card-head {
    margin:-16px -16px 14px -16px !important; padding:13px 18px !important;
    border-radius:16px 16px 0 0 !important;
    background:#1f57d6; color:#fff; font-family:'Baloo 2',sans-serif; font-weight:700; font-size:17px;
}

/* ===== BLUE SIDE PANELS — reliably targeted via container key, not :has() ===== */
[class*="st-key-history_panel"],
[class*="st-key-progress_panel"],
[class*="st-key-badges_panel"] {
    background: linear-gradient(180deg,#2f6bea,#2559c9) !important;
    border-radius: 16px !important;
    border: 1px solid #2150bd !important;
    box-shadow: 0 8px 22px rgba(31,87,214,0.22) !important;
}
[class*="st-key-history_panel"] div[data-testid="stVerticalBlockBorderWrapper"],
[class*="st-key-progress_panel"] div[data-testid="stVerticalBlockBorderWrapper"],
[class*="st-key-badges_panel"] div[data-testid="stVerticalBlockBorderWrapper"] {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}
/* readable text inside blue panels (kept white/gold; black would vanish on blue) */
.tt-prog-row { color:#ffffff !important; }
.tt-prog-row .val { color:#ffd23f !important; }
.tt-badge .lbl { color:#ffffff !important; }
[class*="st-key-hist_view"] label,
[class*="st-key-hist_view"] label p,
[class*="st-key-hist_view"] label div { color:#ffffff !important; font-weight:700 !important; font-size:13.5px !important; }
.stProgress > div > div { background: rgba(255,255,255,0.28) !important; }
.stProgress > div > div > div { background: #ffd23f !important; }

/* History buttons */
[class*="st-key-newchat"] button {
    font-family:'Nunito',sans-serif !important; font-weight:800 !important; font-size:14px !important;
    background:#2f9e5a !important; color:#fff !important; border:none !important; border-radius:11px !important;
    padding:9px !important; margin-bottom:10px !important; box-shadow:none !important;
}
[class*="st-key-newchat"] button p { color:#fff !important; font-weight:800 !important; font-size:14px !important; }
[class*="st-key-chatopen_"] button {
    font-family:'Nunito',sans-serif !important; font-weight:700 !important; font-size:13.5px !important;
    color:#111 !important; background:#f4f7fe !important; border:1px solid #dbe5fa !important;
    border-radius:11px !important; padding:9px 12px !important; margin-bottom:7px !important; box-shadow:none !important;
    justify-content:flex-start !important; text-align:left !important;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}
[class*="st-key-chatopen_"] button p { color:#111 !important; font-weight:700 !important; font-size:13.5px !important; }
[class*="st-key-chatopen_"] button[kind="primary"] { background:#dbeafe !important; border:2px solid #ffd23f !important; }
[class*="st-key-chatopen_"] button[kind="primary"] p { color:#1f57d6 !important; }

/* current-chat question chips (black text on light pill) */
.tt-hist-item { font-family:'Nunito',sans-serif; font-weight:700; font-size:13.5px; color:#111;
    background:#f4f7fe; border:1px solid #dbe5fa; border-radius:10px; padding:8px 12px; margin-bottom:7px;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.tt-hist-empty { font-family:'Nunito',sans-serif; font-weight:700; font-size:13px; color:#eaf1ff;
    background:rgba(255,255,255,0.12); border:1px dashed rgba(255,255,255,0.5); border-radius:10px;
    padding:14px 14px; margin: 4px 2px; text-align:center; }

/* Clear / change-name */
[class*="st-key-clearbtn"] button, [class*="st-key-chgname"] button {
    font-family:'Nunito',sans-serif !important; font-weight:700 !important; font-size:13px !important;
    background:#fff !important; border:1px dashed #b9c8e6 !important; color:#111 !important;
    border-radius:10px !important; padding:8px !important; box-shadow:none !important;
}
[class*="st-key-clearbtn"] button p, [class*="st-key-chgname"] button p { color:#111 !important; font-weight:700 !important; font-size:13px !important; }

/* ===== MIDDLE AREA — all black text (image-2 look) ===== */
.tt-buddy-name { font-family:'Baloo 2',sans-serif; font-weight:800; color:#111; font-size:20px; }
.tt-buddy-line { color:#111; font-weight:600; font-size:16px; }

/* message avatars */
.tt-av { display:inline-flex; width:34px; height:34px; border-radius:12px;
    align-items:center; justify-content:center; font-size:18px; margin-right:9px; vertical-align:middle; }
.tt-av.student { background:#ff6f59; }
.tt-av.bot { background:#f5a623; }
.tt-bot-head { display:flex; align-items:center; font-family:'Baloo 2',sans-serif;
    font-weight:800; color:#111; font-size:16px; margin:2px 0 8px; }

.tt-q {
    display:flex; align-items:center;
    background:#f6f9ff; border:1px solid #e2e9f7; border-radius:12px; padding:12px 15px;
    font-weight:800; color:#111; font-size:17px; margin:2px 0 10px;
}
.answer-block.intro {
    background:#f5f9ff; border:1px solid #e0e9fb; border-left:7px solid #2f6bea; border-radius:14px;
    padding:15px 17px; white-space:pre-wrap; font-size:16px; line-height:1.6; color:#111; font-weight:600; margin-bottom:10px;
}
.answer-block {
    background:#f3fbf6; border:1px solid #cfeed9; border-left:7px solid #43c17e; border-radius:14px;
    padding:16px 18px; white-space:pre-wrap; font-size:16px; line-height:1.6; color:#111; font-weight:600;
}
.chat-reply {
    background:#f5f9ff; border:1px solid #e2e9f7; border-left:6px solid #2f6bea; border-radius:14px;
    padding:14px 16px; font-size:16px; line-height:1.5; color:#111; font-weight:600;
}
.hint-tag {
    font-family:'Nunito',sans-serif; font-size:15px; font-weight:600; color:#111;
    background:#fff4d6; border-left:5px solid #f5b301; border-radius:10px; padding:9px 13px; margin:6px 0;
}
.verify-tag { font-family:'Nunito',sans-serif; font-weight:700; font-size:13px; color:#1c7a41;
    background:#e8f7ee; border:1px solid #bfe8cf; border-radius:999px; padding:4px 12px; display:inline-block; margin-top:8px; }
.source-tag { font-family:'Nunito',sans-serif; font-size:13px; color:#111;
    border-top:1px dashed #dbe3f2; margin-top:10px; padding-top:8px; }
.tt-empty { text-align:center; color:#111; font-weight:700; font-size:16px; padding:8px 0; }

/* answer-check gate */
.feedback-correct { font-family:'Baloo 2',sans-serif; font-weight:700; font-size:16px; color:#1c7a41;
    background:#e6f9ee; border:1px solid #a9e6c1; border-radius:12px; padding:10px 14px; margin:8px 0; }
.feedback-wrong { font-family:'Baloo 2',sans-serif; font-weight:700; font-size:15px; color:#c0343a;
    background:#fdeaea; border:1px solid #f4bfc2; border-radius:12px; padding:10px 14px; margin:8px 0; }
[class*="st-key-ans_"] input { border:1px solid #cdd9f2 !important; border-radius:10px !important;
    font-weight:700 !important; color:#111 !important; background:#fff !important; }

/* per-question shortcut buttons — spread + warm like image 2 */
.tt-shortcut-hint { color:#111; font-weight:700; font-size:14px; margin:10px 2px 6px; }
[class*="st-key-turnbtn_"] button {
    font-family:'Baloo 2',sans-serif !important; font-weight:800 !important; font-size:16px !important;
    background:linear-gradient(135deg,#f5b301,#ff6f59) !important; color:#fff !important;
    border:2px solid #1f2a63 !important; border-radius:14px !important; padding:12px 8px !important;
    box-shadow:3px 3px 0 rgba(31,42,99,0.25) !important;
}
[class*="st-key-turnbtn_"] button p { color:#fff !important; font-weight:800 !important; }

/* Progress rows */
.tt-prog-row { display:flex; align-items:center; justify-content:space-between; padding:8px 0; font-weight:800; font-size:15px; }

/* Badges */
.tt-badges { display:flex; flex-wrap:wrap; gap:12px; }
.tt-badge { width:82px; text-align:center; }
.tt-badge .hex { width:52px;height:52px;margin:0 auto 5px;border-radius:16px;display:flex;align-items:center;justify-content:center;font-size:24px;color:#fff; }
.tt-badge .lbl { font-size:11px; font-weight:800; line-height:1.15; }
.tt-badge.locked .hex { background:rgba(255,255,255,0.16); color:#dbe6ff; }

/* ===== Ask bar (lives INSIDE the centre column -> middle width) ===== */
.tt-ask-label { font-family:'Baloo 2',sans-serif; font-weight:800; color:#111; font-size:18px; margin:4px 2px 6px; }
[class*="st-key-askbox"] input {
    font-family:'Nunito',sans-serif !important; font-weight:700 !important; font-size:17px !important;
    color:#111 !important; background:#fff !important; border:2px solid #cdd9f2 !important;
    border-radius:14px !important; padding:15px 17px !important; box-shadow:0 6px 18px rgba(31,87,214,0.08) !important;
}
[class*="st-key-askbtn"] button {
    font-family:'Baloo 2',sans-serif !important; font-weight:800 !important; font-size:17px !important;
    background:#2f6bea !important; color:#fff !important; border:none !important; border-radius:14px !important;
    padding:15px !important; box-shadow:0 6px 18px rgba(31,87,214,0.18) !important; height:100%;
}
[class*="st-key-askbtn"] button p { color:#fff !important; font-weight:800 !important; font-size:17px !important; }

/* Footer — FIXED at the very bottom, full width */
.tt-footer {
    position: fixed; left: 0; right: 0; bottom: 0; z-index: 1000;
    background:linear-gradient(90deg,#1f57d6,#2f6bea); color:#fff;
    border-radius:20px 20px 0 0; padding:14px 34px;
    font-weight:700; font-size:16px; box-shadow:0 -6px 20px rgba(31,87,214,0.20);
}
/* Fixed ask bar — floats just above the footer, spans full width like a real search bar */
[class*="st-key-ask_bar"] {
    position: fixed !important; left: 0; right: 0; bottom: 74px; z-index: 999;
    max-width: 900px; margin: 0 auto; padding: 0 24px;
}
[class*="st-key-ask_bar"] [data-testid="stHorizontalBlock"] {
    display: flex !important;
    align-items: stretch !important;
    gap: 10px !important;
}
[class*="st-key-ask_bar"] [data-testid="stTextInput"] {
    margin: 0 !important;
}
[class*="st-key-ask_bar"] [data-testid="stTextInput"] > div {
    height: 52px !important;
}
[class*="st-key-ask_bar"] [data-testid="stTextInput"] input {
    font-family:'Nunito',sans-serif !important; font-weight:600 !important; font-size:17px !important;
    color:#111 !important; background:#ffffff !important; border:2px solid #cdd9f2 !important;
    border-radius:16px !important;
    height: 52px !important;
    padding:0 20px !important;
    box-sizing: border-box !important;
    box-shadow:0 10px 30px rgba(31,87,214,0.18) !important;
}
[class*="st-key-ask_bar"] [data-testid="stTextInput"] input::placeholder { color:#8a95b3 !important; }
[class*="st-key-ask_bar"] [class*="st-key-askbtn"] {
    display: flex !important;
    align-items: stretch !important;
}
[class*="st-key-ask_bar"] [class*="st-key-askbtn"] button {
    background:#2f6bea !important; color:#fff !important; border:none !important;
    border-radius:14px !important; font-size:18px !important; font-weight:800 !important;
    height: 52px !important;
    width: 52px !important;
    min-height: 0 !important;
    padding: 0 !important;
    box-shadow:0 10px 30px rgba(31,87,214,0.28) !important;
}
</style>
"""


def render_chat_reply(msg):
    st.markdown('<div class="tt-bot-head"><span class="tt-av bot">🤖</span>Math Buddy</div>',
                unsafe_allow_html=True)
    st.markdown(f'<div class="chat-reply">{html.escape(msg.get("reply", ""))}</div>',
                unsafe_allow_html=True)


def render_turn(msg, idx, is_latest=False):
    """Render one controller-driven tutoring turn.

    The mode (teach_invite / diagnose_correct / diagnose_wrong / hint /
    co_solve / reveal / ...) comes straight from scripts.llm.controller, so
    what's shown — and whether a real answer is on the screen at all — is
    decided by the state machine, not by this function. Shortcut buttons are
    only interactive on the latest turn; older turns are history."""
    st.markdown('<div class="tt-bot-head"><span class="tt-av bot">🤖</span>Math Buddy</div>',
                unsafe_allow_html=True)

    mode = msg.get("mode")
    text = msg.get("text") or ""

    if mode == "diagnose_correct":
        st.markdown('<div class="feedback-correct">⭐ Correct — great job! 🎉</div>',
                    unsafe_allow_html=True)
        if text:
            st.markdown(f'<div class="chat-reply">{html.escape(text)}</div>', unsafe_allow_html=True)
        v = msg.get("verify")
        if v and v.get("verifiable") and v.get("match") is False:
            # The student's stated answer was already graded correct against
            # state.computed_answer by the controller; this catches the rarer
            # case where the model's own celebratory restatement names a
            # different number than the one it just graded.
            st.markdown(
                '<div class="verify-tag" style="background:#fdeaea;color:#c0343a;'
                'border-color:#f4bfc2;">⚠ Disagrees with the computed answer</div>',
                unsafe_allow_html=True,
            )
    elif mode == "hint":
        n = msg.get("hint_number")
        prefix = f"Hint {n}: " if n else ""
        st.markdown(f'<div class="hint-tag">💡 {prefix}{html.escape(text)}</div>',
                    unsafe_allow_html=True)
    elif mode in ("co_solve", "reveal"):
        if text:
            st.markdown(f'<div class="answer-block">{html.escape(text)}</div>', unsafe_allow_html=True)
        v = msg.get("verify")
        if v and v.get("verifiable"):
            if v.get("match") is True:
                st.markdown('<div class="verify-tag">✓ Verified against computed answer</div>',
                            unsafe_allow_html=True)
            elif v.get("match") is False:
                st.markdown(
                    '<div class="verify-tag" style="background:#fdeaea;color:#c0343a;'
                    'border-color:#f4bfc2;">⚠ Disagrees with the computed answer</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown('<div class="verify-tag">… could not read a final number to verify</div>',
                            unsafe_allow_html=True)
        if msg.get("source"):
            st.markdown(f'<div class="source-tag">📖 {html.escape(msg["source"])}</div>',
                        unsafe_allow_html=True)
    elif text:
        st.markdown(f'<div class="chat-reply">{html.escape(text)}</div>', unsafe_allow_html=True)

    if not is_latest:
        return
    buttons = [b for b in (msg.get("buttons") or []) if b in _ACTIONABLE_LABELS]
    if not buttons:
        return
    st.markdown('<div class="tt-shortcut-hint">Tap a shortcut, or type below 👇</div>',
                unsafe_allow_html=True)
    cols = st.columns(len(buttons))
    for col, label in zip(cols, buttons):
        with col:
            if st.button(label, key=f"turnbtn_{idx}_{label}", use_container_width=True):
                chat = active_chat()
                if label in _CLOSE_EPISODE_LABELS:
                    episode = chat.get("episode")
                    state = episode.get("state") if episode else None
                    if state is not None:
                        from scripts.llm import controller as C
                        try:
                            C.step(state, "NEW_QUESTION", label)
                        except Exception:
                            pass
                    chat["episode"] = None
                    chat["messages"].append({"role": "user", "text": label})
                    chat["messages"].append({
                        "role": "assistant", "kind": "chat", "question": label,
                        "reply": "Sure! What would you like to try next? 🙂",
                    })
                else:
                    active_turns = build_active_turns(chat["messages"])
                    chat["messages"].append({"role": "user", "text": label})
                    with st.spinner("Thinking…"):
                        chat["messages"].append(submit_turn(
                            chat, label, ss.grade, ss.level, active_turns,
                            forced_intent=_LABEL_TO_INTENT[label],
                        ))
                st.rerun()


def render_main_page():
    st.markdown(MAIN_CSS, unsafe_allow_html=True)
    chat = active_chat()
    msgs = chat["messages"]

    solved = sum(1 for m in msgs if m.get("role") == "assistant" and m.get("outcome") == "solved")
    stars = solved * 5
    level_num = 1 + solved // 3
    lvl_pct = (solved % 3) / 3

    initial = display_name()[0].upper() if display_name() != "friend" else "🙂"
    st.markdown(
        f'<div class="tt-appbar">'
        f'<div class="tt-brand">Tiny<span class="y">Thinker</span></div>'
        f'<div class="tt-bar-right"><span class="tt-stars">⭐ {stars}</span>'
        f'<span class="tt-user"><span class="av">{initial}</span>{display_name()}</span></div></div>',
        unsafe_allow_html=True,
    )

    left, center, right = st.columns([1, 2.4, 1], gap="medium")

    # ---------- LEFT: History + New chat ----------
    with left:
        with st.container(border=True, key="history_panel"):
            st.markdown('<div class="tt-card-head">History</div>', unsafe_allow_html=True)
            view = st.radio("view", ["Chat History", "All Chats"], horizontal=True,
                            label_visibility="collapsed", key="hist_view")
            if st.button("➕ New chat", key="newchat", use_container_width=True):
                start_new_chat()
                st.rerun()

            if view == "Chat History":
                qs = [m["text"] for m in active_chat()["messages"] if m["role"] == "user"]
                if qs:
                    for n, q in enumerate(qs, 1):
                        short = q if len(q) <= 30 else q[:29] + "…"
                        st.markdown(f'<div class="tt-hist-item">{n}. {html.escape(short)}</div>',
                                    unsafe_allow_html=True)
                else:
                    st.markdown('<div class="tt-hist-empty">No questions in this chat yet — ask one! 👇</div>',
                                unsafe_allow_html=True)
            else:
                for c in reversed(ss.chats):
                    title = chat_title(c)
                    short = title if len(title) <= 24 else title[:23] + "…"
                    q_count = sum(1 for m in c["messages"] if m["role"] == "user")
                    label = f"💬 {short}" + (f"  ({q_count})" if q_count else "")
                    if st.button(label, key=f"chatopen_{c['id']}",
                                 type=("primary" if c["id"] == ss.active else "secondary"),
                                 use_container_width=True):
                        ss.active = c["id"]
                        st.rerun()

    # ---------- CENTER: greeting + conversation + ask bar ----------
    with center:
        st.markdown(
            '<div class="tt-bot-head" style="font-size:20px;">'
            '<span class="tt-av bot">🤖</span>Hi! I\'m Math Buddy</div>'
            '<div class="tt-buddy-line" style="margin:-4px 0 14px 44px;">'
            'Ask me any math question below and I\'ll explain it step by step!</div>',
            unsafe_allow_html=True,
        )

        if not msgs:
            pass
        else:
            pairs, i = [], 0
            while i < len(msgs):
                if msgs[i]["role"] == "user":
                    if i + 1 < len(msgs) and msgs[i + 1]["role"] == "assistant":
                        pairs.append((msgs[i], msgs[i + 1], i + 1))
                    else:
                        pairs.append((msgs[i], None, None))
                    i += 2
                else:
                    i += 1

            # Oldest first, newest last — normal chat order (top -> bottom).
            with st.container(height=430, key="chat_scroll"):
                for q, a, a_idx in pairs:
                    with st.container(border=True):
                        st.markdown(f'<div class="tt-q"><span class="tt-av student">🧒</span>'
                                    f'{html.escape(q["text"])}</div>', unsafe_allow_html=True)
                        if a is not None:
                            if a.get("kind") == "chat":
                                render_chat_reply(a)
                            else:
                                render_turn(a, a_idx, is_latest=(a_idx == len(msgs) - 1))

            components.html(
                f"""
                <!-- cache-buster: {len(msgs)} {time.time()} -->
                <script>
                (function () {{
                    function isScrollable(el) {{
                        if (!el || el.scrollHeight <= el.clientHeight) return false;
                        const style = window.getComputedStyle(el);
                        return style.overflowY === 'auto' || style.overflowY === 'scroll';
                    }}
                    function findScrollable(root) {{
                        if (isScrollable(root)) return root;
                        let best = null, bestOverhang = 0;
                        const all = root.querySelectorAll('*');
                        for (const el of all) {{
                            if (isScrollable(el)) {{
                                const overhang = el.scrollHeight - el.clientHeight;
                                if (overhang > bestOverhang) {{
                                    best = el;
                                    bestOverhang = overhang;
                                }}
                            }}
                        }}
                        return best;
                    }}
                    function scrollToLatestQuestion(tries) {{
                        const doc = window.parent.document;
                        const root = doc.querySelector('[class*="st-key-chat_scroll"]');
                        if (!root) {{
                            if (tries > 0) setTimeout(function () {{ scrollToLatestQuestion(tries - 1); }}, 100);
                            return;
                        }}
                        const scrollable = findScrollable(root);
                        if (!scrollable) {{
                            if (tries > 0) setTimeout(function () {{ scrollToLatestQuestion(tries - 1); }}, 100);
                            return;
                        }}
                        const blocks = scrollable.querySelectorAll('[data-testid="stVerticalBlockBorderWrapper"]');
                        if (blocks.length > 0) {{
                            const last = blocks[blocks.length - 1];
                            const scrollableTop = scrollable.getBoundingClientRect().top;
                            const lastTop = last.getBoundingClientRect().top;
                            scrollable.scrollTop += (lastTop - scrollableTop) - 8;
                        }} else {{
                            scrollable.scrollTop = scrollable.scrollHeight;
                        }}
                    }}
                    scrollToLatestQuestion(20);
                }})();
                </script>
                """,
                height=0,
            )

        # ---- ask bar: fixed at the bottom of the screen, above the footer ----
        ask_key = f"askbox_{ss.active}_{len(msgs)}"
        with st.container(key="ask_bar"):
            a_in, a_btn = st.columns([6, 1])
            with a_in:
                question = st.text_input(
                    "ask", key=ask_key,
                    placeholder="Type your answer, a question, or how you're thinking…",
                    label_visibility="collapsed",
                )
            with a_btn:
                ask_clicked = st.button("↑", key="askbtn", use_container_width=True)

        # Guard against a double-fire of the ask button (Enter + click landing
        # in the same script run), which was causing the same question to be
        # appended twice. We remember which widget key we last acted on and
        # skip if this exact click has already been processed.
        submit_id = f"{ask_key}:{question.strip()}"
        if ask_clicked and question.strip() and st.session_state.get("_last_submit_id") != submit_id:
            st.session_state["_last_submit_id"] = submit_id
            q = question.strip()

            # Build memory BEFORE adding the current user message. This is the
            # key detail that prevents the new question from appearing twice
            # in the LLM prompt.
            active_turns = build_active_turns(chat["messages"])

            chat["messages"].append({"role": "user", "text": q})
            with st.spinner("Thinking…"):
                reply = submit_turn(chat, q, ss.grade, ss.level, active_turns)
            chat["messages"].append(reply)
            st.rerun()

    # ---------- RIGHT: Progress + Badges ----------
    with right:
        with st.container(border=True, key="progress_panel"):
            st.markdown('<div class="tt-card-head">Progress</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="tt-prog-row"><span>⭐ Level {level_num}</span>'
                        f'<span class="val">{int(lvl_pct*100)}%</span></div>',
                        unsafe_allow_html=True)
            st.progress(lvl_pct)
            st.markdown(
                f'<div class="tt-prog-row"><span>✅ Questions Answered</span><span class="val">{solved}</span></div>'
                f'<div class="tt-prog-row"><span>🌟 Stars</span><span class="val">{stars}</span></div>',
                unsafe_allow_html=True,
            )

        with st.container(border=True, key="badges_panel"):
            st.markdown('<div class="tt-card-head">Badges</div>', unsafe_allow_html=True)
            badges = [
                ("Quick Thinker", "#f5a623", "⚡", solved >= 1),
                ("Rising Star", "#2f9e5a", "🌟", solved >= 3),
                ("Problem Solver", "#9b5de5", "🏆", solved >= 5),
                ("Math Genius", "#e5484d", "🎓", solved >= 8),
            ]
            cells = ""
            for name, c, ico, ok in badges:
                cls = "" if ok else "locked"
                bg = f'style="background:{c}"' if ok else ""
                cells += f'<div class="tt-badge {cls}"><div class="hex" {bg}>{ico if ok else "🔒"}</div><div class="lbl">{name}</div></div>'
            st.markdown(f'<div class="tt-badges">{cells}</div>', unsafe_allow_html=True)

        if st.button("🗑️ Clear this chat", key="clearbtn", use_container_width=True):
            chat["messages"] = []
            chat["episode"] = None
            reset_student()
            st.rerun()
        if st.button("↩ Change name", key="chgname", use_container_width=True):
            ss.page = "name"
            st.rerun()

    # ---------- FIXED FOOTER ----------
    st.markdown(
        '<div class="tt-footer">🏆 <b>Keep Practicing!</b> &nbsp; '
        'Solving problems every day makes you a Tiny Thinker champion! 🚀</div>',
        unsafe_allow_html=True,
    )


# ===========================================================================
# Router
# ===========================================================================
if ss.page == "name":
    render_name_page()
elif ss.page == "greeting":
    render_greeting_page()
else:
    render_main_page()
