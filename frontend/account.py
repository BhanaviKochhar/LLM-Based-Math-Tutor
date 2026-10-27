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
               "_show_grade_picker", "_add_child_back")


def accounts_enabled() -> bool:
    if MOCK_MODE:
        return False
    from scripts.llm import db
    return db.configured()


def signed_in() -> bool:
    return ss.get("account") == "parent" and ss.get("db_client") is not None


def continue_as_guest() -> None:
    ss.account = "guest"


def log_in(email: str, password: str) -> None:
    """Raises db.AccountError with a parent-facing message on failure."""
    from scripts.llm import db
    client = db.new_client()
    db.sign_in(client, email.strip(), password)
    ss.db_client = client
    ss.account = "parent"
    if db.list_children(client):
        ss.page = "pick"
    # No children yet: the name page asks for the first (see create_child).


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
    from scripts.llm import db
    ss.student_id = child["id"]
    db.attach(child["id"], ss.db_client)
    ss.name = child["display_name"]
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
    """Back to the picker. The current child's progress is already saved;
    their open chat window is not kept (chat history is not stored yet)."""
    _drop_child_session()
    ss.page = "pick"


def log_out() -> None:
    from scripts.llm import db
    _drop_child_session()
    if ss.get("db_client") is not None:
        db.sign_out(ss.db_client)
    # A clean slate: the next person at this browser starts at the login page
    # with none of this account's state left behind.
    for key in list(ss.keys()):
        del ss[key]
