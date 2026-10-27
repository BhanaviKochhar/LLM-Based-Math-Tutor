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

    # No background token refresh: the app refreshes once per page
    # interaction instead (frontend/account.py keep_fresh), so a new token
    # can be written to the "keep me logged in" cookie in the same step.
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_ANON_KEY"],
        options=ClientOptions(postgrest_client_timeout=_DB_TIMEOUT_S, auto_refresh_token=False),
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
    "otp_expired": "That code is wrong or has expired. Please ask for a new one.",
    "same_password": "Please choose a password different from your old one.",
    "refresh_token_not_found": "Please log in again.",
    "refresh_token_already_used": "Please log in again.",
    "session_expired": "Please log in again.",
}


class AccountError(Exception):
    """A sign-up or login problem, with a message fit to show a parent."""


def _auth_error(exc: Exception) -> AccountError:
    code = getattr(exc, "code", None)
    return AccountError(_AUTH_MESSAGES.get(code, "Something went wrong. Please try again."))


def sign_up(client, email: str, password: str, redirect_to: str | None, consent_at: str) -> bool:
    """Register a parent or teacher account. Returns True when they are
    logged in straight away, False when they must confirm their email
    first. consent_at (ISO time the consent box was ticked) and the consent
    version are kept in the account's own metadata as the record of that
    consent."""
    options = {"data": {"consent_at": consent_at, "consent_version": CONSENT_VERSION}}
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


def restore_session(client, refresh_token: str) -> str:
    """Log a fresh client back in from a remembered refresh token. Returns
    the NEW refresh token (Supabase issues a new one each time; the old one
    stops working)."""
    try:
        return client.auth.refresh_session(refresh_token).session.refresh_token
    except Exception as exc:
        raise _auth_error(exc) from exc


def current_refresh_token(client) -> str | None:
    """The session's refresh token, refreshing the session first if its
    access token has expired (so the client's requests keep working)."""
    session = client.auth.get_session()
    return session.refresh_token if session else None


def send_reset_code(client, email: str) -> None:
    """Email a 6-digit password-reset code (the Reset Password email
    template must show {{ .Token }}). Supabase answers the same whether or
    not the account exists."""
    try:
        client.auth.reset_password_for_email(email)
    except Exception as exc:
        raise _auth_error(exc) from exc


def reset_password(client, email: str, code: str, new_password: str) -> None:
    """Check the emailed code, set the new password, and leave the client
    logged in."""
    try:
        client.auth.verify_otp({"email": email, "token": code, "type": "recovery"})
        client.auth.update_user({"password": new_password})
        # Same supabase-py quirk as record_consent: update_user() drops the
        # login from table requests until the session is refreshed.
        client.auth.refresh_session()
    except Exception as exc:
        raise _auth_error(exc) from exc


def sign_out(client) -> None:
    """Ends this browser's session only; the default ("global") would also
    log the parent out on every other device."""
    try:
        client.auth.sign_out({"scope": "local"})
    except Exception:
        pass


def list_children(client) -> list[dict]:
    """The account's child profiles, oldest first."""
    return (client.table("students").select("id, display_name, grade")
            .order("created_at").execute().data)


def add_child(client, display_name: str, grade: int) -> dict:
    return (client.table("students")
            .insert({"display_name": display_name, "grade": grade})
            .execute().data[0])


def update_grade(client, student_id: str, grade: int) -> None:
    client.table("students").update({"grade": grade}).eq("id", student_id).execute()


def rename_child(client, student_id: str, display_name: str) -> None:
    client.table("students").update({"display_name": display_name}).eq("id", student_id).execute()


def delete_child(client, student_id: str) -> None:
    """Removes the profile; its attempts go with it (on delete cascade)."""
    client.table("students").delete().eq("id", student_id).execute()


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------
# Bumped when what we keep changes; a parent who agreed to an older version
# is asked again at login. 1: name, class, practice results. 2: also chats.
CONSENT_VERSION = 2


def consent_version(client) -> int:
    """The consent version the logged-in account last agreed to (accounts
    from before versioning count as 1)."""
    user = client.auth.get_user().user
    return int((user.user_metadata or {}).get("consent_version", 1))


def record_consent(client, consent_at: str) -> None:
    client.auth.update_user({"data": {"consent_version": CONSENT_VERSION,
                                      f"consent_v{CONSENT_VERSION}_at": consent_at}})
    # update_user() leaves the client's table requests carrying the anon key
    # instead of the parent's login (supabase-py resets the Authorization
    # header on any auth event other than sign-in, refresh or sign-out), so
    # the next query was refused by Row Level Security. A token refresh puts
    # the login back.
    client.auth.refresh_session()


# ---------------------------------------------------------------------------
# Saved chats (the History sidebar)
# ---------------------------------------------------------------------------
def _text_key(message: dict) -> str:
    """Where a message keeps its visible text: a small-talk reply (kind
    "chat") under "reply", everything else under "text"."""
    return "reply" if message.get("role") == "assistant" and message.get("kind") == "chat" else "text"


def message_to_row(chat_id: str, position: int, message: dict) -> dict:
    key = _text_key(message)
    metadata = {k: v for k, v in message.items() if k not in ("role", key)}
    return {"chat_id": chat_id, "position": position, "role": message["role"],
            "content": message.get(key) or "", "metadata": metadata}


def row_to_message(row: dict) -> dict:
    message = dict(row["metadata"] or {}, role=row["role"])
    message[_text_key(message)] = row["content"]
    return message


def list_chats(client, student_id: str) -> list[dict]:
    """The child's saved chats, most recently used first."""
    return (client.table("chats").select("id, title, thread_notes")
            .eq("student_id", student_id).order("updated_at", desc=True)
            .execute().data)


def load_messages(client, chat_id: str) -> list[dict]:
    rows = (client.table("messages").select("position, role, content, metadata")
            .eq("chat_id", chat_id).order("position").execute().data)
    return [row_to_message(r) for r in rows]


def save_chat(client, student_id: str, chat: dict, title: str) -> None:
    """Bring the saved copy of a session chat up to date: create the chat row
    on first save, then insert only the messages not saved yet.
    chat["db_id"] and chat["saved_count"] record what is already stored."""
    from datetime import datetime, timezone

    fields = {"title": title[:200], "thread_notes": list(chat.get("thread_notes") or []),
              "updated_at": datetime.now(timezone.utc).isoformat()}
    if not chat.get("db_id"):
        row = (client.table("chats").insert(dict(fields, student_id=student_id))
               .execute().data[0])
        chat["db_id"], chat["saved_count"] = row["id"], 0
    else:
        client.table("chats").update(fields).eq("id", chat["db_id"]).execute()
    start = chat.get("saved_count") or 0
    new = [message_to_row(chat["db_id"], pos, m)
           for pos, m in enumerate(chat["messages"]) if pos >= start]
    if new:
        client.table("messages").insert(new).execute()
    chat["saved_count"] = len(chat["messages"])


def delete_chat(client, chat_id: str) -> None:
    """Removes the chat; its messages go with it (on delete cascade)."""
    client.table("chats").delete().eq("id", chat_id).execute()


# ---------------------------------------------------------------------------
# Textbook search (the meaning-based half of scripts/retrieval.py)
# ---------------------------------------------------------------------------
_public_client = None
_public_lock = threading.Lock()


def public_client():
    """One shared client with no login, for public data (the textbook
    chunks). Safe to share between sessions: it never signs in."""
    global _public_client
    with _public_lock:
        if _public_client is None:
            _public_client = new_client()
        return _public_client


def chunk_count() -> int:
    return public_client().table("chunks").select("id", count="exact", head=True).execute().count


def match_chunks(query_embedding: list[float], grades: tuple[int, ...],
                 min_page: int, match_count: int) -> list[int]:
    """Chunk ids nearest the query in the given grades past min_page,
    nearest first (supabase/schema.sql match_chunks)."""
    rows = public_client().rpc("match_chunks", {
        "query_embedding": query_embedding, "grades": list(grades),
        "min_page": min_page, "match_count": match_count,
    }).execute().data
    return [r["id"] for r in rows]
