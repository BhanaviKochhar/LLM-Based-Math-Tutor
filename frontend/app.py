"""frontend/app.py -- TinyThinker entrypoint and page router.

The actual implementation lives in focused modules next to this file:
  frontend/config.py            -- app-wide flags (MOCK_MODE)
  frontend/state.py             -- session state, identity, learner profile
  frontend/markdown_utils.py    -- the **bold**/`code` renderer for replies
  frontend/episode.py           -- controller-driven tutoring episode logic
  frontend/styles/              -- CSS (global chrome + the main chat page)
  frontend/assets/              -- the onboarding illustrated-scene SVGs
  frontend/views/                -- one render_*_page() per screen (not
                                     named "pages/" -- that name is reserved
                                     by Streamlit's own auto-MPA-nav feature,
                                     which hijacked the sidebar when tried)

This file only wires page_config -> session defaults -> global CSS -> the
page router, and re-exports the moved names so existing callers (tests,
eval scripts) that still do `from frontend import app; app.something(...)`
keep working unchanged.

Launch from the repo root so data/ paths resolve:  streamlit run frontend/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Put the repo root on sys.path so `scripts.llm` (and this `frontend`
# package itself) resolve regardless of Streamlit's own working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# st.set_page_config() must be the first Streamlit command that produces
# output, so it runs before any page-rendering import below.
st.set_page_config(page_title="TinyThinker — NCERT Math Tutor", page_icon="🔵", layout="wide")

from frontend.config import MOCK_MODE
from frontend.state import (
    GRADE_LABEL,
    _current_learner_level,
    _student_id,
    _top_weak_topic,
    active_chat,
    change_grade,
    chat_title,
    clear_chat,
    display_name,
    init_session_state,
    record_feedback,
    reset_learning_progress,
    reset_student,
    ss,
    start_new_chat,
)
from frontend.markdown_utils import _markdown_lite
from frontend.episode import (
    _ACTIONABLE_LABELS,
    _BADGES,
    _CLOSE_EPISODE_LABELS,
    _LABEL_TO_INTENT,
    GenerationFailed,
    MOCK_RESPONSES,
    _advance_math_followup,
    _apply_action,
    _friendly_reply,
    _group_chat_history,
    _mock_episode_turn,
    _post_check,
    _progress_to_next_badge,
    _record_outcome,
    _run_generation,
    advance_episode,
    build_active_turns,
    process_pending_turn,
    queue_pending_turn,
    start_episode,
    submit_turn,
)
from frontend.account import accounts_enabled
from frontend.styles.global_css import inject_global_css
from frontend.views.auth_page import render_auth_page
from frontend.views.name_page import _name_page_submit, render_name_page
from frontend.views.main_page import render_chat_reply, render_main_page, render_turn

init_session_state()
inject_global_css()


# A fresh host has no data/chromadb (it is gitignored), so the first run
# builds it from data/extracted_json. Once per server process, and only under
# `streamlit run`, never when tests import this module.
@st.cache_resource(show_spinner="Getting the maths books ready… (first visit after a restart takes a minute or two)")
def _warm_retrieval_index():
    from scripts import retrieval
    retrieval._chroma_collection()


if not MOCK_MODE and st.runtime.exists():
    _warm_retrieval_index()

# ===========================================================================
# Router
#
# When accounts are on (a Supabase project is configured, frontend/account.py),
# the login page comes first; a logged-in parent with a child profile goes
# straight to the chat, one without goes to the name page to create it.
#
# Onboarding is now a single screen: "Let's go" on the name page takes the
# child straight to the chat (ss.page = "main") and queues a brief welcome
# toast (see render_main_page) instead of stopping at a separate full-screen
# "Hi {name}!" page that needed its own extra click to continue.
# ===========================================================================
if ss.page == "name" and ss.get("account") is None and accounts_enabled():
    render_auth_page()
elif ss.page == "name":
    render_name_page()
else:
    render_main_page()
