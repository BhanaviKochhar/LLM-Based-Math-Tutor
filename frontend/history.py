"""frontend/history.py -- saved chats for a logged-in child.

Everything here is a no-op for guests and when accounts are off: chats then
live only in the session, exactly as before.

A saved chat joins ss.chats as a stub (title only); its messages are fetched
the first time it is opened. After every finished turn the active chat is
saved: the chat row on first save, then only the new messages. A save that
fails is dropped silently -- the child's tutoring is never held up by it --
and the next turn's save picks up whatever was missed.
"""
from __future__ import annotations

from frontend import account
from frontend.state import chat_title, ss


def _on() -> bool:
    return account.signed_in() and "student_id" in ss


def load_for_child() -> None:
    """After a child is chosen: their saved chats, then a fresh chat to
    start in (ss.chats is oldest first; the sidebar lists newest first)."""
    if not _on():
        return
    from scripts.llm import db
    try:
        saved = db.list_chats(ss.db_client, ss.student_id)
    except Exception:
        saved = []
    stubs = [{"id": f"saved-{c['id']}", "db_id": c["id"], "title": c["title"],
              "thread_notes": list(c["thread_notes"] or []), "messages": [],
              "episode": None, "loaded": False}
             for c in reversed(saved)]
    ss.chat_seq = 1
    ss.chats = stubs + [{"id": "chat-1", "messages": [], "episode": None, "thread_notes": []}]
    ss.active = "chat-1"


def ensure_loaded(chat: dict) -> None:
    """Fetch a saved chat's messages the first time it is opened."""
    if chat.get("loaded", True) or not _on():
        return
    from scripts.llm import db
    try:
        chat["messages"] = db.load_messages(ss.db_client, chat["db_id"])
    except Exception:
        return
    chat["saved_count"] = len(chat["messages"])
    chat["loaded"] = True


def save(chat: dict) -> None:
    if not _on() or not chat["messages"]:
        return
    from scripts.llm import db
    try:
        db.save_chat(ss.db_client, ss.student_id, chat, chat_title(chat))
    except Exception:
        pass


def delete(chat: dict) -> None:
    """Remove a chat from the session, and from the database if saved."""
    if chat.get("db_id") and _on():
        from scripts.llm import db
        db.delete_chat(ss.db_client, chat["db_id"])
    ss.chats = [c for c in ss.chats if c["id"] != chat["id"]]
    if not ss.chats:
        ss.chat_seq += 1
        ss.chats = [{"id": f"chat-{ss.chat_seq}", "messages": [], "episode": None, "thread_notes": []}]
    ss.active = ss.chats[-1]["id"]
