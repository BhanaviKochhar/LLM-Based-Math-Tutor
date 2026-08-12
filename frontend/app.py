import sys
import time
import random
from pathlib import Path

import streamlit as st

# Make the project root importable so `scripts.*` resolves. Streamlit puts
# the script's own folder (frontend/) on sys.path, not the repo root, so we
# add the parent explicitly. Launch the app from the repo root so the
# data/ paths used by retrieval and the student tracker resolve too:
#     streamlit run frontend/app.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Flip to True to demo the UI with canned content (no API keys / index needed).
MOCK_MODE = False

# The real backend is imported lazily inside _prepare() so MOCK_MODE works
# even in an environment without the LLM/vector-store dependencies installed.

MOCK_RESPONSES = [
    {
        "hint1": "Multiplication means adding the same number again and again. Think about how many equal groups you have!",
        "hint2": "You have 3 groups of 4 apples. Try writing it as 4 + 4 + 4.",
        "hint3": "Now just add 4 + 4 + 4 together, one step at a time — what do you get?",
        "answer": (
            "Let's break it down step by step.\n\n"
            "1. We have 3 groups of 4 apples.\n"
            "2. That means 4 + 4 + 4.\n"
            "3. 4 + 4 = 8, and 8 + 4 = 12.\n\n"
            "So 3 × 4 = 12 apples in total."
        ),
        "source": "NCERT Class 3, Chapter 5: Fun with Multiplication",
    },
    {
        "hint1": "A fraction tells us how many equal parts something is split into.",
        "hint2": "Imagine a roti. If you cut it into 2 equal pieces, each piece is 1 out of those 2 parts.",
        "hint3": "So if you take just 1 of those 2 equal pieces, how would you write that as a fraction?",
        "answer": (
            "Great question! A fraction like 1/2 means we split something "
            "into 2 equal parts and take 1 of them.\n\n"
            "Imagine a roti cut into 2 equal halves — 1/2 is just one of those halves."
        ),
        "source": "NCERT Class 4, Chapter 7: Jugs and Mugs (Fractions)",
    },
    {
        "hint1": "When adding two numbers, always start from the ones place (the right side).",
        "hint2": "Add the ones first: 7 + 5 = 12. Remember to carry the extra 1 over to the tens place!",
        "hint3": "Now add the tens place: 2 + 1 + the 1 you carried. What number do you get?",
        "answer": (
            "To add 27 + 15:\n\n"
            "1. Add the ones: 7 + 5 = 12. Write 2, carry 1.\n"
            "2. Add the tens: 2 + 1 + 1(carry) = 4.\n\n"
            "So 27 + 15 = 42."
        ),
        "source": "NCERT Class 2, Chapter 4: Add Our Points",
    },
]


# ---------------------------------------------------------------------------
# Backend shim
#
# The UI reveals things in stages: hints on tap, then the full answer on tap.
# So instead of one ask_tutor() that returns everything at once, we expose
# three staged calls that map onto the backend pipeline:
#
#   _prepare(question, grade)      -> retrieval only (cheap); no answer yet
#   _generate_hint(state, n)       -> one hint string, lazily, per tap
#   _answer_stream(state)          -> generator of answer tokens (for streaming)
#   _verify(state, answer_text)    -> sympy sanity-check dict
#
# `state` is the assistant message dict; it carries the retrieved chunks so
# hints and the answer stay grounded in the SAME context.
# ---------------------------------------------------------------------------

STUDENT_ID = "session_user"  # single-user MVP; drives the personalisation loop


def _prepare(question: str, grade: int, ui_level: str) -> dict:
    """Retrieve context and resolve the teaching level. No generation."""
    if MOCK_MODE:
        mock = random.choice(MOCK_RESPONSES)
        return {"chunks": [], "source": mock["source"], "level": "intermediate",
                "_mock": mock}

    from scripts.llm import pipeline

    turn = pipeline.prepare(question, grade, level=ui_level, student_id=STUDENT_ID)
    return {"chunks": turn.chunks, "source": turn.source, "level": turn.level}


def _generate_hint(state: dict, n: int) -> str:
    """One hint for level n, grounded in the stored chunks, aware of earlier
    hints so the three levels escalate instead of repeating."""
    if MOCK_MODE:
        time.sleep(0.3)
        return state["_mock"][f"hint{n}"]

    from scripts.llm import pipeline

    previous = [state["hints"][k] for k in range(1, n) if k in state["hints"]]
    return pipeline.get_hint(state["question"], state["grade"], state["chunks"],
                             state["level"], n, previous)


def _answer_stream(state: dict):
    """Yield the final answer token-by-token and stash the completed turn on
    `state` so verification can read it afterwards."""
    if MOCK_MODE:
        for word in state["_mock"]["answer"].split(" "):
            time.sleep(0.02)
            yield word + " "
        state["_answer_text"] = state["_mock"]["answer"]
        return

    from scripts.llm import pipeline

    turn = pipeline.resume(state["question"], state["grade"], state["chunks"],
                           state["level"])
    for piece in turn.stream():
        yield piece
    state["_turn"] = turn
    state["_answer_text"] = turn.answer


def _verify(state: dict) -> dict:
    """Run the sympy sanity check on the streamed answer."""
    if MOCK_MODE:
        return {"verifiable": True, "match": True, "computed": None,
                "model_value": None, "note": "mock"}

    turn = state.get("_turn")
    if turn is not None:
        return turn.finalize()

    from scripts.llm import verifier

    return verifier.check(state["question"], state.get("_answer_text", ""))


def _record_feedback(question: str, correct: bool) -> None:
    if MOCK_MODE:
        return
    try:
        from scripts.llm import pipeline

        pipeline.record_feedback(STUDENT_ID, topic=question, correct=correct)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tier B: controller-driven tutoring turn adapters.
# ---------------------------------------------------------------------------
def _start_episode(question: str, grade: int, ui_level: str) -> dict:
    """Begin an episode: retrieve + solve-first + controller.start().
    Returns an episode dict stored in the message."""
    from scripts.llm import pipeline, controller

    turn = pipeline.prepare(question, grade, level=ui_level, student_id=STUDENT_ID)
    state, action = controller.start(
        question, grade, level=turn.level,
        computed_answer=turn.computed_answer, is_math=turn.is_math)
    return {
        "state": state,
        "action": action,
        "chunks": turn.chunks,
        "source": turn.source,
        "exchanges": [],          # list of {"tutor": str, "student": str|None}
        "buttons": action.buttons,
        "terminal": False,
        "pending_stream": True,    # first tutor message not yet streamed
        "hint_texts": [],          # progressive hints given this episode
    }


def _thread_notes() -> list:
    """Collect capped thread notes from finished episodes in the transcript."""
    from scripts.llm import memory
    notes = []
    for m in st.session_state.messages:
        if m.get("role") == "assistant" and m.get("thread_note"):
            notes.append(m["thread_note"])
    return memory.cap_thread(notes)


def _active_turns(ep: dict) -> list:
    """Prior exchanges of THIS episode as chat messages for memory."""
    turns = []
    for ex in ep["exchanges"]:
        if ex.get("tutor"):
            turns.append({"role": "assistant", "content": ex["tutor"]})
        if ex.get("student"):
            turns.append({"role": "user", "content": ex["student"]})
    return turns


def _turn_stream(ep: dict):
    """Stream the current action's tutor text; stash it on the episode."""
    from scripts.llm import pipeline, controller

    action = ep["action"]
    out = pipeline.generate_turn(
        ep["state"], action, chunks=ep["chunks"],
        thread_notes=_thread_notes(), active_turns=_active_turns(ep),
        previous_hints=ep["hint_texts"],
    )
    # MODE_HINT returns a plain string; everything else a streamable TurnStream.
    if isinstance(out, str):
        ep["hint_texts"].append(out)
        ep["_last_text"] = out
        yield out
        return
    if out is None:
        ep["_last_text"] = ""
        return
    for piece in out.stream():
        yield piece
    ep["_last_text"] = out.text


def _advance(ep: dict, intent: str, turn_text: str | None):
    """Run one controller step for a typed/tapped student turn."""
    from scripts.llm import controller, memory

    # record the student's turn against the last exchange
    if ep["exchanges"]:
        ep["exchanges"][-1]["student"] = turn_text or f"[{intent}]"

    state, action = controller.step(ep["state"], intent, turn_text)
    ep["state"] = state
    ep["action"] = action
    ep["buttons"] = action.buttons
    ep["pending_stream"] = action.mode != controller.MODE_NEW_QUESTION
    if action.terminal:
        ep["terminal"] = True
    return action


def _classify(turn_text: str, ep: dict) -> str:
    from scripts.llm import intent
    ctx = ep["exchanges"][-1]["tutor"][:160] if ep["exchanges"] else None
    return intent.classify_intent(turn_text, context=ctx)


# ---------------------------------------------------------------------------
# Page setup + styling (notebook / graph-paper theme)
# ---------------------------------------------------------------------------

st.set_page_config(page_title="TinyThinker — NCERT Math Tutor", page_icon="🧠", layout="wide")

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Baloo+2:wght@600;700;800&family=Inter:wght@400;500;600&family=Space+Mono:wght@400;700&display=swap');

:root {
    --mint: #eaf6f0;
    --indigo: #2b2d89;
    --indigo-soft: #4a4dc0;
    --mustard: #f5b942;
    --coral: #ff6f59;
    --paper: #fffdf7;
    --charcoal: #2e2e2e;
    --charcoal-soft: #52565e;
    --line: #d8e3da;
    --green: #3a9d5d;
    --red: #e5484d;
}

.stApp {
    background-color: var(--mint);
    background-image: linear-gradient(var(--line) 1px, transparent 1px),
        linear-gradient(90deg, var(--line) 1px, transparent 1px);
    background-size: 28px 28px;
    font-family: 'Inter', sans-serif;
    color: var(--charcoal);
    font-size: 17px;
}

/* Body text readability on the mint background, and bigger for kids */
.stApp p, .stApp li, .stApp span, .stMarkdown {
    color: var(--charcoal);
    font-size: 17px;
}

section[data-testid="stSidebar"] {
    background-color: var(--indigo);
}
section[data-testid="stSidebar"] * {
    color: var(--paper) !important;
}
section[data-testid="stSidebar"] .stRadio label,
section[data-testid="stSidebar"] .stSelectbox label {
    font-family: 'Baloo 2', sans-serif;
    font-weight: 700;
    letter-spacing: 0.03em;
}
section[data-testid="stSidebar"] small,
section[data-testid="stSidebar"] .stCaption {
    color: #cfd0f2 !important;
}

h1, h2, h3, h4, h5 {
    font-family: 'Baloo 2', sans-serif !important;
    color: var(--indigo) !important;
}

.brand-title {
    font-family: 'Baloo 2', sans-serif;
    font-weight: 800;
    font-size: 22px;
    color: var(--paper) !important;
    margin-bottom: 0;
}
.brand-sub {
    font-family: 'Space Mono', monospace;
    font-size: 11px;
    color: #cfd0f2 !important;
    margin-top: -6px;
}

.grade-badge {
    font-family: 'Baloo 2', sans-serif;
    font-weight: 800;
    font-size: 20px;
    background: var(--mustard);
    color: var(--indigo) !important;
    padding: 10px 14px;
    border-radius: 12px;
    text-align: center;
    margin-bottom: 8px;
}

.source-tag {
    font-family: 'Space Mono', monospace;
    font-size: 12px;
    color: var(--charcoal-soft);
    border-top: 1px dashed var(--line);
    margin-top: 8px;
    padding-top: 6px;
}

.verify-tag {
    font-family: 'Space Mono', monospace;
    font-size: 12px;
    color: var(--green);
    margin-top: 2px;
}

.hint-tag {
    font-family: 'Inter', sans-serif;
    font-size: 16px;
    background: #fff4d6;
    border-left: 4px solid var(--mustard);
    border-radius: 8px;
    padding: 8px 12px;
    margin: 6px 0;
}

.feedback-correct {
    font-family: 'Baloo 2', sans-serif;
    font-weight: 700;
    font-size: 18px;
    color: var(--green);
}
.feedback-wrong {
    font-family: 'Baloo 2', sans-serif;
    font-weight: 700;
    font-size: 18px;
    color: var(--red);
}

div[data-testid="stChatMessage"] {
    background-color: var(--paper);
    border: 1px solid var(--line);
    border-radius: 14px;
    box-shadow: 3px 3px 0 rgba(43, 45, 137, 0.06);
}
div[data-testid="stChatMessage"] p {
    color: var(--charcoal) !important;
    font-size: 17px;
}

.stChatInput textarea {
    font-family: 'Inter', sans-serif !important;
    color: white !important;
    font-size: 17px !important;
}
.stChatInput textarea::placeholder {
    color: rgba(255, 255, 255, 0.6) !important;
}

/* Big, bright, fun buttons for kids everywhere in the app */
.stButton > button {
    font-family: 'Baloo 2', sans-serif;
    font-weight: 800;
    font-size: 18px;
    border-radius: 16px;
    border: 3px solid var(--indigo);
    padding: 14px 10px;
    background: linear-gradient(135deg, var(--mustard), var(--coral));
    color: white !important;
    box-shadow: 4px 4px 0 rgba(43, 45, 137, 0.25);
    transition: transform 0.08s ease;
}
/* Tier B: secondary action buttons (shortcuts beside the open text box) */
div[data-testid="column"] .stButton > button {
    font-size: 14px;
    padding: 6px 14px;
    background: #fff;
    color: var(--ink, #2b2b40);
    border: 1.5px solid #e3e3ef;
    box-shadow: none;
    font-weight: 600;
}
div[data-testid="column"] .stButton > button:hover {
    border-color: var(--accent, #f5a623);
    transform: none;
}
.or-type-hint {
    color: #9a9ab0; font-size: 13px; margin: 2px 0 6px 2px;
}
.stButton > button:hover {
    transform: translateY(-2px) scale(1.02);
}
.stButton > button p {
    color: white !important;
    font-size: 18px !important;
}

/* Grade picker buttons — extra big for the landing screen */
.grade-picker .stButton > button {
    font-size: 26px;
    padding: 28px 10px;
    width: 100%;
}
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "grade" not in st.session_state:
    st.session_state.grade = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "level" not in st.session_state:
    st.session_state.level = "on_track"
if "student_id" not in st.session_state:
    st.session_state.student_id = STUDENT_ID

level_labels = {
    "needs_practice": "Needs more practice — simpler steps",
    "on_track": "On track — standard explanation",
    "ahead": "Ahead — shorter, less hand-holding",
}

GRADE_EMOJI = {1: "🐣", 2: "🐥", 3: "🦊", 4: "🐼", 5: "🦁"}

# ---------------------------------------------------------------------------
# Grade selection screen (shown first — D2)
# ---------------------------------------------------------------------------

if st.session_state.grade is None:
    LANDING_CSS = """
    <style>
    .stApp {
        background: linear-gradient(-45deg, #ffe29f, #ffa99f, #ff719a, #a1c4fd, #c2e9fb, #ffe29f);
        background-size: 400% 400%;
        animation: gradientShift 14s ease infinite;
    }
    @keyframes gradientShift {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }
    .sparkle-row {
        text-align: center;
        font-size: 26px;
        letter-spacing: 22px;
        animation: twinkle 2s ease-in-out infinite;
    }
    @keyframes twinkle {
        0%, 100% { opacity: 0.45; }
        50% { opacity: 1; }
    }
    .hero-mascot {
        font-size: 100px;
        text-align: center;
        animation: bounce 1.6s ease-in-out infinite;
        filter: drop-shadow(4px 6px 0 rgba(43,45,137,0.15));
    }
    @keyframes bounce {
        0%, 100% { transform: translateY(0) rotate(-3deg); }
        50% { transform: translateY(-22px) rotate(3deg); }
    }
    .hero-title {
        font-family: 'Baloo 2', sans-serif;
        font-weight: 800;
        font-size: 58px;
        text-align: center;
        background: linear-gradient(90deg, #ff6f59, #f5b942, #3a9d5d, #2b2d89, #ff6f59);
        background-size: 300% auto;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        animation: shine 4s linear infinite;
        margin: 0;
    }
    @keyframes shine {
        to { background-position: 300% center; }
    }
    .hero-sub {
        text-align: center;
        font-family: 'Baloo 2', sans-serif;
        font-size: 22px;
        color: var(--indigo) !important;
        font-weight: 700;
        margin-top: 4px;
    }
    .grade-picker .stButton > button {
        font-size: 26px;
        padding: 30px 10px;
        width: 100%;
        animation: pulse 2.4s ease-in-out infinite;
    }
    @keyframes pulse {
        0%, 100% { box-shadow: 4px 4px 0 rgba(43,45,137,0.25); transform: scale(1); }
        50% { box-shadow: 6px 8px 18px rgba(43,45,137,0.4); transform: scale(1.03); }
    }
    </style>
    """
    st.markdown(LANDING_CSS, unsafe_allow_html=True)

    st.write("")
    st.markdown('<div class="sparkle-row">✨ 🌟 ✨ 🌟 ✨</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-mascot">🦉</div>', unsafe_allow_html=True)
    st.markdown('<p class="hero-title">TinyThinker</p>', unsafe_allow_html=True)
    st.markdown('<p class="hero-sub">Hi! Let\'s make maths super fun today!</p>', unsafe_allow_html=True)
    st.write("")
    st.markdown('<p class="hero-sub" style="font-size:18px;">👇 Tap your class to begin the adventure 👇</p>', unsafe_allow_html=True)
    st.write("")

    st.markdown('<div class="grade-picker">', unsafe_allow_html=True)
    cols = st.columns(5)
    for i, g in enumerate(range(1, 6)):
        with cols[i]:
            if st.button(f"{GRADE_EMOJI[g]}\n\nClass {g}", key=f"grade_btn_{g}", use_container_width=True):
                st.session_state.grade = g
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar — grade badge, level, progress, controls
# ---------------------------------------------------------------------------

grade = st.session_state.grade

with st.sidebar:
    st.markdown('<p class="brand-title">🧠 TinyThinker</p>', unsafe_allow_html=True)
    st.markdown('<p class="brand-sub">NCERT MATHS TUTOR</p>', unsafe_allow_html=True)
    st.markdown("---")

    st.markdown(f'<div class="grade-badge">{GRADE_EMOJI[grade]} Class {grade}</div>', unsafe_allow_html=True)
    if st.button("🔄 Change Class", use_container_width=True):
        st.session_state.grade = None
        st.rerun()

    st.markdown("---")
    # D5 — progress tracker (session-level: questions attempted vs correct)
    attempted = [m for m in st.session_state.messages if m.get("role") == "assistant" and m.get("feedback")]
    correct = [m for m in attempted if m.get("feedback") == "correct"]
    st.markdown("**YOUR PROGRESS**")
    if attempted:
        st.progress(len(correct) / len(attempted))
        st.caption(f"⭐ {len(correct)}/{len(attempted)} correct this session")
    else:
        st.progress(0)
        st.caption("Answer a question to start tracking progress!")

    st.markdown("---")
    if st.button("🗑️ Clear chat", use_container_width=True):
        st.session_state.messages = []
        # Tier A: also forget tracked history so the level starts fresh and
        # the student isn't stuck at a level from a previous session.
        if not MOCK_MODE:
            try:
                from scripts.llm import pipeline
                pipeline.reset_student(STUDENT_ID)
            except Exception:
                pass
        st.rerun()

    level = st.session_state.level

st.markdown(f"##### {GRADE_EMOJI[grade]} Class {grade} Maths · grounded in your NCERT textbook")


# ---------------------------------------------------------------------------
# Tier B: episode rendering + unified text/button routing.
# ---------------------------------------------------------------------------
_LABEL_TO_INTENT = {
    "I'll try": None,                 # opens the box; no step, just prompts a try
    "Give me a hint": "HINT",
    "Another hint": "HINT",
    "Show me how": "SOLVE",
    "Just show me": "SOLVE",
    "Show me anyway": "SOLVE",
    "Try again": None,                 # nudge to type an attempt
    "Practice problem": "NEW_QUESTION_PRACTICE",
    "New question": "NEW_QUESTION_UI",
}


def _stream_pending(ep):
    """Stream the current tutor action if it hasn't been streamed yet."""
    if not ep.get("pending_stream"):
        return
    from scripts.llm import controller
    action = ep["action"]
    if action.mode == controller.MODE_HINT:
        # hints render as a tag, consistent with the old look
        hint = "".join(_turn_stream(ep))
        if not (hint or "").strip():
            if st.button("↻ Try again", key=f"retry_{_active_idx()}"):
                st.rerun()  # pending_stream still True -> re-streams
            return
        ep["exchanges"].append({"tutor": None, "student": None,
                                "hint": hint, "hint_n": action.hint_number})
    else:
        text = st.write_stream(_turn_stream(ep))
        if not (text or "").strip():
            # Throttled / empty — keep pending so the child can retry cleanly
            # instead of the turn silently vanishing.
            st.caption("Hmm, I couldn't reach the tutor just now.")
            if st.button("↻ Try again", key=f"retry_{_active_idx()}"):
                st.rerun()
            return
        ep["exchanges"].append({"tutor": text or ep.get("_last_text", ""),
                                "student": None})
        # reveal/co-solve are answer-bearing -> verify + record
        if action.mode in (controller.MODE_REVEAL, controller.MODE_CO_SOLVE):
            _finalize_reveal(ep)
    ep["pending_stream"] = False
    if ep.get("terminal") and not ep.get("thread_note"):
        _write_thread_note(ep)


def _finalize_reveal(ep):
    """After a reveal/co-solve, run verify and (interim) record an attempt."""
    from scripts.llm import verifier
    text = ep["exchanges"][-1]["tutor"]
    ca = ep["state"].computed_answer
    if ca is not None:
        val = verifier._safe_eval(ca)
        ep["verify"] = verifier.check(ep["state"].question, text, computed_value=val)
    else:
        ep["verify"] = None


def _write_thread_note(ep):
    from scripts.llm import memory, controller
    st_ = ep["state"]
    outcome = {controller.SOLVED: "solved", controller.SHOWN: "shown",
               controller.GAVE_UP: "gave_up"}.get(st_.phase, "moved_on")
    note = memory.build_thread_note(st_.question, outcome,
                                    attempts=st_.attempts,
                                    hints=st_.hints_given)
    # store the note on the message so _thread_notes() picks it up next episode
    ep["thread_note"] = note


def render_episode(ep, idx):
    """Render a controller-driven tutoring episode: exchange history + (if the
    active episode) the secondary action buttons beside the open text box."""
    # stream the newest tutor turn if pending (only the active episode is)
    _stream_pending(ep)

    # render exchange history
    for j, ex in enumerate(ep["exchanges"]):
        if ex.get("hint") is not None:
            st.markdown(f'<div class="hint-tag">💡 Hint {ex.get("hint_n","")}: {ex["hint"]}</div>',
                        unsafe_allow_html=True)
        elif ex.get("tutor"):
            # already streamed live on first render; re-show on later reruns
            if not (idx == _active_idx() and j == len(ep["exchanges"]) - 1 and ep.get("_just_streamed")):
                st.write(ex["tutor"])
        if ex.get("student"):
            pass  # student turns show as their own user chat bubbles

    if ep.get("verify"):
        _render_verify_tag(ep["verify"])
    if ep.get("source"):
        st.markdown(f'<div class="source-tag">📖 {ep["source"]}</div>',
                    unsafe_allow_html=True)


def _active_idx():
    idxs = [i for i, m in enumerate(st.session_state.messages)
            if m.get("role") == "assistant"]
    return idxs[-1] if idxs else -1


def _render_verify_tag(verify):
    if not verify:
        return
    match = verify.get("match")
    if match is True:
        st.markdown('<div class="verify-tag">✓ Answer verified</div>',
                    unsafe_allow_html=True)
    elif match is False:
        st.markdown(
            '<div class="verify-tag" style="color: var(--red);">'
            '⚠︎ Let me double-check this one — my working didn\'t line up. '
            'Try it yourself too!</div>',
            unsafe_allow_html=True,
        )


# ---- render transcript -----------------------------------------------------
for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        if msg["role"] == "user":
            st.write(msg["text"])
        else:
            render_episode(msg, i)


# ---- action buttons for the active (non-terminal) episode ------------------
def _handle_intent(ep, intent, turn_text):
    """Route a resolved intent through the controller and rerun."""
    if intent in ("NEW_QUESTION_UI", "NEW_QUESTION_PRACTICE"):
        # end this episode cleanly; a new question starts a fresh one
        from scripts.llm import controller
        controller.step(ep["state"], "NEW_QUESTION", turn_text)
        ep["terminal"] = True
        if not ep.get("thread_note"):
            _write_thread_note(ep)
        if intent == "NEW_QUESTION_PRACTICE":
            st.session_state._pending_practice = True
        st.rerun()
        return
    _advance(ep, intent, turn_text)
    st.rerun()


_active = None
if st.session_state.messages:
    last = st.session_state.messages[-1]
    if last.get("role") == "assistant" and not last.get("terminal"):
        _active = last

if _active is not None:
    st.markdown('<p class="or-type-hint">Tap a shortcut, or just type what you\'re thinking 👇</p>',
                unsafe_allow_html=True)
    btns = _active.get("buttons", [])
    if btns:
        cols = st.columns(len(btns))
        for c, label in zip(cols, btns):
            with c:
                if st.button(label, key=f"act_{_active_idx()}_{label}"):
                    mapped = _LABEL_TO_INTENT.get(label, "ATTEMPT")
                    if mapped is None:
                        # "I'll try" / "Try again": just invite typing, no step
                        st.session_state._nudge = "Go ahead — type your answer or what you're thinking."
                        st.rerun()
                    else:
                        _handle_intent(_active, mapped, f"[{label}]")
    if st.session_state.get("_nudge"):
        st.caption(st.session_state.pop("_nudge"))


# ---- the always-open text box (primary input) ------------------------------
typed = st.chat_input("Type your answer, a question, or how you're thinking…")

if typed:
    st.session_state.messages.append({"role": "user", "text": typed})

    # If there's an active episode, route the text as a mid-episode turn;
    # otherwise it's a brand-new question -> start a fresh episode.
    if _active is not None:
        from scripts.llm import intent as _intent_mod
        resolved = _classify(typed, _active)
        if resolved == "NEW_QUESTION":
            _active = None  # fall through to new-episode start below
        else:
            _advance(_active, resolved, typed)
            st.rerun()

    if _active is None:
        with st.chat_message("assistant"):
            with st.spinner("Finding the right textbook pages…"):
                ep = _start_episode(typed, grade, st.session_state.level)
        st.session_state.messages.append({"role": "assistant", **ep})
        st.rerun()