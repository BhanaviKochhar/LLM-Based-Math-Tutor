"""frontend/account.py -- the logged-in parent or teacher, per browser session.

Only active when the deployment has a Supabase project (scripts/llm/db.py
configured()). Without one -- local runs, tests, CI -- the app starts on the
name page and keeps progress in data/students.json exactly as before.

Session keys:
  ss.account    None (not chosen yet), "guest" or "parent"
  ss.db_client  the parent's own Supabase client (holds their login)

After login a parent with children lands on the picker page (ss.page "pick");
one with none goes to the name page to add the first. Once a child is
chosen, its database id BECOMES ss.student_id (the id state._student_id()
hands the tutoring code), and db.attach() points student_tracker at the
database for that id. Guests keep the random per-session id and the JSON
file.
"""
from __future__ import annotations

from frontend.config import MOCK_MODE
from frontend.state import change_grade, ss

# Per-child session state, dropped on Switch and Log out so nothing of one
# child's session (chats, name, open problem) carries over to the next.
_CHILD_KEYS = ("student_id", "name", "name_field", "chats", "active", "chat_seq",
               "_show_grade_picker", "_add_child_back", "_confirm_delete_chat")


def accounts_enabled() -> bool:
    if MOCK_MODE:
        return False
    from scripts.llm import db
    return db.configured()


def signed_in() -> bool:
    return ss.get("account") == "parent" and ss.get("db_client") is not None


def continue_as_guest() -> None:
    ss.account = "guest"


def log_in(email: str, password: str, remember: bool) -> None:
    """Raises db.AccountError with a parent-facing message on failure."""
    from scripts.llm import db
    client = db.new_client()
    db.sign_in(client, email.strip(), password)
    _start_parent_session(client, remember)


def reset_password(email: str, code: str, new_password: str) -> None:
    """Finish a forgotten-password reset; the parent is then logged in (and
    remembered on this device, the login form's default)."""
    from scripts.llm import db
    client = db.new_client()
    db.reset_password(client, email.strip(), code.strip(), new_password)
    _start_parent_session(client, remember=True)


def _start_parent_session(client, remember: bool) -> None:
    from scripts.llm import db
    ss.db_client = client
    ss.account = "parent"
    ss["_remember"] = remember
    if remember:
        _remember_device(db.current_refresh_token(client))
    if db.consent_version(client) < db.CONSENT_VERSION:
        # Agreed to an older version of what we keep: ask again first.
        ss.page = "consent"
        return
    _route_after_login()


# ---------------------------------------------------------------------------
# "Keep me logged in on this device"
#
# The parent's refresh token is kept in a browser cookie for 30 days. On a
# new visit sync_cookie() logs back in with it. Supabase issues a new
# refresh token whenever the session is refreshed and the old one stops
# working, so every new token is written back to the cookie; keep_fresh()
# does that refresh once per page interaction (the client's own background
# refresh is off, see db.new_client). A cookie can only be read and written
# by the page, so a change is queued in session state and delivered by the
# cookie component (_cookie_bridge) on the next run.
# ---------------------------------------------------------------------------
COOKIE_NAME = "tt_session"
COOKIE_DAYS = 30


def _remember_device(refresh_token: str | None) -> None:
    if refresh_token and refresh_token != ss.get("_cookie_token"):
        ss["_cookie_token"] = refresh_token
        ss["_cookie_write"] = refresh_token


def _forget_device() -> None:
    ss["_cookie_token"] = None
    ss["_cookie_write"] = ""


def sync_cookie() -> None:
    """Every run, before any page renders: deliver a queued cookie change,
    learn the cookie's current value, and on a fresh visit log back in from
    it."""
    if not accounts_enabled():
        return
    _restore_from(_cookie_bridge())


def _restore_from(token: str | None) -> None:
    # None: the page hasn't reported the cookie yet (it does right after the
    # first render, which reruns the script); try again then.
    if token is None or ss.get("_restore_tried") or ss.get("account") is not None:
        return
    ss["_restore_tried"] = True
    if not token:
        return
    from scripts.llm import db
    client = db.new_client()
    try:
        new_token = db.restore_session(client, token)
    except Exception:
        _forget_device()  # expired or revoked: back to the login page
        return
    ss["_cookie_token"] = None  # force the new token into the cookie
    _remember_device(new_token)
    ss.db_client = client
    ss.account = "parent"
    ss["_remember"] = True
    if db.consent_version(client) < db.CONSENT_VERSION:
        ss.page = "consent"
    else:
        _route_after_login()
    # The old token stopped working the moment this one was issued: run once
    # more straight away so the cookie gets the new one even if the parent
    # leaves without clicking anything.
    import streamlit as st
    st.rerun()


def keep_fresh() -> None:
    """Once per page interaction: refresh the login if its access token has
    expired, and keep a remembered device's cookie on the newest token."""
    if not signed_in():
        return
    from scripts.llm import db
    try:
        token = db.current_refresh_token(ss.db_client)
    except Exception:
        return  # a network blip: the next interaction tries again
    if token and ss.get("_remember"):
        _remember_device(token)


# The page's own cookie is read and written by a small two-way component
# whose JavaScript runs in the app page. st.context.cookies can't be used for
# this: on Streamlit Community Cloud the app sits behind Cloud's proxy and
# this cookie never reaches Python that way (confirmed live).
_COOKIE_JS = """
export default function(component) {
    const { data, setStateValue } = component;
    const name = "%(name)s";
    if (data && typeof data.write === "string") {
        const secure = location.protocol === "https:" ? "; Secure" : "";
        document.cookie = name + "=" + encodeURIComponent(data.write)
            + "; Max-Age=" + (data.write ? %(max_age)d : 0) + "; Path=/; SameSite=Lax" + secure;
    }
    // Reported once per visit only: a reported value starts a new run, and a
    // run started while a click's run is in flight drops that click.
    if (data && data.report) {
        const found = document.cookie.split("; ").find(c => c.startsWith(name + "="));
        setStateValue("token", found ? decodeURIComponent(found.slice(name.length + 1)) : "");
    }
}
""" % {"name": COOKIE_NAME, "max_age": COOKIE_DAYS * 24 * 3600}

_cookie_component = None


def _cookie_bridge() -> str | None:
    """Mount the cookie component: it writes a queued change, then reports
    the cookie (None until the page has reported it once)."""
    global _cookie_component
    import streamlit as st

    if _cookie_component is None:
        _cookie_component = st.components.v2.component("tt_session_cookie", js=_COOKIE_JS)
    write = ss.get("_cookie_write")
    ss["_cookie_write"] = None
    ss["_cookie_seq"] = ss.get("_cookie_seq", 0) + (write is not None)
    result = _cookie_component(
        key="tt_cookie",
        data={"write": write, "seq": ss["_cookie_seq"], "report": not ss.get("_cookie_reported")},
        on_token_change=lambda: None,
    )
    if result.token is not None:
        ss["_cookie_reported"] = True
    return result.token


def agree_to_current_consent() -> None:
    from datetime import datetime, timezone

    from scripts.llm import db
    db.record_consent(ss.db_client, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    _route_after_login()


def _route_after_login() -> None:
    from scripts.llm import db
    # No children yet: the name page asks for the first (see create_child).
    ss.page = "pick" if db.list_children(ss.db_client) else "name"


def register(email: str, password: str, redirect_to: str | None, consent_at: str) -> bool:
    """True when the new account is logged in straight away, False when the
    parent must confirm their email first."""
    from scripts.llm import db
    client = db.new_client()
    if not db.sign_up(client, email.strip(), password, redirect_to, consent_at):
        return False
    ss.db_client = client
    ss.account = "parent"
    return True


def children() -> list[dict]:
    from scripts.llm import db
    return db.list_children(ss.db_client)


def choose_child(child: dict) -> None:
    from frontend import history
    from scripts.llm import db
    ss.student_id = child["id"]
    db.attach(child["id"], ss.db_client)
    ss.name = child["display_name"]
    history.load_for_child()
    change_grade(child["grade"])
    ss.page = "main"


def create_child(display_name: str, grade: int) -> None:
    from scripts.llm import db
    choose_child(db.add_child(ss.db_client, display_name, grade))


def rename_child(student_id: str, display_name: str) -> None:
    from scripts.llm import db
    db.rename_child(ss.db_client, student_id, display_name)


def delete_child(student_id: str) -> None:
    from scripts.llm import db
    db.delete_child(ss.db_client, student_id)


def start_adding_child(can_go_back: bool) -> None:
    """To the name page to add a child; can_go_back offers a way back to the
    picker (False for an account's very first child)."""
    ss.name_field = ""
    ss["_add_child_back"] = can_go_back
    ss.page = "name"


def back_to_picker() -> None:
    ss.pop("_add_child_back", None)
    ss.page = "pick"


def save_grade(grade: int) -> None:
    """Keep the child's profile in step with an in-app class change."""
    if not signed_in() or "student_id" not in ss:
        return
    from scripts.llm import db
    try:
        db.update_grade(ss.db_client, ss.student_id, grade)
    except Exception:
        pass


def _drop_child_session() -> None:
    from scripts.llm import db
    if "student_id" in ss:
        db.detach(ss.student_id)
    for key in _CHILD_KEYS:
        if key in ss:
            del ss[key]


def switch_child() -> None:
    """Back to the picker. The current child's progress and chats are
    already saved (each turn is saved as it finishes)."""
    _drop_child_session()
    ss.page = "pick"


def log_out() -> None:
    from scripts.llm import db
    _drop_child_session()
    if ss.get("db_client") is not None:
        db.sign_out(ss.db_client)
    # A clean slate: the next person at this browser starts at the login page
    # with none of this account's state left behind, and this device is no
    # longer remembered.
    for key in list(ss.keys()):
        del ss[key]
    _forget_device()
    ss["_restore_tried"] = True
