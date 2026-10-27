"""frontend/views/auth_page.py -- the first screen when accounts are on.

A parent or teacher logs in or creates an account (with consent for the
child's data), or anyone can try the tutor without one. Shown only when
frontend.account.accounts_enabled(); otherwise the app opens on the name page
as before.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

import streamlit as st

from frontend import account
from frontend.views.name_page import render_onboarding_world

_MIN_PASSWORD = 8

CONSENT_LABEL = ("I'm this child's parent, guardian or teacher, and I agree to "
                 "TinyThinker keeping my child's first name, class and practice results.")

PRIVACY_NOTE = """
**What TinyThinker keeps**

- Your email address, so you can log in.
- Your child's first name and class.
- Which practice questions your child got right or wrong, so the tutor can
  pick up at the right level next time.

We don't ask for surnames, photos, age or school. The questions your child
types are sent to an AI service to write the tutor's replies.

You can reset your child's progress at any time. To delete the account and
everything in it, contact the TinyThinker team.
"""


# Shared by the account screens (this page and views/picker_page.py): the
# outlined secondary button (any key starting "outline_") and the readable
# message boxes written by notice().
ACCOUNT_CSS = """
<style>
    [class*="st-key-outline_"] button {
        font-family: 'Baloo 2', sans-serif !important; font-weight: 700 !important;
        width: 100% !important; border-radius: 14px !important; padding: 10px !important;
        background: #ffffff !important; color: #2f4d80 !important;
        border: 2px solid #f5b301 !important;
    }
    [class*="st-key-outline_"] button p { color: #2f4d80 !important; font-weight: 700 !important; }
    .tt-or { text-align: center; color: #7a6a52; font-weight: 700; margin: 10px 0 6px; }
    .tt-notice {
        font-family: 'Nunito', sans-serif; font-weight: 700; font-size: 15px;
        line-height: 1.45; border-radius: 12px; padding: 12px 16px; margin: 10px 0 4px;
        border: 2px solid; background: #ffffff;
    }
    .tt-notice.ok { color: #1d5a32; border-color: #3a9d5d; background: #eef8f1; }
    .tt-notice.err { color: #8a1c1c; border-color: #d64545; background: #fdf0f0; }
</style>
"""


def render_auth_page():
    render_onboarding_world()
    st.markdown(ACCOUNT_CSS, unsafe_allow_html=True)
    st.markdown('<p class="tt-title">Welcome, <span class="accent">Tiny&nbsp;Thinker!</span></p>',
                unsafe_allow_html=True)
    st.markdown('<p class="tt-sub">Grown-ups: log in to save your child\'s progress ✨</p>',
                unsafe_allow_html=True)

    log_in_tab, register_tab = st.tabs(["Log in", "Create account"])

    with log_in_tab:
        with st.form("login_form", border=False):
            email = st.text_input("Email", key="login_email", placeholder="Email address",
                                  label_visibility="collapsed")
            password = st.text_input("Password", key="login_password", type="password",
                                     placeholder="Password", label_visibility="collapsed")
            submitted = st.form_submit_button("Log in →", key="go_btn_login",
                                              use_container_width=True)
        if submitted:
            if not email.strip() or not password:
                notice("err", "Please enter your email and password.")
            else:
                try:
                    account.log_in(email, password)
                except Exception as exc:
                    notice("err", _message(exc))
                else:
                    st.rerun()

    with register_tab:
        with st.form("register_form", border=False):
            new_email = st.text_input("Email", key="register_email", placeholder="Email address",
                                      label_visibility="collapsed")
            new_password = st.text_input("Password", key="register_password", type="password",
                                         placeholder=f"Password (at least {_MIN_PASSWORD} characters)",
                                         label_visibility="collapsed")
            repeat = st.text_input("Repeat password", key="register_repeat", type="password",
                                   placeholder="Repeat password", label_visibility="collapsed")
            consent = st.checkbox(CONSENT_LABEL, key="register_consent")
            with st.expander("What we keep and why"):
                st.markdown(PRIVACY_NOTE)
            created = st.form_submit_button("Create account →", key="go_btn_register",
                                            use_container_width=True)
        if created:
            problem = _registration_problem(new_email, new_password, repeat, consent)
            if problem:
                notice("err", problem)
            else:
                try:
                    logged_in = account.register(
                        new_email, new_password, redirect_to=None,
                        consent_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    )
                except Exception as exc:
                    notice("err", _message(exc))
                else:
                    if logged_in:
                        st.rerun()
                    notice("ok", "Almost done! We've sent you an email. Open the link in it to "
                               "confirm your address, then come back here and log in.")

    st.markdown('<div class="tt-or">or</div>', unsafe_allow_html=True)
    if st.button("Try without an account", key="outline_guest", use_container_width=True):
        account.continue_as_guest()
        st.rerun()
    st.stop()


def notice(kind: str, text: str) -> None:
    """A readable message box: dark text on a pale tint with a strong border
    (Streamlit's own success/error boxes are pale-on-pale on this card)."""
    st.markdown(f'<div class="tt-notice {kind}">{html.escape(text)}</div>', unsafe_allow_html=True)


def _registration_problem(email: str, password: str, repeat: str, consent: bool) -> str | None:
    if "@" not in email or "." not in email.split("@")[-1]:
        return "Please enter a valid email address."
    if len(password) < _MIN_PASSWORD:
        return f"Please choose a password with at least {_MIN_PASSWORD} characters."
    if password != repeat:
        return "The two passwords don't match."
    if not consent:
        return "Please tick the box to agree before creating an account."
    return None


def _message(exc: Exception) -> str:
    from scripts.llm import db
    if isinstance(exc, db.AccountError):
        return str(exc)
    return "We couldn't reach the server just now. Please try again."
