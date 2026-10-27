"""frontend/account.py -- the logged-in parent or teacher, per browser session.

Only active when the deployment has a Supabase project (scripts/llm/db.py
configured()). Without one -- local runs, tests, CI -- the app starts on the
name page and keeps progress in data/students.json exactly as before.

Session keys:
  ss.account    None (not chosen yet), "guest" or "parent"
  ss.db_client  the parent's own Supabase client (holds their login)

Once a child profile is chosen, its database id BECOMES ss.student_id (the
id state._student_id() hands the tutoring code), and db.attach() points
student_tracker at the database for that id. Guests keep the random
per-session id and the JSON file.
"""
from __future__ import annotations

from frontend.config import MOCK_MODE
from frontend.state import change_grade, ss


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
    child = db.first_child(client)
    if child:
        _use_child(child)
    # No child yet: the name page asks for one (see create_child).


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


def create_child(display_name: str, grade: int) -> None:
    from scripts.llm import db
    _use_child(db.add_child(ss.db_client, display_name, grade))


def _use_child(child: dict) -> None:
    from scripts.llm import db
    ss.student_id = child["id"]
    db.attach(child["id"], ss.db_client)
    ss.name = child["display_name"]
    change_grade(child["grade"])
    ss.page = "main"


def save_grade(grade: int) -> None:
    """Keep the child's profile in step with an in-app class change."""
    if not signed_in() or "student_id" not in ss:
        return
    from scripts.llm import db
    try:
        db.update_grade(ss.db_client, ss.student_id, grade)
    except Exception:
        pass


def log_out() -> None:
    from scripts.llm import db
    if "student_id" in ss:
        db.detach(ss.student_id)
    if ss.get("db_client") is not None:
        db.sign_out(ss.db_client)
    # A clean slate: the next person at this browser starts at the login page
    # with none of this child's chats, name or level left behind.
    for key in list(ss.keys()):
        del ss[key]
