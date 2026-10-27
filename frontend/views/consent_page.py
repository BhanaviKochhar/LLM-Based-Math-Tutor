"""frontend/views/consent_page.py -- agree to an updated privacy promise.

Shown once after login to a parent or teacher who agreed to an older version
of what TinyThinker keeps (scripts/llm/db.py CONSENT_VERSION). Nothing new is
kept until they agree; they can log out instead.
"""
from __future__ import annotations

import streamlit as st

from frontend import account
from frontend.views.auth_page import ACCOUNT_CSS, CONSENT_LABEL, PRIVACY_NOTE, notice
from frontend.views.name_page import render_onboarding_world


def render_consent_page():
    render_onboarding_world()
    st.markdown(ACCOUNT_CSS, unsafe_allow_html=True)
    st.markdown('<p class="tt-title">Something <span class="accent">new</span></p>',
                unsafe_allow_html=True)
    st.markdown('<p class="tt-sub">TinyThinker can now save your child\'s chats, so they '
                'can be reopened later. Please read and agree to continue.</p>',
                unsafe_allow_html=True)
    with st.expander("What we keep and why", expanded=True):
        st.markdown(PRIVACY_NOTE)
    agreed = st.checkbox(CONSENT_LABEL, key="reconsent_box")
    if st.button("Agree and continue →", key="go_btn_reconsent", use_container_width=True):
        if not agreed:
            notice("err", "Please tick the box to agree, or log out below.")
        else:
            try:
                account.agree_to_current_consent()
            except Exception:
                notice("err", "We couldn't save that just now. Please try again.")
                st.stop()
            st.rerun()
    if st.button("Log out", key="outline_reconsent_logout", use_container_width=True):
        account.log_out()
        st.rerun()
    st.stop()
