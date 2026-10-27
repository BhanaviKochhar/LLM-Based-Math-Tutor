"""frontend/history.py -- saved chats for a logged-in child.

Everything here is a no-op for guests and when accounts are off: chats then
live only in the session, exactly as before.

A saved chat joins ss.chats as a stub (title only); its messages are fetched
the first time it is opened. After every finished turn the active chat is
saved: the chat row on first save, then only the new messages. A save that
fails is dropped silently -- the child's tutoring is never held up by it --
and the next turn's save picks up whatever was missed.

The chat's unfinished problem (chat["episode"]: the tutor's state, the
textbook chunks it retrieved, hints shown) is saved with it, so a reopened
chat carries on where it stopped, hint buttons included.
"""
from __future__ import annotations

from dataclasses import asdict

from frontend import account
from frontend.state import chat_title, ss


def episode_to_json(episode: dict | None) -> dict | None:
    """chat["episode"] as plain JSON (its tutor state is a dataclass)."""
    if not episode:
        return None
    state = episode.get("state")
    return dict(episode, state=asdict(state) if state is not None else None)


def episode_from_json(data: dict | None) -> dict | None:
    if not data:
        return None
    from scripts.llm.controller import TutorState
    state = data.get("state")
    return dict(data, state=TutorState(**state) if state is not None else None)


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
              "episode": None, "saved_episode": c.get("episode"), "loaded": False}
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
    try:
        episode = episode_from_json(chat.pop("saved_episode", None))
    except Exception:
        episode = None  # saved by an older version of the tutor state
    # A problem opened for another class is dropped, the same rule as an
    # in-app class change (state.change_grade).
    state = episode.get("state") if episode else None
    if state is not None and state.grade != ss.grade:
        episode = None
    chat["episode"] = episode


def save(chat: dict) -> None:
    if not _on() or not chat["messages"]:
        return
    from scripts.llm import db
    try:
        db.save_chat(ss.db_client, ss.student_id, chat, chat_title(chat),
                     episode=episode_to_json(chat.get("episode")))
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
