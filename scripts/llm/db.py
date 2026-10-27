"""Supabase storage for logged-in children's progress, plus the account calls
the login page needs.

student_tracker stays the one entry point the tutoring code uses (record,
stats, classify, reset). When a parent logs in and picks a child, the
frontend attach()es that child's id to the parent's Supabase client;
student_tracker then reads and writes that child's progress here instead of
data/students.json. Anyone not attached -- a guest, an eval run, the test
suites, or any run without SUPABASE_URL/SUPABASE_ANON_KEY -- keeps using the
JSON file exactly as before.

Every client here is built from the PUBLIC anon key and carries the logged-in
parent's own session, so the Row Level Security policies in
supabase/schema.sql decide what it can touch. The service-role key is never
used.

`supabase` is imported lazily so this module (and student_tracker, which
imports it) loads without the package installed.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass

try:  # pragma: no cover - trivial
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

# Fail fast on a slow or unreachable database rather than holding up a
# child's turn; a failed write is dropped (see student_tracker callers).
_DB_TIMEOUT_S = 10


def configured() -> bool:
    """True when this deployment has a Supabase project to log in to."""
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_ANON_KEY"))


def new_client():
    """A fresh client for ONE browser session. Never share one between
    sessions: it holds that parent's login."""
    from supabase import ClientOptions, create_client

    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_ANON_KEY"],
        options=ClientOptions(postgrest_client_timeout=_DB_TIMEOUT_S),
    )


# ---------------------------------------------------------------------------
# Progress for one attached child
# ---------------------------------------------------------------------------
@dataclass
class ProgressStore:
    client: object
    student_id: str

    def record(self, topic: str, correct: bool) -> None:
        self.client.table("attempts").insert(
            {"student_id": self.student_id, "topic": topic, "correct": bool(correct)}
        ).execute()

    def summary(self, window: int) -> dict:
        """The same shape student_tracker keeps per student in the JSON
        file: attempts, correct, weak_topics (topic -> wrong count, in
        first-missed order) and recent (last `window` outcomes, oldest
        first)."""
        data = self.client.rpc(
            "student_summary", {"p_student_id": self.student_id, "p_window": window}
        ).execute().data
        return {
            "attempts": data["attempts"],
            "correct": data["correct"],
            "weak_topics": {topic: n for topic, n in data["weak_topics"]},
            "recent": data["recent"],
        }

    def reset(self) -> None:
        self.client.table("attempts").delete().eq("student_id", self.student_id).execute()


_stores: dict[str, ProgressStore] = {}
_stores_lock = threading.Lock()


def attach(student_id: str, client) -> None:
    with _stores_lock:
        _stores[student_id] = ProgressStore(client, student_id)


def detach(student_id: str) -> None:
    with _stores_lock:
        _stores.pop(student_id, None)


def store_for(student_id: str | None) -> ProgressStore | None:
    if not student_id:
        return None
    with _stores_lock:
        return _stores.get(student_id)


# ---------------------------------------------------------------------------
# Accounts and child profiles (called by frontend/views/auth_page.py)
# ---------------------------------------------------------------------------
# Supabase Auth error codes -> what a parent should read. Anything else
# falls back to a generic message rather than showing raw API text.
_AUTH_MESSAGES = {
    "invalid_credentials": "That email and password don't match. Please try again.",
    "email_not_confirmed": "Please confirm your email first: open the link we sent you, then log in.",
    "user_already_exists": "There's already an account with that email. Try logging in instead.",
    "weak_password": "Please choose a stronger password (at least 8 characters).",
    "over_email_send_rate_limit": "We've sent too many emails in the last hour. Please try again a bit later.",
    "over_request_rate_limit": "Too many attempts. Please wait a minute and try again.",
    "email_address_invalid": "That doesn't look like a valid email address.",
}


class AccountError(Exception):
    """A sign-up or login problem, with a message fit to show a parent."""


def _auth_error(exc: Exception) -> AccountError:
    code = getattr(exc, "code", None)
    return AccountError(_AUTH_MESSAGES.get(code, "Something went wrong. Please try again."))


def sign_up(client, email: str, password: str, redirect_to: str | None, consent_at: str) -> bool:
    """Register a parent or teacher account. Returns True when they are
    logged in straight away, False when they must confirm their email
    first. consent_at (ISO time the consent box was ticked) is kept in the
    account's own metadata as the record of that consent."""
    options = {"data": {"consent_at": consent_at}}
    if redirect_to:
        options["email_redirect_to"] = redirect_to
    try:
        res = client.auth.sign_up({"email": email, "password": password, "options": options})
    except Exception as exc:
        raise _auth_error(exc) from exc
    return res.session is not None


def sign_in(client, email: str, password: str) -> None:
    try:
        client.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as exc:
        raise _auth_error(exc) from exc


def sign_out(client) -> None:
    try:
        client.auth.sign_out()
    except Exception:
        pass


def first_child(client) -> dict | None:
    """The account's child profile (one per account for now), or None."""
    rows = (client.table("students").select("id, display_name, grade")
            .order("created_at").limit(1).execute().data)
    return rows[0] if rows else None


def add_child(client, display_name: str, grade: int) -> dict:
    return (client.table("students")
            .insert({"display_name": display_name, "grade": grade})
            .execute().data[0])


def update_grade(client, student_id: str, grade: int) -> None:
    client.table("students").update({"grade": grade}).eq("id", student_id).execute()
