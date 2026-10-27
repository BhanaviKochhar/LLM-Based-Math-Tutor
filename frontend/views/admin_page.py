"""frontend/views/admin_page.py -- the admin dashboard.

Reached from the picker's "Admin dashboard" link, shown only to accounts on
the admins list. Every number comes from one database call,
admin_dashboard() in supabase/schema.sql, which itself refuses anyone not on
that list -- so this page can't leak anything even if someone reaches it.
Totals only: no emails, child names or message text. Test accounts are left
out.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from frontend import account

_CHART_H = 260

_OUTCOME_LABELS = {"solved": "Solved", "shown": "Answer shown",
                   "gave_up": "Gave up", "moved_on": "Moved on"}

_ADMIN_CSS = """
<style>
.tt-admin-head { font-family: 'Baloo 2', sans-serif !important; font-weight: 800 !important;
                 font-size: 30px !important; color: #2f4d80 !important; margin: 0 !important; }
.tt-admin-head .accent { color: #e08a1e; }
.tt-admin-note { color: #5a4a30; font-size: 14px; margin: 0 0 8px 0; }
[data-testid="stMetric"] { background: #ffffff; border: 2px solid #f3deb0;
                           border-radius: 14px; padding: 10px 14px; }
</style>
"""


def _empty() -> None:
    st.caption("No data yet.")


def _frame(rows: list[dict], columns: dict[str, str]) -> pd.DataFrame:
    """Rows from the dashboard bundle as a table with friendly column names."""
    return pd.DataFrame(rows)[list(columns)].rename(columns=columns)


def render_admin_page():
    st.markdown(_ADMIN_CSS, unsafe_allow_html=True)
    top, refresh, back = st.columns([6, 1, 2], vertical_alignment="center")
    with top:
        st.markdown('<p class="tt-admin-head">TinyThinker <span class="accent">admin</span></p>',
                    unsafe_allow_html=True)
        st.markdown('<p class="tt-admin-note">Totals only (no names, emails or messages). '
                    'Test accounts are left out. Times are UTC.</p>', unsafe_allow_html=True)
    with refresh:
        if st.button("Refresh", key="admin_refresh", use_container_width=True):
            st.rerun()
    with back:
        if st.button("← Back to profiles", key="admin_back", use_container_width=True):
            account.back_to_picker()
            st.rerun()

    try:
        d = account.admin_dashboard()
    except Exception:
        st.error("The dashboard is only available to admins, or the database couldn't be "
                 "reached. Please try Refresh.")
        st.stop()

    t = d["totals"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Accounts", t["accounts"])
    c2.metric("Children", t["children"])
    c3.metric("Active children, last 7 days", t["active_7_days"])
    c4.metric("Active children, last 30 days", t["active_30_days"])

    st.subheader("Usage")
    left, right = st.columns(2)
    with left:
        st.markdown("**Active children per day** (last 30 days)")
        rows = d["active_children_per_day"]
        if rows:
            st.bar_chart(_frame(rows, {"day": "Day", "children": "Children"}), x="Day", y="Children", height=_CHART_H)
        else:
            _empty()
    with right:
        st.markdown("**New accounts per week**")
        rows = d["new_accounts_per_week"]
        if rows:
            st.bar_chart(_frame(rows, {"week": "Week starting", "accounts": "Accounts"}),
                         x="Week starting", y="Accounts", height=_CHART_H)
        else:
            _empty()

    st.subheader("Learning")
    left, right = st.columns(2)
    with left:
        st.markdown("**Accuracy per class** (graded answers)")
        rows = d["accuracy_per_class"]
        if rows:
            st.dataframe(_frame(rows, {"class": "Class", "children": "Children",
                                       "answers": "Answers", "percent_correct": "% correct"}),
                         hide_index=True, use_container_width=True)
        else:
            _empty()
        st.markdown("**Children at each tutor level** (last 5 graded answers)")
        rows = d["tutor_levels"]
        if rows:
            st.bar_chart(_frame(rows, {"level": "Level", "children": "Children"}),
                         x="Level", y="Children", horizontal=True, height=_CHART_H)
        else:
            _empty()
    with right:
        st.markdown("**Most-missed topics**")
        rows = d["most_missed_topics"]
        if rows:
            st.dataframe(_frame(rows, {"topic": "Topic", "wrong": "Wrong", "answers": "Answers",
                                       "percent_wrong": "% wrong", "children": "Children"}),
                         hide_index=True, use_container_width=True)
        else:
            _empty()

    st.subheader("Conversations")
    left, right = st.columns(2)
    with left:
        st.markdown("**Chats and messages typed per day** (last 30 days)")
        rows = d["chats_per_day"]
        if rows:
            st.bar_chart(_frame(rows, {"day": "Day", "chats": "Chats", "typed": "Messages typed"}),
                         x="Day", y=["Chats", "Messages typed"], stack=False, height=_CHART_H)
        else:
            _empty()
        per_chat = d["typed_per_chat"] or {}
        if per_chat.get("chats"):
            a, b, c = st.columns(3)
            a.metric("Messages per chat (average)", per_chat["average"])
            b.metric("Median", per_chat["median"])
            c.metric("Most in one chat", per_chat["most"])
    with right:
        st.markdown("**How problems ended**")
        rows = d["problem_outcomes"]
        if rows:
            frame = _frame(rows, {"ended": "Ended", "problems": "Problems"})
            frame["Ended"] = frame["Ended"].map(lambda o: _OUTCOME_LABELS.get(o, o))
            st.bar_chart(frame, x="Ended", y="Problems", horizontal=True, height=_CHART_H)
        else:
            _empty()

    st.subheader("Safety and scope")
    st.caption("Messages stopped by the safety filter, and questions declined as beyond "
               "Class 1-5 maths, per day (last 30 days).")
    rows = d["safety_and_scope_per_day"]
    if rows:
        st.bar_chart(_frame(rows, {"day": "Day", "safety_blocked": "Safety filter",
                                   "scope_declined": "Beyond Class 1-5"}),
                     x="Day", y=["Safety filter", "Beyond Class 1-5"], stack=False, height=_CHART_H)
    else:
        _empty()
    st.stop()
