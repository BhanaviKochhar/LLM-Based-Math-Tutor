"""frontend/state.py -- Streamlit session-state setup, identity, and the
persistent-learner-profile bridge into scripts.llm (student_tracker/pipeline).
"""
from __future__ import annotations

import html
import uuid

import streamlit as st

from frontend.config import MOCK_MODE

ss = st.session_state


def _student_id() -> str:
    """A stable, opaque per-BROWSER-SESSION id -- deliberately NOT the
    child's name (two different children could share a name, and the name
    is just a display greeting, not an identity) and NOT a single hardcoded
    constant shared by every visitor (that would mean two different
    children open in two different browser sessions on the same running app
    would silently share one student_tracker profile/level/history). Full
    authentication is out of scope for this pass; this is the bounded fix
    that keeps identity separate from both Streamlit session state and
    tutoring state so a real auth layer can replace it later without
    touching the tutoring code (see the stabilization brief's identity
    architecture section)."""
    return st.session_state.setdefault("student_id", uuid.uuid4().hex)


def record_feedback(question: str, correct: bool) -> None:
    if MOCK_MODE:
        return
    try:
        from scripts.llm import pipeline
        pipeline.record_feedback(_student_id(), topic=question, correct=correct)
    except Exception:
        pass


def reset_student() -> None:
    if MOCK_MODE:
        return
    try:
        from scripts.llm import pipeline
        pipeline.reset_student(_student_id())
    except Exception:
        pass


def clear_chat(chat) -> None:
    """Clear ONLY this chat's visible conversation and open episode. Does
    NOT touch the persistent student_tracker profile -- that is a separate,
    explicit action (reset_learning_progress) so clearing a chat window can
    never silently erase a child's saved level/history. Previously these
    were bundled into one click; see reset_learning_progress for the other
    half of that split."""
    chat["messages"] = []
    chat["episode"] = None
    chat["thread_notes"] = []
    chat["pending_turn"] = None


def reset_learning_progress() -> None:
    """Explicit, separate action that DOES erase the persistent learner
    profile (student_tracker). Destructive and global across every chat,
    unlike clear_chat — the UI requires its own confirmation step before
    calling this (see render_main_page)."""
    reset_student()


def _current_learner_level() -> str:
    """The REAL backend learner level (beginner/intermediate/advanced) that
    actually drives tutoring depth/thresholds — distinct from the right
    panel's old "Level N" gamification number, which only counted solves in
    THIS chat and reset on every new chat. Showing both under the same word
    "Level" was misleading (two unrelated things sharing a label); this is
    the honest one, reusing the same resolver the live pipeline itself uses
    so the number on screen can never drift from the number that actually
    shapes the tutor's behaviour."""
    if MOCK_MODE:
        return "intermediate"
    try:
        from scripts.llm import pipeline
        return pipeline.resolve_level(_student_id(), ss.level)
    except Exception:
        return "intermediate"


def _top_weak_topic() -> str | None:
    """The single most-missed canonical topic (scripts/llm/topics.py) across
    this student's recorded wrong attempts, or None if there isn't a
    meaningful one yet. Surfaces the Track 16 fix (canonical, aggregatable
    topic tracking) somewhere the child/parent can actually see it -- data
    that is computed but never shown is as good as unused."""
    if MOCK_MODE:
        return None
    try:
        from scripts.llm import student_tracker
        weak = student_tracker.stats(_student_id()).get("weak_topics", [])
        # "Other" is an honest low-confidence bucket, not a real topic name --
        # never surface it as if it were specific, actionable feedback.
        named = [t for t in weak if t != "Other"]
        return named[0] if named else None
    except Exception:
        return None


def change_grade(new_grade: int) -> None:
    """Apply a grade change: update ss.grade and invalidate every chat's
    OPEN episode (never the messages -- past turns stay as a true record of
    what was actually discussed at the old grade).

    An in-progress episode's trusted answer, retrieval, and prompt were all
    computed for the OLD grade's taught form (e.g. a Class 1 episode's
    verifier never injects carrying; a Class 5 one might). Letting it
    silently continue under a new grade would mean a child who just moved
    from Class 3 to Class 5 keeps getting Class-3-shaped hints on a problem
    the controller still thinks is open, or a Class 5 trusted answer
    silently applied to what was asked as a Class 3 problem. Closing the
    episode (not the chat) is the same invariant the onboarding page's grade
    selector already enforces -- this is the shared implementation so an
    in-session control can offer the same safety without leaving the chat.

    A no-op if new_grade == ss.grade (nothing to invalidate)."""
    if new_grade == ss.grade:
        return
    for c in ss.chats:
        c["episode"] = None
    ss.grade = new_grade



# ===========================================================================
# Session defaults
# ===========================================================================
def init_session_state() -> None:
    ss.setdefault("page", "name")
    ss.setdefault("name", "")
    ss.setdefault("name_field", "")
    ss.setdefault("grade", 3)
    # Default to the WEAKEST level, not the middle one -- until
    # student_tracker has 3+ recent attempts to classify from (see
    # pipeline.resolve_level), this UI value IS the tutor's assumption about
    # a brand-new child it knows nothing about yet. "on_track" defaulted
    # every first-ever session to "intermediate" depth (3-4 steps, one
    # example, no explicit definitions) -- live-reported: a first-time
    # explanation of common denominators asserted the answer ("the smallest
    # common denominator for 3 and 9 is 9") without ever showing how to find
    # it. Starting assumed-weak means that same child gets the "define every
    # term, show the method behind every sub-step" beginner treatment until
    # they've actually demonstrated otherwise -- erring toward over-
    # explaining a new student rather than under-explaining one.
    ss.setdefault("level", "needs_practice")
    ss.setdefault("chat_seq", 1)
    ss.setdefault("chats", [{"id": "chat-1", "messages": [], "episode": None, "thread_notes": []}])
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
    # A saved chat not opened yet (frontend/history.py) has no messages
    # loaded, only its stored title.
    return chat.get("title") or "New chat"


def start_new_chat():
    ss.chat_seq += 1
    cid = f"chat-{ss.chat_seq}"
    ss.chats.append({"id": cid, "messages": [], "episode": None, "thread_notes": []})
    ss.active = cid
