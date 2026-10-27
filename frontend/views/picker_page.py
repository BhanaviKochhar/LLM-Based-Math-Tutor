"""frontend/views/picker_page.py -- "Who's learning today?"

Shown to a logged-in parent or teacher who has at least one child profile:
right after login, and again from the top bar's Switch button. One big card
per child, "Add a child", and a Manage mode to rename or delete profiles.
"""
from __future__ import annotations

import re

import streamlit as st

from frontend import account
from frontend.state import ss
from frontend.views.auth_page import ACCOUNT_CSS, notice
from frontend.views.name_page import render_onboarding_world

_NAME_MAX = 40  # students.display_name check in supabase/schema.sql

_PICKER_CSS = """
<style>
[class*="st-key-pick_"] button {
    font-family: 'Baloo 2', sans-serif !important; width: 100% !important;
    min-height: 64px !important; border-radius: 18px !important;
    background: #ffffff !important; border: 3px solid #f5b301 !important;
    box-shadow: 0 4px 14px rgba(0,0,0,0.10) !important;
    transition: transform .08s ease, box-shadow .12s ease !important;
}
[class*="st-key-pick_"] button p {
    color: #2f4d80 !important; font-weight: 800 !important; font-size: 19px !important;
}
[class*="st-key-pick_"] button:hover {
    transform: translateY(-1px); box-shadow: 0 8px 18px rgba(224,138,30,0.30) !important;
    background: #fff8e6 !important;
}
[class*="st-key-link_"] button {
    background: transparent !important; border: none !important; box-shadow: none !important;
    min-height: 0 !important; padding: 2px 6px !important;
}
[class*="st-key-link_"] button p {
    color: #2f6bea !important; font-weight: 700 !important; font-size: 14px !important;
    text-decoration: underline;
}
</style>
"""


def _plain(text: str) -> str:
    """A child's name as a button label: Streamlit renders labels as
    Markdown, so its control characters are escaped."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|~<>])", r"\\\1", text)


def render_picker_page():
    render_onboarding_world()
    st.markdown(ACCOUNT_CSS + _PICKER_CSS, unsafe_allow_html=True)
    st.markdown('<p class="tt-title">Who\'s learning <span class="accent">today?</span></p>',
                unsafe_allow_html=True)

    try:
        kids = account.children()
    except Exception:
        notice("err", "We couldn't load your children's profiles. Please try again.")
        kids = None
    if kids == []:
        account.start_adding_child(can_go_back=False)
        st.rerun()

    managing = ss.get("_manage_children", False)
    if kids:
        if managing:
            st.markdown('<p class="tt-sub">Rename or delete a profile.</p>', unsafe_allow_html=True)
            _render_manage(kids)
        else:
            st.markdown('<p class="tt-sub">Tap your name to start ✨</p>', unsafe_allow_html=True)
            for child in kids:
                label = f"{_plain(child['display_name'])}  ·  Class {child['grade']}"
                if st.button(label, key=f"pick_{child['id']}", use_container_width=True):
                    account.choose_child(child)
                    st.rerun()

    if not managing:
        if st.button("+ Add a child", key="outline_add", use_container_width=True):
            account.start_adding_child(can_go_back=bool(kids))
            st.rerun()

    left, right = st.columns(2)
    with left:
        if kids and st.button("Done" if managing else "Manage profiles", key="link_manage"):
            ss["_manage_children"] = not managing
            ss.pop("_confirm_delete", None)
            st.rerun()
    with right:
        if st.button("Log out", key="link_logout"):
            account.log_out()
            st.rerun()
    st.stop()


def _render_manage(kids: list[dict]) -> None:
    confirm = ss.get("_confirm_delete")
    for child in kids:
        cid, name = child["id"], child["display_name"]
        if confirm == cid:
            notice("err", f"Delete {name} and all of {name}'s progress? This can't be undone.")
            yes, no = st.columns(2)
            with yes:
                if st.button("Yes, delete", key=f"outline_delyes_{cid}", use_container_width=True):
                    try:
                        account.delete_child(cid)
                    except Exception:
                        notice("err", "We couldn't delete that profile. Please try again.")
                        st.stop()
                    ss.pop("_confirm_delete", None)
                    st.rerun()
            with no:
                if st.button("Cancel", key=f"outline_delno_{cid}", use_container_width=True):
                    ss.pop("_confirm_delete", None)
                    st.rerun()
            continue

        field, save, delete = st.columns([5, 2, 2], vertical_alignment="center")
        with field:
            new_name = st.text_input("Name", value=name, key=f"rename_{cid}",
                                     max_chars=_NAME_MAX, label_visibility="collapsed")
        with save:
            if st.button("Save", key=f"outline_save_{cid}", use_container_width=True):
                new_name = new_name.strip()
                if not new_name:
                    notice("err", "A name can't be empty.")
                elif new_name != name:
                    try:
                        account.rename_child(cid, new_name)
                    except Exception:
                        notice("err", "We couldn't save that name. Please try again.")
                        st.stop()
                    st.rerun()
        with delete:
            if st.button("Delete", key=f"outline_del_{cid}", use_container_width=True):
                ss["_confirm_delete"] = cid
                st.rerun()
