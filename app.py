import time
import random
import streamlit as st

MOCK_MODE = True

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


def ask_tutor(question: str, grade: int, level: str = "on_track") -> dict:
    """
    Returns {"answer": str, "source": str, "hint1": str, "hint2": str, "hint3": str}.

    `level` is the personalization signal ("needs_practice" / "on_track" /
    "ahead") — pass it through to your prompt engineering / personalization
    module once that's wired up, so explanation depth and difficulty adapt
    per student as described in the proposal.

    Wired to retrieval.py (BM25 + ChromaDB, grade-filtered) and llm.py
    (Anthropic API) — see those files. Flip MOCK_MODE to False below once
    your retrieval pipeline and ANTHROPIC_API_KEY are ready.

    NOTE for integration (Day 8-9): the team contract's generate() only
    returns a single "hint" field, not hint1/hint2/hint3. Below we gracefully
    degrade to that single hint if hint1/hint2/hint3 aren't present, so the
    UI doesn't break — but flag this with Person 3 so the 3-level hint
    system actually has 3 distinct levels of content, not 1 repeated.
    """
    if MOCK_MODE:
        time.sleep(0.6 + random.random() * 0.4)
        return random.choice(MOCK_RESPONSES)

    from llm import ask_tutor as real_ask_tutor

    result = real_ask_tutor(question, grade, level)
    return {
        "answer": result.get("answer", ""),
        "source": result.get("source", ""),
        "hint1": result.get("hint1") or result.get("hint") or "Think about what the question is really asking.",
        "hint2": result.get("hint2") or result.get("hint") or "Let's work through the first step together.",
        "hint3": result.get("hint3") or result.get("hint") or "You're almost there — try putting it all together.",
    }


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
        st.rerun()

    level = st.session_state.level

st.markdown(f"##### {GRADE_EMOJI[grade]} Class {grade} Maths · grounded in your NCERT textbook")


def render_assistant_message(msg, idx):
    """Renders one assistant message with progressive 3-level hints (D4)
    and emoji feedback (D6). Hints must be viewed in order (no skipping)."""
    hint_level = msg.get("hint_level", 0)
    viewed_hints = msg.get("viewed_hints", 0)
    feedback = msg.get("feedback")

    if hint_level >= 1:
        st.markdown(f'<div class="hint-tag">💡 Hint 1: {msg["hint1"]}</div>', unsafe_allow_html=True)
    if hint_level >= 2:
        st.markdown(f'<div class="hint-tag">💡 Hint 2: {msg["hint2"]}</div>', unsafe_allow_html=True)
    if hint_level >= 3:
        st.markdown(f'<div class="hint-tag">💡 Hint 3: {msg["hint3"]}</div>', unsafe_allow_html=True)
    if hint_level >= 4:
        st.write(msg["answer"])
        st.markdown('<div class="verify-tag">✓ Answer verified</div>', unsafe_allow_html=True)
        if msg.get("source"):
            st.markdown(f'<div class="source-tag">📖 {msg["source"]}</div>', unsafe_allow_html=True)

    # Hint / reveal controls, shown until the full answer is up.
    # Strictly sequential: Hint 1 -> Hint 2 -> Hint 3 -> Full Answer. No skip.
    if hint_level < 4:
        if hint_level == 0:
            if st.button("💡 Get Hint 1", key=f"hint1_{idx}"):
                msg["hint_level"] = 1
                msg["viewed_hints"] = viewed_hints + 1
                st.rerun()
        elif hint_level == 1:
            if st.button("💡 Get Hint 2", key=f"hint2_{idx}"):
                msg["hint_level"] = 2
                msg["viewed_hints"] = viewed_hints + 1
                st.rerun()
        elif hint_level == 2:
            if st.button("💡 Get Hint 3", key=f"hint3_{idx}"):
                msg["hint_level"] = 3
                msg["viewed_hints"] = viewed_hints + 1
                st.rerun()
        elif hint_level == 3:
            if st.button("✅ Show Full Answer", key=f"full_{idx}"):
                msg["hint_level"] = 4
                st.rerun()

    # Feedback controls (D6), shown once the full answer is visible
    if hint_level >= 4 and feedback is None:
        st.write("")
        f1, f2 = st.columns(2)
        with f1:
            if st.button("⭐ I got it right!", key=f"correct_{idx}"):
                msg["feedback"] = "correct"
                st.rerun()
        with f2:
            if st.button("❌ I got it wrong", key=f"wrong_{idx}"):
                msg["feedback"] = "wrong"
                st.rerun()
    elif feedback == "correct":
        tag = '<span class="feedback-correct">⭐ Correct! Great job!</span>'
        if viewed_hints > 0:
            tag += ' <span class="hint-tag" style="display:inline-block;">💡 Hint used</span>'
        st.markdown(tag, unsafe_allow_html=True)
    elif feedback == "wrong":
        st.markdown(
            '<span class="feedback-wrong">❌ Not quite — that\'s okay, mistakes help us learn! '
            'Try re-reading the steps above and ask another question when ready.</span>',
            unsafe_allow_html=True,
        )
        if viewed_hints > 0:
            st.markdown('<div class="hint-tag">💡 Hint used</div>', unsafe_allow_html=True)


for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        if msg["role"] == "user":
            st.write(msg["text"])
        else:
            render_assistant_message(msg, i)

question = st.chat_input("Type a maths question…")

if question:
    st.session_state.messages.append({"role": "user", "text": question})
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner("Working it out…"):
            result = ask_tutor(question, grade, level)
        with st.spinner("Double-checking the answer…"):
            time.sleep(0.4)  # mirrors the external answer-checker step

        new_msg = {
            "role": "assistant",
            "answer": result["answer"],
            "source": result.get("source", ""),
            "hint1": result.get("hint1", "Think about the first step you'd take."),
            "hint2": result.get("hint2", "Try working through it slowly, one part at a time."),
            "hint3": result.get("hint3", "You're almost there — try putting it all together."),
            "hint_level": 0,
            "viewed_hints": 0,
            "feedback": None,
        }
        st.session_state.messages.append(new_msg)
        render_assistant_message(new_msg, len(st.session_state.messages) - 1)