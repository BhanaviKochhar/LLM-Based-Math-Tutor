import re
import html
import time
import random
import streamlit as st
import streamlit.components.v1 as components

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
        "final_answer": "12",
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
        "final_answer": "1/2",
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
        "final_answer": "42",
        "source": "NCERT Class 2, Chapter 4: Add Our Points",
    },
]


def ask_tutor(question: str, grade: int, level: str = "on_track") -> dict:
    """
    Returns {"answer", "final_answer", "source", "hint1", "hint2", "hint3"}.

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

    NOTE (D6): the UI lets a student type an answer at any hint stage and
    checks it against `final_answer`. If your generate() doesn't yet return a
    clean `final_answer` token, the check gracefully falls back to "reveal the
    explanation to self-check" — but ask Person 3 to include a short
    `final_answer` field so auto-checking works.
    """
    if MOCK_MODE:
        time.sleep(0.6 + random.random() * 0.4)
        return random.choice(MOCK_RESPONSES)

    from llm import ask_tutor as real_ask_tutor

    result = real_ask_tutor(question, grade, level)
    return {
        "answer": result.get("answer", ""),
        "final_answer": result.get("final_answer", ""),
        "source": result.get("source", ""),
        "hint1": result.get("hint1") or result.get("hint") or "Think about what the question is really asking.",
        "hint2": result.get("hint2") or result.get("hint") or "Let's work through the first step together.",
        "hint3": result.get("hint3") or result.get("hint") or "You're almost there — try putting it all together.",
    }


def check_student_answer(student: str, final_answer: str):
    """Returns True/False when we have an answer key, or None when we can't check."""
    if not final_answer:
        return None
    s = student.strip().lower().replace(" ", "").rstrip(".!?")
    c = final_answer.strip().lower().replace(" ", "")
    if not s:
        return None
    if s == c:
        return True
    try:
        if abs(float(s) - float(c)) < 1e-9:
            return True
    except ValueError:
        pass
    tokens = re.findall(r"\d+/\d+|\d+\.?\d*", s)
    if c in tokens:
        return True
    cm = re.fullmatch(r"(\d+)/(\d+)", c)
    if cm:
        for tok in tokens:
            sm = re.fullmatch(r"(\d+)/(\d+)", tok)
            if sm:
                try:
                    if int(sm[1]) * int(cm[2]) == int(cm[1]) * int(sm[2]):
                        return True
                except (ValueError, ZeroDivisionError):
                    pass
    return False


# ---------------------------------------------------------------------------
# Page setup + styling  (Candy-Sky theme)
# ---------------------------------------------------------------------------

st.set_page_config(page_title="TinyThinker — NCERT Math Tutor", page_icon="🧠", layout="wide")

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Baloo+2:wght@600;700;800&family=Fredoka:wght@500;600;700&family=Inter:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap');

:root {
    --indigo: #2b2d89;
    --indigo-soft: #5b5ee0;
    --mustard: #ffc94d;
    --coral: #ff6f59;
    --pink: #ff7eb3;
    --purple: #9b5de5;
    --sky: #4cc9f0;
    --paper: #fffdf9;
    --charcoal: #2c2b3a;
    --charcoal-soft: #5a5a70;
    --line: #e7e2f7;
    --green: #2f9e5a;
    --green-soft: #43c17e;
    --red: #e5484d;
}

/* ---- Dreamy candy-sky background with a faint maths grid on top ---- */
.stApp {
    background-color: #f3ecff;
    background-image:
        linear-gradient(rgba(43, 45, 137, 0.045) 1px, transparent 1px),
        linear-gradient(90deg, rgba(43, 45, 137, 0.045) 1px, transparent 1px),
        radial-gradient(circle at 12% 16%, rgba(255, 126, 179, 0.45), transparent 42%),
        radial-gradient(circle at 88% 12%, rgba(76, 201, 240, 0.42), transparent 40%),
        radial-gradient(circle at 80% 84%, rgba(155, 93, 229, 0.32), transparent 46%),
        radial-gradient(circle at 18% 88%, rgba(255, 201, 77, 0.40), transparent 46%),
        linear-gradient(135deg, #fff4e6, #ffe9f2 38%, #ece7ff 68%, #e3f6ff);
    background-size: 30px 30px, 30px 30px, auto, auto, auto, auto, auto;
    background-attachment: fixed;
    font-family: 'Inter', sans-serif;
    color: var(--charcoal);
    font-size: 17px;
}

.stApp p, .stApp li, .stApp span, .stMarkdown {
    color: var(--charcoal);
    font-size: 17px;
}

h1, h2, h3, h4, h5 {
    font-family: 'Baloo 2', sans-serif !important;
    color: var(--indigo) !important;
}

/* ---------------------------- Sidebar ---------------------------- */
section[data-testid="stSidebar"] {
    background: linear-gradient(200deg, #3a2f9e, #2b2d89 55%, #23256e);
}
section[data-testid="stSidebar"]::after {
    content: "";
    position: absolute; inset: 0; pointer-events: none;
    background:
        radial-gradient(circle at 80% 8%, rgba(255, 126, 179, 0.25), transparent 40%),
        radial-gradient(circle at 10% 92%, rgba(76, 201, 240, 0.22), transparent 42%);
}
section[data-testid="stSidebar"] * { color: var(--paper) !important; }
section[data-testid="stSidebar"] small,
section[data-testid="stSidebar"] .stCaption { color: #d6d7fb !important; }

.brand-title {
    font-family: 'Baloo 2', sans-serif;
    font-weight: 800;
    font-size: 24px;
    color: var(--paper) !important;
    margin-bottom: 0;
}
.brand-sub {
    font-family: 'Space Mono', monospace;
    font-size: 11px;
    letter-spacing: 0.12em;
    color: #cdcefb !important;
    margin-top: -4px;
}

/* Sidebar hello card — bigger name */
.hello-card {
    background: rgba(255, 255, 255, 0.12);
    border: 1px solid rgba(255, 255, 255, 0.22);
    border-radius: 18px;
    padding: 14px 16px;
    margin-bottom: 12px;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.15);
}
.hello-card .who {
    font-family: 'Baloo 2', sans-serif;
    font-weight: 800;
    font-size: 26px;
    color: var(--paper) !important;
    line-height: 1.12;
}
.hello-card .who span {
    color: var(--mustard) !important;
    text-shadow: 0 2px 0 rgba(0,0,0,0.12);
}
.hello-card .role {
    font-family: 'Space Mono', monospace;
    font-size: 11px;
    color: #d6d7fb !important;
    margin-top: 2px;
}

.grade-badge {
    font-family: 'Baloo 2', sans-serif;
    font-weight: 800;
    font-size: 22px;
    background: linear-gradient(135deg, var(--mustard), var(--coral));
    color: #fff !important;
    padding: 12px 14px;
    border-radius: 16px;
    text-align: center;
    margin-bottom: 10px;
    box-shadow: 0 8px 0 rgba(0, 0, 0, 0.14), 0 12px 22px rgba(255, 111, 89, 0.35);
}

/* ------------------- Greeting banner (big name!) ------------------- */
.greeting-banner {
    position: relative;
    overflow: hidden;
    background: linear-gradient(180deg, #ffffff, #fff7fc);
    border: 3px solid #ffffff;
    border-radius: 28px;
    padding: 26px 30px 22px 30px;
    box-shadow: 0 20px 44px rgba(155, 93, 229, 0.22), 0 6px 0 rgba(43, 45, 137, 0.06);
    margin-bottom: 14px;
}
.greeting-banner::before {
    content: "";
    position: absolute; left: 0; top: 0; height: 9px; width: 100%;
    background: linear-gradient(90deg, var(--coral), var(--mustard), var(--green-soft), var(--sky), var(--purple), var(--pink), var(--coral));
    background-size: 250% auto;
    animation: shine 6s linear infinite;
}
.greeting-hi {
    font-family: 'Baloo 2', sans-serif;
    font-weight: 800;
    font-size: clamp(40px, 6.8vw, 66px);
    line-height: 1.04;
    margin: 8px 0 0 0;
}
.grad-name {
    background: linear-gradient(90deg, #ff6f59, #ff7eb3, #9b5de5, #4cc9f0, #43c17e, #ffc94d, #ff6f59);
    background-size: 300% auto;
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    animation: shine 5s linear infinite;
}
.wave {
    display: inline-block;
    transform-origin: 72% 72%;
    animation: wave 1.9s ease-in-out infinite;
}
.greeting-sub {
    font-family: 'Inter', sans-serif;
    color: var(--charcoal-soft) !important;
    font-size: 16px;
    margin: 8px 0 0 0;
}
@keyframes shine { to { background-position: 300% center; } }
@keyframes wave {
    0%, 60%, 100% { transform: rotate(0deg); }
    10% { transform: rotate(16deg); }
    20% { transform: rotate(-8deg); }
    30% { transform: rotate(16deg); }
    40% { transform: rotate(-4deg); }
    50% { transform: rotate(12deg); }
}

/* -------------------------- Chat bubbles -------------------------- */
div[data-testid="stChatMessage"] {
    background-color: var(--paper);
    border: 1px solid var(--line);
    border-radius: 20px;
    box-shadow: 0 12px 26px rgba(43, 45, 137, 0.10);
}
div[data-testid="stChatMessage"] p { color: var(--charcoal) !important; font-size: 17px; }

/* Hint sticky-notes — colour-coded, gradient, playful */
.hint-tag {
    font-family: 'Inter', sans-serif;
    font-size: 16px;
    border-radius: 14px;
    padding: 12px 16px;
    margin: 8px 0;
    line-height: 1.5;
    box-shadow: 0 6px 14px rgba(43, 45, 137, 0.10);
}
.hint-tag b { font-family: 'Baloo 2', sans-serif; }
.hint-1 { background: linear-gradient(135deg, #fff2c9, #ffe39c); border-left: 6px solid var(--mustard); }
.hint-2 { background: linear-gradient(135deg, #ffe1d6, #ffcbb9); border-left: 6px solid var(--coral); }
.hint-3 { background: linear-gradient(135deg, #ece9ff, #d9d5ff); border-left: 6px solid var(--purple); }

/* Worked explanation block */
.answer-block {
    background: linear-gradient(180deg, #ffffff, #f6fff9);
    border: 2px solid #d7f0e0;
    border-left: 7px solid var(--green-soft);
    border-radius: 16px;
    padding: 16px 18px;
    margin: 8px 0 4px 0;
    white-space: pre-wrap;
    font-size: 17px;
    line-height: 1.55;
    box-shadow: 0 10px 22px rgba(47, 158, 90, 0.12);
}

.answer-label {
    font-family: 'Baloo 2', sans-serif;
    font-weight: 700;
    font-size: 16px;
    color: var(--indigo) !important;
    margin: 2px 0 5px 0;
}
.answer-label .opt {
    font-family: 'Space Mono', monospace;
    font-weight: 400;
    font-size: 12px;
    color: var(--charcoal-soft) !important;
}
.next-label {
    font-family: 'Baloo 2', sans-serif;
    font-weight: 700;
    font-size: 16px;
    color: var(--indigo) !important;
    margin: 2px 0 5px 0;
}

.feedback-correct {
    font-family: 'Baloo 2', sans-serif;
    font-weight: 700;
    font-size: 18px;
    color: #1c7a41 !important;
    background: linear-gradient(135deg, #e6f9ee, #d0f4de);
    border: 1px solid #a9e6c1;
    border-radius: 14px;
    padding: 10px 14px;
    margin: 8px 0;
    box-shadow: 0 8px 18px rgba(47, 158, 90, 0.16);
}
.feedback-wrong {
    font-family: 'Baloo 2', sans-serif;
    font-weight: 700;
    font-size: 17px;
    color: #c0343a !important;
    background: linear-gradient(135deg, #fdeaea, #ffd9db);
    border: 1px solid #f4bfc2;
    border-radius: 14px;
    padding: 10px 14px;
    margin: 8px 0;
}
.hint-chip {
    display: inline-block;
    font-family: 'Space Mono', monospace;
    font-size: 12px;
    color: #8a6a00;
    background: #fff4d6;
    border: 1px solid #f0dca0;
    border-radius: 999px;
    padding: 3px 12px;
    margin-top: 4px;
}

.verify-tag {
    font-family: 'Space Mono', monospace;
    font-size: 12px;
    color: var(--green);
    margin-top: 8px;
    display: inline-block;
    background: #e8f7ee;
    border: 1px solid #bfe8cf;
    border-radius: 999px;
    padding: 4px 12px;
}
.source-tag {
    font-family: 'Space Mono', monospace;
    font-size: 12px;
    color: var(--charcoal-soft);
    border-top: 1px dashed var(--line);
    margin-top: 10px;
    padding-top: 7px;
}

/* Worksheet-blank text inputs */
.stTextInput input {
    border: 2px solid var(--indigo-soft);
    border-radius: 14px;
    padding: 13px 15px;
    font-size: 17px;
    font-family: 'Inter', sans-serif;
    color: var(--charcoal);
    background: #ffffff;
    box-shadow: 0 4px 12px rgba(91, 94, 224, 0.10);
}
.stTextInput input:focus {
    border-color: var(--coral);
    box-shadow: 0 0 0 4px rgba(255, 111, 89, 0.18);
}

.stChatInput textarea {
    font-family: 'Inter', sans-serif !important;
    color: white !important;
    font-size: 17px !important;
}
.stChatInput textarea::placeholder { color: rgba(255, 255, 255, 0.6) !important; }

/* Big, bright, bouncy buttons */
.stButton > button {
    font-family: 'Baloo 2', sans-serif;
    font-weight: 800;
    font-size: 18px;
    border-radius: 18px;
    border: 3px solid #ffffff;
    padding: 14px 12px;
    background: linear-gradient(135deg, var(--mustard), var(--coral));
    color: white !important;
    box-shadow: 0 8px 0 rgba(43, 45, 137, 0.18), 0 12px 22px rgba(255, 111, 89, 0.30);
    transition: transform 0.09s ease, box-shadow 0.09s ease;
}
.stButton > button:hover {
    transform: translateY(-3px) scale(1.02);
    box-shadow: 0 11px 0 rgba(43, 45, 137, 0.18), 0 16px 28px rgba(255, 111, 89, 0.38);
}
.stButton > button:active { transform: translateY(1px) scale(0.99); }
.stButton > button p { color: white !important; font-size: 18px !important; }
/* Green "check my answer" primary buttons */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, var(--green-soft), var(--green));
    box-shadow: 0 8px 0 rgba(23, 122, 65, 0.22), 0 12px 22px rgba(47, 158, 90, 0.32);
}

/* Grade picker — extra big on landing */
.grade-picker .stButton > button { font-size: 26px; padding: 28px 10px; width: 100%; }

/* ------------------- Sidebar chat-history list ------------------- */
/* The history rows are real st.buttons (so clicking restores the chat).
   We restyle just those buttons — scoped by their key prefix "hist_" via the
   wrapper Streamlit gives each widget — into a compact, quiet list that reads
   differently from the big candy action buttons. */
section[data-testid="stSidebar"] .stButton > button[kind="secondary"] {
    /* default sidebar secondary buttons stay candy-styled; history rows below
       override this via the element key wrapper */
}
section[data-testid="stSidebar"] div[class*="st-key-hist_"] > .stButton > button,
section[data-testid="stSidebar"] .st-key-hist_ > .stButton > button {
    /* fallback selectors; the reliable one is below */
}
/* Reliable: target buttons whose Streamlit key starts with hist_ */
[class*="st-key-hist_"] button {
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    font-size: 13.5px !important;
    text-align: left !important;
    justify-content: flex-start !important;
    color: #eef0ff !important;
    background: rgba(255, 255, 255, 0.10) !important;
    border: 1px solid rgba(255, 255, 255, 0.18) !important;
    border-radius: 13px !important;
    padding: 9px 12px !important;
    box-shadow: none !important;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    transition: background 0.12s ease, transform 0.12s ease !important;
}
[class*="st-key-hist_"] button p {
    color: #eef0ff !important; font-size: 13.5px !important; font-weight: 600 !important;
}
[class*="st-key-hist_"] button:hover {
    background: rgba(255, 255, 255, 0.20) !important;
    transform: translateX(2px) !important;
    box-shadow: none !important;
}
[class*="st-key-hist_"] button:active { transform: scale(0.99) !important; }

.hist-empty {
    font-family: 'Space Mono', monospace; font-size: 12px;
    color: #cdcefb !important; background: rgba(255, 255, 255, 0.07);
    border: 1px dashed rgba(255, 255, 255, 0.22); border-radius: 12px;
    padding: 11px 12px;
}

/* ---- Scroll anchors for jumping to a question from history ---- */
html { scroll-behavior: smooth; }
.msg-anchor { position: relative; display: block; height: 0; margin: 0; scroll-margin-top: 90px; }

/* ---- Layering: the falling-shapes layer (#tt-falling) is injected at
       z-index:-1 as a child of the app container. We turn the app container
       into a stacking context (position + z-index) so a negative-z child
       paints ABOVE the page gradient but strictly BEHIND all content — even
       content Streamlit leaves unpositioned. Content is also lifted to
       z-index:1 as a belt-and-suspenders measure. ---- */
[data-testid="stAppViewContainer"] { position: relative; z-index: 0; }
[data-testid="stMain"]   { position: relative; z-index: 1; }
[data-testid="stHeader"] { position: relative; z-index: 1; }
/* The sidebar renders above the z-index:-1 shapes on its own (Streamlit gives
   it a stacking context via its collapse transform), so it needs no explicit
   position/z-index here — adding position:relative was breaking its internal
   scroll. Instead, just make sure its content stays scrollable when tall. */
section[data-testid="stSidebar"] > div { height: 100%; overflow-y: auto; }
[data-testid="stSidebarContent"] { overflow-y: auto; max-height: 100vh; }
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def _shape_svg(kind: str, color: str, outline: bool) -> str:
    """One big geometric shape as an inline SVG (filled or outlined)."""
    if outline:
        style = f'fill="none" stroke="{color}" stroke-width="9" stroke-linejoin="round"'
    else:
        style = f'fill="{color}"'
    if kind == "triangle":
        body = f'<polygon points="50,10 90,88 10,88" {style}/>'
    elif kind == "square":
        body = f'<rect x="12" y="12" width="76" height="76" rx="14" {style}/>'
    elif kind == "plus":
        body = (f'<path d="M40 8 h20 v32 h32 v20 h-32 v32 h-20 v-32 '
                f'h-32 v-20 h32 z" {style}/>')
    elif kind == "circle":
        body = f'<circle cx="50" cy="50" r="40" {style}/>'
    elif kind == "diamond":
        body = f'<polygon points="50,8 90,50 50,92 10,50" {style}/>'
    else:  # star
        body = (f'<polygon points="50,6 61,38 96,38 68,59 79,92 50,72 '
                f'21,92 32,59 4,38 39,38" {style}/>')
    return f'<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">{body}</svg>'


def render_falling_shapes():
    """Big geometric shapes drifting top -> bottom across the WHOLE viewport,
    sitting FAINTLY BEHIND all content.

    The layer is injected (via a component-iframe script) as a child of the
    real app container at z-index:-1. Because that container is a stacking
    context (see CSS), a negative-z child paints above the page background but
    behind every content element — including the unpositioned Streamlit blocks
    that previously let the shapes bleed over the chat. Opacity is kept low so
    it reads as background texture, never competing with the question/answer.
    Injecting one level up (rather than via st.markdown, which lands inside
    .block-container) also lets `position: fixed` resolve against the viewport,
    so the shapes spread full-width instead of squashing to one side."""
    palette = ["#ff6f59", "#ffc94d", "#4cc9f0", "#9b5de5", "#ff7eb3", "#43c17e"]
    kinds = ["triangle", "square", "plus", "circle", "diamond", "star"]
    rng = random.Random(42)  # isolated seed so it doesn't disturb the mock RNG

    items = []
    for _ in range(18):
        kind = rng.choice(kinds)
        color = rng.choice(palette)
        outline = rng.random() < 0.45
        left = rng.uniform(-2, 94)
        size = rng.randint(80, 180)          # big, but faint
        dur = rng.uniform(9, 19)
        # Negative delay => shapes are already scattered mid-fall at load time.
        delay = -rng.uniform(0, dur)
        items.append(
            f'<div class="tt-shape" style="left:{left:.1f}%;'
            f'width:{size}px;height:{size}px;'
            f'animation-duration:{dur:.1f}s;animation-delay:{delay:.1f}s;">'
            f'{_shape_svg(kind, color, outline)}</div>'
        )
    items_html = "".join(items)

    js = """
    <script>
    (function () {
      const doc = window.parent.document;
      const CSS = `
        [data-testid="stAppViewContainer"]{position:relative;z-index:0;}
        #tt-falling{position:fixed;inset:0;width:100vw;height:100vh;
          overflow:hidden;pointer-events:none;z-index:-1;}
        #tt-falling .tt-shape{position:absolute;top:-16vh;opacity:0;
          will-change:transform,opacity;
          animation-name:ttfall;animation-timing-function:linear;
          animation-iteration-count:infinite;
          filter:drop-shadow(0 4px 8px rgba(43,45,137,0.08));}
        #tt-falling .tt-shape svg{display:block;width:100%;height:100%;}
        @keyframes ttfall{
          0%{transform:translateY(-20vh) rotate(0deg);opacity:0;}
          10%{opacity:0.16;}
          90%{opacity:0.16;}
          100%{transform:translateY(122vh) rotate(340deg);opacity:0;}
        }
      `;
      if (!doc.getElementById('tt-falling-style')) {
        const s = doc.createElement('style');
        s.id = 'tt-falling-style';
        s.textContent = CSS;
        doc.head.appendChild(s);
      } else {
        doc.getElementById('tt-falling-style').textContent = CSS;
      }
      const old = doc.getElementById('tt-falling');
      if (old) old.remove();
      const layer = doc.createElement('div');
      layer.id = 'tt-falling';
      layer.setAttribute('aria-hidden', 'true');
      layer.innerHTML = `__ITEMS__`;
      const host = doc.querySelector('[data-testid="stAppViewContainer"]')
                || doc.querySelector('.stApp') || doc.body;
      host.appendChild(layer);
    })();
    </script>
    """.replace("__ITEMS__", items_html)

    components.html(js, height=0)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "grade" not in st.session_state:
    st.session_state.grade = None
if "name" not in st.session_state:
    st.session_state.name = ""
if "messages" not in st.session_state:
    st.session_state.messages = []
if "level" not in st.session_state:
    st.session_state.level = "on_track"
# Archived chats — one entry per "Clear chat", titled by its first question.
# This list is NEVER wiped by clearing; it's what feeds the sidebar history.
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "chat_seq" not in st.session_state:
    st.session_state.chat_seq = 0
# Set by a history row click; consumed at the top of the run to restore a chat.
if "restore_chat_id" not in st.session_state:
    st.session_state.restore_chat_id = None
# Message index to smooth-scroll to after the chat renders (set by clicking a
# question in the sidebar history). Consumed once, at the bottom of the run.
if "scroll_to" not in st.session_state:
    st.session_state.scroll_to = None


def _archive_current_chat():
    """Save the live chat into chat_history, titled by its first question."""
    msgs = st.session_state.messages
    if not msgs:
        return
    first_q = next((m.get("text", "") for m in msgs if m.get("role") == "user"), "")
    title = first_q.strip() or "(untitled chat)"
    st.session_state.chat_seq += 1
    st.session_state.chat_history.append({
        "id": f"chat_{st.session_state.chat_seq}",
        "title": title,
        "messages": msgs,           # keep the full chat (hints, solved-state…)
        "created_at": time.time(),
    })


# A history row was clicked last run — archive whatever's open, then load the
# chosen chat back into the workspace before anything else renders.
if st.session_state.restore_chat_id is not None:
    _target_id = st.session_state.restore_chat_id
    st.session_state.restore_chat_id = None
    _entry = next((c for c in st.session_state.chat_history if c["id"] == _target_id), None)
    if _entry is not None:
        # Don't lose the currently-open chat: archive it first (unless it IS
        # the one being restored, or it's empty).
        cur = st.session_state.messages
        cur_first = next((m.get("text", "") for m in cur if m.get("role") == "user"), "").strip()
        if cur and cur_first != _entry["title"]:
            _archive_current_chat()
        # Pull the chosen chat out of the archive and make it the live one.
        st.session_state.chat_history = [
            c for c in st.session_state.chat_history if c["id"] != _target_id
        ]
        st.session_state.messages = _entry["messages"]

level_labels = {
    "needs_practice": "Needs more practice — simpler steps",
    "on_track": "On track — standard explanation",
    "ahead": "Ahead — shorter, less hand-holding",
}

GRADE_EMOJI = {1: "🐣", 2: "🐥", 3: "🦊", 4: "🐼", 5: "🦁"}


def display_name() -> str:
    """A safe, friendly name for greetings."""
    return html.escape(st.session_state.name) if st.session_state.name else "friend"


# ---------------------------------------------------------------------------
# Landing screen — name + grade selection (shown first — D2)
# ---------------------------------------------------------------------------

if st.session_state.grade is None:
    LANDING_CSS = """
    <style>
    .stApp {
        background:
            radial-gradient(circle at 16% 18%, rgba(255, 255, 255, 0.38), transparent 46%),
            radial-gradient(circle at 84% 78%, rgba(255, 255, 255, 0.30), transparent 50%),
            linear-gradient(-45deg, #ffce9e, #ff9ec6, #c39bff, #7ec8ff, #8ff5d4, #ffce9e);
        background-size: auto, auto, 400% 400%;
        animation: gradientShift 15s ease infinite;
    }
    @keyframes gradientShift {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }
    .sparkle-row {
        text-align: center;
        font-size: 28px;
        letter-spacing: 22px;
        animation: twinkle 2s ease-in-out infinite;
    }
    @keyframes twinkle {
        0%, 100% { opacity: 0.4; }
        50% { opacity: 1; }
    }
    .hero-mascot {
        font-size: 108px;
        text-align: center;
        animation: bounce 1.6s ease-in-out infinite;
        filter: drop-shadow(4px 8px 0 rgba(43, 45, 137, 0.18));
    }
    @keyframes bounce {
        0%, 100% { transform: translateY(0) rotate(-4deg); }
        50% { transform: translateY(-24px) rotate(4deg); }
    }
    .hero-title {
        font-family: 'Baloo 2', sans-serif;
        font-weight: 800;
        font-size: 66px;
        text-align: center;
        background: linear-gradient(90deg, #ff6f59, #ffc94d, #43c17e, #4cc9f0, #9b5de5, #ff6f59);
        background-size: 300% auto;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        animation: shine 4s linear infinite;
        margin: 0;
        filter: drop-shadow(2px 3px 0 rgba(255, 255, 255, 0.5));
    }
    @keyframes shine { to { background-position: 300% center; } }
    .hero-sub {
        text-align: center;
        font-family: 'Baloo 2', sans-serif;
        font-size: 24px;
        color: var(--indigo) !important;
        font-weight: 700;
        margin-top: 6px;
        text-shadow: 0 2px 0 rgba(255, 255, 255, 0.55);
    }
    .name-card-label {
        text-align: center;
        font-family: 'Baloo 2', sans-serif;
        font-weight: 800;
        font-size: 22px;
        color: var(--indigo) !important;
        margin-bottom: 4px;
        text-shadow: 0 2px 0 rgba(255, 255, 255, 0.55);
    }
    /* Big cheerful name box */
    .stTextInput input {
        text-align: center;
        font-family: 'Baloo 2', sans-serif !important;
        font-weight: 800;
        font-size: 24px !important;
        border: 4px solid #ffffff !important;
        border-radius: 20px !important;
        box-shadow: 0 12px 26px rgba(43, 45, 137, 0.22);
        background: rgba(255, 255, 255, 0.92) !important;
    }
    /* Live name preview — nice and BIG */
    .name-preview {
        text-align: center;
        font-family: 'Baloo 2', sans-serif;
        font-weight: 800;
        font-size: clamp(34px, 6vw, 56px);
        margin-top: 12px;
        line-height: 1.05;
    }
    .name-preview .np-grad {
        background: linear-gradient(90deg, #ff6f59, #9b5de5, #4cc9f0, #43c17e, #ff6f59);
        background-size: 300% auto;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        animation: shine 4s linear infinite;
    }
    .grade-picker .stButton > button {
        font-size: 26px;
        padding: 30px 10px;
        width: 100%;
        animation: pulse 2.4s ease-in-out infinite;
    }
    @keyframes pulse {
        0%, 100% { box-shadow: 0 8px 0 rgba(43,45,137,0.18), 0 12px 22px rgba(255,111,89,0.30); transform: scale(1); }
        50% { box-shadow: 0 10px 0 rgba(43,45,137,0.18), 0 18px 30px rgba(43,45,137,0.42); transform: scale(1.03); }
    }

    /* Frosted hero card that holds all the landing content */
    .block-container {
        position: relative;
        max-width: 880px;
        margin-top: 20px;
        background: rgba(255, 255, 255, 0.32);
        -webkit-backdrop-filter: blur(11px);
        backdrop-filter: blur(11px);
        border: 2px solid rgba(255, 255, 255, 0.62);
        border-radius: 38px;
        box-shadow: 0 30px 72px rgba(43, 45, 137, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.7);
        padding: 34px 46px 48px;
    }
    /* Floating maths doodles + colour blobs behind the card content */
    .landing-bg {
        position: absolute; inset: 0; z-index: -1;
        overflow: hidden; border-radius: 38px; pointer-events: none;
    }
    .landing-bg .blob { position: absolute; border-radius: 50%; filter: blur(32px); opacity: 0.5; }
    .landing-bg .b1 { width: 260px; height: 260px; left: -60px; top: -40px;
        background: radial-gradient(circle, #ff9ec6, transparent 70%); animation: drift1 17s ease-in-out infinite; }
    .landing-bg .b2 { width: 300px; height: 300px; right: -80px; bottom: -70px;
        background: radial-gradient(circle, #7ec8ff, transparent 70%); animation: drift2 21s ease-in-out infinite; }
    .landing-bg .fl { position: absolute; font-size: 40px; opacity: 0.22;
        animation: floaty 9s ease-in-out infinite; }
    .landing-bg .fa { left: 6%;  top: 24%; }
    .landing-bg .fb { left: 86%; top: 18%; font-size: 46px; animation-delay: 1.2s; }
    .landing-bg .fc { left: 78%; top: 68%; animation-delay: 2.0s; }
    .landing-bg .fd { left: 10%; top: 72%; font-size: 44px; animation-delay: 0.6s; }
    .landing-bg .fe { left: 44%; top: 8%;  animation-delay: 1.7s; }
    .landing-bg .ff { left: 90%; top: 46%; animation-delay: 2.6s; }
    .landing-bg .fg { left: 28%; top: 44%; animation-delay: 3.1s; }
    @keyframes floaty { 0%, 100% { transform: translateY(0) rotate(-6deg); } 50% { transform: translateY(-20px) rotate(6deg); } }
    @keyframes drift1 { 0%, 100% { transform: translate(0, 0); } 50% { transform: translate(36px, 26px); } }
    @keyframes drift2 { 0%, 100% { transform: translate(0, 0); } 50% { transform: translate(-40px, -30px); } }
    </style>
    """
    st.markdown(LANDING_CSS, unsafe_allow_html=True)

    # Falling shapes on the landing screen too (behind the frosted card)
    render_falling_shapes()

    # Decorative floating maths doodles sitting behind the frosted hero card
    st.markdown(
        '<div class="landing-bg">'
        '<div class="blob b1"></div><div class="blob b2"></div>'
        '<span class="fl fa">➕</span><span class="fl fb">✖️</span>'
        '<span class="fl fc">➗</span><span class="fl fd">🔢</span>'
        '<span class="fl fe">⭐</span><span class="fl ff">🧮</span>'
        '<span class="fl fg">➖</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    # keep whatever they typed if they come back to change name/class
    if "name_field" not in st.session_state:
        st.session_state.name_field = st.session_state.name

    st.write("")
    st.markdown('<div class="sparkle-row">✨ 🌟 ✨ 🌟 ✨</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-mascot">🦉</div>', unsafe_allow_html=True)
    st.markdown('<p class="hero-title">TinyThinker</p>', unsafe_allow_html=True)
    st.markdown('<p class="hero-sub">Let\'s make maths super fun today!</p>', unsafe_allow_html=True)
    st.write("")

    # Name input — centred
    nl, nc, nr = st.columns([1, 2, 1])
    with nc:
        st.markdown('<p class="name-card-label">👋 What should we call you?</p>', unsafe_allow_html=True)
        st.text_input(
            "Your name",
            key="name_field",
            placeholder="Type your name…",
            label_visibility="collapsed",
        )

    typed_name = st.session_state.name_field.strip()
    if typed_name:
        st.markdown(
            f'<p class="name-preview">Hi, <span class="np-grad">{html.escape(typed_name)}</span>! 🎉</p>',
            unsafe_allow_html=True,
        )

    st.write("")
    st.markdown('<p class="hero-sub" style="font-size:19px;">👇 Tap your class to begin the adventure 👇</p>', unsafe_allow_html=True)
    st.write("")

    st.markdown('<div class="grade-picker">', unsafe_allow_html=True)
    cols = st.columns(5)
    for i, g in enumerate(range(1, 6)):
        with cols[i]:
            if st.button(f"{GRADE_EMOJI[g]}\n\nClass {g}", key=f"grade_btn_{g}", use_container_width=True):
                st.session_state.name = st.session_state.name_field.strip()
                st.session_state.grade = g
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

# ---------------------------------------------------------------------------
# Falling-shapes background for the main tutoring screen
# ---------------------------------------------------------------------------

render_falling_shapes()

# ---------------------------------------------------------------------------
# Sidebar — hello, grade badge, progress, controls
# ---------------------------------------------------------------------------

grade = st.session_state.grade

with st.sidebar:
    st.markdown('<p class="brand-title">🧠 TinyThinker</p>', unsafe_allow_html=True)
    st.markdown('<p class="brand-sub">NCERT MATHS TUTOR</p>', unsafe_allow_html=True)
    st.markdown("---")

    st.markdown(
        f'<div class="hello-card"><div class="who">Hi, <span>{display_name()}</span>! 👋</div>'
        f'<div class="role">LET\'S SOLVE SOME MATHS</div></div>',
        unsafe_allow_html=True,
    )

    st.markdown(f'<div class="grade-badge">{GRADE_EMOJI[grade]} Class {grade}</div>', unsafe_allow_html=True)
    if st.button("🔄 Change name / class", use_container_width=True):
        st.session_state.grade = None
        st.rerun()

    st.markdown("---")
    # D5 — progress tracker (session-level: questions solved vs attempted)
    attempted = [
        m for m in st.session_state.messages
        if m.get("role") == "assistant" and (m.get("solved") or m.get("revealed"))
    ]
    correct = [m for m in attempted if m.get("solved")]
    st.markdown("**YOUR PROGRESS**")
    if attempted:
        st.progress(len(correct) / len(attempted))
        st.caption(f"⭐ {len(correct)}/{len(attempted)} solved this session")
    else:
        st.progress(0)
        st.caption("Answer a question to start tracking progress!")

    st.markdown("---")
    # ---- Chat history, two views:
    #   • "This chat" — the questions in the chat that's currently open; tap one
    #     to jump (smooth-scroll) to it in the workspace.
    #   • "All chats" — every saved chat (titled by its first question) in an
    #     expander, with that chat's questions listed underneath; tapping a
    #     question reopens the chat and jumps to it.
    # Saved chats live in st.session_state.chat_history and survive clearing. ----
    st.markdown("**🕘 CHAT HISTORY**")
    _view = st.radio(
        "history view",
        ["This chat", "All chats"],
        horizontal=True,
        label_visibility="collapsed",
        key="history_view_radio",
    )

    def _q_list(messages):
        """(message_index, question_text) for each user turn, in order."""
        return [(i, m.get("text", "")) for i, m in enumerate(messages)
                if m.get("role") == "user"]

    if _view == "This chat":
        _qs = _q_list(st.session_state.messages)
        if _qs:
            for _n, (_i, _q) in enumerate(_qs, 1):
                _short = _q if len(_q) <= 38 else _q[:37] + "…"
                if st.button(f"{_n}.  {_short}", key=f"hist_cur_{_i}",
                             use_container_width=True):
                    st.session_state.scroll_to = _i
                    st.rerun()
            st.caption("Tap a question to jump to it")
        else:
            st.markdown(
                '<div class="hist-empty">No questions in this chat yet — '
                'ask one below! 👇</div>',
                unsafe_allow_html=True,
            )
    else:  # All chats
        _any = bool(st.session_state.messages) or bool(st.session_state.chat_history)
        if not _any:
            st.markdown(
                '<div class="hist-empty">No chats yet — ask a question to '
                'start one. 👇</div>',
                unsafe_allow_html=True,
            )
        else:
            # The chat that's open right now (not yet archived) shown first.
            if st.session_state.messages:
                _cur_qs = _q_list(st.session_state.messages)
                _cur_title = (_cur_qs[0][1] if _cur_qs else "(current chat)")
                _cur_short = _cur_title if len(_cur_title) <= 34 else _cur_title[:33] + "…"
                with st.expander(f"💬 {_cur_short}  ·  now", expanded=True):
                    for _n, (_i, _q) in enumerate(_cur_qs, 1):
                        _short = _q if len(_q) <= 34 else _q[:33] + "…"
                        if st.button(f"{_n}.  {_short}", key=f"hist_cur2_{_i}",
                                     use_container_width=True):
                            st.session_state.scroll_to = _i
                            st.rerun()
            # Saved chats, newest first.
            for _entry in reversed(st.session_state.chat_history):
                _title = _entry["title"]
                _short = _title if len(_title) <= 34 else _title[:33] + "…"
                with st.expander(f"💬 {_short}"):
                    _saved_qs = _q_list(_entry["messages"])
                    for _n, (_i, _q) in enumerate(_saved_qs, 1):
                        _qs_short = _q if len(_q) <= 34 else _q[:33] + "…"
                        if st.button(f"{_n}.  {_qs_short}",
                                     key=f"hist_arc_{_entry['id']}_{_i}",
                                     use_container_width=True):
                            # Reopen this chat, then jump to the chosen question.
                            st.session_state.restore_chat_id = _entry["id"]
                            st.session_state.scroll_to = _i
                            st.rerun()
            st.caption("Tap a question to open that chat and jump to it")

    st.markdown("---")
    # Clear chat = archive the current chat (titled by its first question),
    # then wipe the workspace so you start fresh.
    if st.button("🗑️ Clear chat", use_container_width=True):
        _archive_current_chat()
        st.session_state.messages = []
        st.rerun()

    level = st.session_state.level

# ---------------------------------------------------------------------------
# Main header — big greeting
# ---------------------------------------------------------------------------

st.markdown(
    f'<div class="greeting-banner">'
    f'<p class="greeting-hi"><span class="grad-name">Hi, {display_name()}!</span> <span class="wave">👋</span></p>'
    f'<p class="greeting-sub">{GRADE_EMOJI[grade]} Class {grade} Maths · every answer is grounded in your NCERT textbook</p>'
    f'</div>',
    unsafe_allow_html=True,
)


def render_assistant_message(msg, idx):
    """Renders one assistant message.

    Flow (D4/D6):
      • Get Hint 1
      • After Hint 1:  [ type your answer (optional) ]  [ Get Hint 2 ]
      • After Hint 2:  [ type your answer (optional) ]  [ Get Hint 3 ]
      • After Hint 3:  [ type your answer (optional) ]  [ Show Full Explanation ]
    A correct typed answer at any stage solves the question early. Hints stay
    strictly sequential (no skipping).
    """
    hint_level = msg.get("hint_level", 0)
    viewed_hints = msg.get("viewed_hints", 0)
    solved = msg.get("solved", False)

    # --- Hints revealed so far (colour-coded sticky notes) ---
    if hint_level >= 1:
        st.markdown(f'<div class="hint-tag hint-1">💡 <b>Hint 1</b> — {html.escape(msg["hint1"])}</div>', unsafe_allow_html=True)
    if hint_level >= 2:
        st.markdown(f'<div class="hint-tag hint-2">💡 <b>Hint 2</b> — {html.escape(msg["hint2"])}</div>', unsafe_allow_html=True)
    if hint_level >= 3:
        st.markdown(f'<div class="hint-tag hint-3">💡 <b>Hint 3</b> — {html.escape(msg["hint3"])}</div>', unsafe_allow_html=True)

    # --- Feedback on the most recent typed answer ---
    la = msg.get("last_attempt")
    if la and not solved:
        if la["correct"] is False:
            st.markdown(
                f'<div class="feedback-wrong">❌ "{html.escape(la["text"])}" isn\'t quite right — '
                f"that's okay! Grab another hint and have another go.</div>",
                unsafe_allow_html=True,
            )
        elif la["correct"] is None:
            st.markdown(
                f'<div class="hint-chip">✏️ Your answer "{html.escape(la["text"])}" is saved — '
                f"reveal the full explanation to check it.</div>",
                unsafe_allow_html=True,
            )

    # --- Solved early: celebrate, offer the explanation for review ---
    if solved:
        chip = ' <span class="hint-chip">💡 with a hint</span>' if viewed_hints > 0 else ""
        st.markdown(
            f'<div class="feedback-correct">⭐ "{html.escape(la["text"]) if la else ""}" is correct — great job! 🎉{chip}</div>',
            unsafe_allow_html=True,
        )
        if hint_level >= 4:
            _render_full_explanation(msg)
        else:
            if st.button("📖 See the full explanation", key=f"see_{idx}", use_container_width=True):
                msg["hint_level"] = 4
                msg["revealed"] = True
                st.rerun()
        return

    # --- Full explanation revealed (not solved on their own) ---
    if hint_level >= 4:
        _render_full_explanation(msg)
        return

    # --- Level 0: only Get Hint 1 ---
    if hint_level == 0:
        if st.button("💡 Get Hint 1", key=f"hint1_{idx}", use_container_width=True):
            msg["hint_level"] = 1
            msg["viewed_hints"] = viewed_hints + 1
            st.rerun()
        return

    # --- Levels 1–3: answer (left, optional) + next action (right) ---
    left, right = st.columns(2)

    with left:
        st.markdown(
            '<p class="answer-label">✏️ Your answer <span class="opt">(optional)</span></p>',
            unsafe_allow_html=True,
        )
        typed = st.text_input(
            "Your answer",
            key=f"ans_{idx}_{hint_level}",
            placeholder="Type your answer…",
            label_visibility="collapsed",
        )
        if st.button("Check my answer ✅", key=f"check_{idx}_{hint_level}", type="primary", use_container_width=True):
            student = typed.strip()
            if not student:
                st.warning("Type your answer first, then tap check!")
            else:
                verdict = check_student_answer(student, msg.get("final_answer", ""))
                msg["last_attempt"] = {"text": student, "correct": verdict}
                if verdict is True:
                    msg["solved"] = True
                st.rerun()

    with right:
        if hint_level == 1:
            st.markdown('<p class="next-label">Need more help?</p>', unsafe_allow_html=True)
            if st.button("💡 Get Hint 2", key=f"hint2_{idx}", use_container_width=True):
                msg["hint_level"] = 2
                msg["viewed_hints"] = viewed_hints + 1
                st.rerun()
        elif hint_level == 2:
            st.markdown('<p class="next-label">Need more help?</p>', unsafe_allow_html=True)
            if st.button("💡 Get Hint 3", key=f"hint3_{idx}", use_container_width=True):
                msg["hint_level"] = 3
                msg["viewed_hints"] = viewed_hints + 1
                st.rerun()
        elif hint_level == 3:
            st.markdown('<p class="next-label">Still stuck?</p>', unsafe_allow_html=True)
            if st.button("📖 Show Full Explanation", key=f"full_{idx}", use_container_width=True):
                msg["hint_level"] = 4
                msg["revealed"] = True
                st.rerun()


def _render_full_explanation(msg):
    """The worked, verified explanation + textbook source."""
    st.markdown(f'<div class="answer-block">{html.escape(msg["answer"])}</div>', unsafe_allow_html=True)
    st.markdown('<div class="verify-tag">✓ Answer verified</div>', unsafe_allow_html=True)
    if msg.get("source"):
        st.markdown(f'<div class="source-tag">📖 {html.escape(msg["source"])}</div>', unsafe_allow_html=True)


for i, msg in enumerate(st.session_state.messages):
    # Invisible anchor the sidebar "jump to question" scrolls to.
    st.markdown(f'<div class="msg-anchor msg-anchor-{i}"></div>', unsafe_allow_html=True)
    with st.chat_message(msg["role"]):
        if msg["role"] == "user":
            st.write(msg["text"])
        else:
            render_assistant_message(msg, i)

# If a sidebar history question was tapped, smooth-scroll to it now (once).
if st.session_state.scroll_to is not None:
    _sc = st.session_state.scroll_to
    st.session_state.scroll_to = None
    components.html(
        """
        <script>
        (function () {
          const doc = window.parent.document;
          function go(tries) {
            const el = doc.querySelector('.msg-anchor-__SC__');
            if (el) {
              el.scrollIntoView({ behavior: 'smooth', block: 'start' });
              const bubble = el.nextElementSibling;
              if (bubble) {
                bubble.style.transition = 'box-shadow 0.3s ease';
                const prev = bubble.style.boxShadow;
                bubble.style.boxShadow = '0 0 0 4px rgba(255,111,89,0.55)';
                setTimeout(function () { bubble.style.boxShadow = prev; }, 1200);
              }
            } else if (tries > 0) {
              setTimeout(function () { go(tries - 1); }, 120);
            }
          }
          go(20);
        })();
        </script>
        """.replace("__SC__", str(_sc)),
        height=0,
    )

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
            "final_answer": result.get("final_answer", ""),
            "source": result.get("source", ""),
            "hint1": result.get("hint1", "Think about the first step you'd take."),
            "hint2": result.get("hint2", "Try working through it slowly, one part at a time."),
            "hint3": result.get("hint3", "You're almost there — try putting it all together."),
            "hint_level": 0,
            "viewed_hints": 0,
            "solved": False,
            "revealed": False,
            "last_attempt": None,
        }
        st.session_state.messages.append(new_msg)
        render_assistant_message(new_msg, len(st.session_state.messages) - 1)
    # Rerun so the sidebar history + scroll anchors pick up the new question.
    st.rerun()
