"""Live checks against the real Supabase project. NOT part of CI or the
offline suites: it signs in, writes and deletes rows. Run by hand after
supabase/schema.sql has been applied.

Needs, in .env or the environment:
    SUPABASE_URL, SUPABASE_ANON_KEY
    TEST_PARENT_EMAIL, TEST_PARENT_PASSWORD   a confirmed test account
    TEST_OTHER_EMAIL, TEST_OTHER_PASSWORD     optional second account, for
                                              the cross-account check

It creates its own throwaway child profile and deletes it at the end.

Run:  python -m scripts.llm.test_db_live
"""
from __future__ import annotations

import os
import tempfile

from scripts.llm import db, student_tracker

_passed = 0
_failed = 0


def check(name: str, cond: bool) -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok   {name}")
    else:
        _failed += 1
        print(f"  FAIL {name}")


_SEQUENCE = [
    ("Addition", True), ("Fractions", False), ("Time", False), ("Fractions", False),
    ("Time", False), ("Addition", True), ("Money", False), ("Fractions", True),
]


def _rows_or_denied(client, table: str) -> list:
    """Rows a client can read; [] when it has no access to the table at all
    (logged-out visitors get no grant, so they are refused outright)."""
    try:
        return client.table(table).select("id").execute().data
    except Exception:
        return []


def _signed_in(email_var: str, password_var: str):
    client = db.new_client()
    db.sign_in(client, os.environ[email_var], os.environ[password_var])
    return client


def main() -> None:
    if not db.configured() or not os.environ.get("TEST_PARENT_EMAIL"):
        raise SystemExit("Set SUPABASE_URL, SUPABASE_ANON_KEY, TEST_PARENT_EMAIL and "
                         "TEST_PARENT_PASSWORD first.")

    parent = _signed_in("TEST_PARENT_EMAIL", "TEST_PARENT_PASSWORD")
    child = db.add_child(parent, "Live Test", 3)
    sid = child["id"]
    print("created throwaway child profile")
    try:
        print("progress round trip matches the JSON store")
        db.attach(sid, parent)
        old_store = student_tracker.STORE
        with tempfile.TemporaryDirectory() as tmp:
            student_tracker.STORE = os.path.join(tmp, "students.json")
            try:
                for topic, correct in _SEQUENCE:
                    student_tracker.record(sid, topic, correct)
                    student_tracker.record("file-twin", topic, correct)
                check("stats() identical to the JSON store",
                      student_tracker.stats(sid) == student_tracker.stats("file-twin"))
                check("classify() identical to the JSON store",
                      student_tracker.classify(sid) == student_tracker.classify("file-twin"))
            finally:
                student_tracker.STORE = old_store

        print("grade update and profile lookup")
        db.update_grade(parent, sid, 4)
        mine = parent.table("students").select("id, grade").eq("id", sid).execute().data
        check("grade saved", mine == [{"id": sid, "grade": 4}])
        db.rename_child(parent, sid, "Live Test Renamed")
        listed = {c["id"]: c for c in db.list_children(parent)}
        check("list_children() includes the child", sid in listed)
        check("rename saved", listed.get(sid, {}).get("display_name") == "Live Test Renamed")

        print("saved chats")
        chat = {"messages": [{"role": "user", "text": "What is 2 + 2?"},
                             {"role": "assistant", "kind": "turn", "text": "Let's count!",
                              "buttons": ["Give me a hint"], "verify": {"ok": True}}],
                "thread_notes": ["solved 3 + 3"]}
        db.save_chat(parent, sid, chat, "What is 2 + 2?")
        chat["messages"] += [{"role": "user", "text": "4"},
                             {"role": "assistant", "kind": "chat", "question": "4", "reply": "Yes!"}]
        db.save_chat(parent, sid, chat, "What is 2 + 2?")
        listed_chats = db.list_chats(parent, sid)
        check("list_chats() returns the chat with its title and notes",
              [(c["id"], c["title"], c["thread_notes"]) for c in listed_chats]
              == [(chat["db_id"], "What is 2 + 2?", ["solved 3 + 3"])])
        check("load_messages() gives back all four messages, unchanged and in order",
              db.load_messages(parent, chat["db_id"]) == chat["messages"])
        db.save_chat(parent, sid, chat, "What is 2 + 2?", episode={"msg_start": 2, "hints_shown": ["count"]})
        check("an unfinished problem is saved and listed with its chat",
              [c["episode"] for c in db.list_chats(parent, sid)] == [{"msg_start": 2, "hints_shown": ["count"]}])
        spare = {"messages": [{"role": "user", "text": "spare"}], "thread_notes": []}
        db.save_chat(parent, sid, spare, "spare")
        db.delete_chat(parent, spare["db_id"])
        check("delete_chat() removes the chat and its messages",
              [c["id"] for c in db.list_chats(parent, sid)] == [c["id"] for c in listed_chats]
              and parent.table("messages").select("id").eq("chat_id", spare["db_id"]).execute().data == [])

        print("consent")
        fresh = _signed_in("TEST_PARENT_EMAIL", "TEST_PARENT_PASSWORD")
        db.record_consent(fresh, "2026-01-01T00:00:00+00:00")
        check("consent is recorded at the current version",
              db.consent_version(fresh) == db.CONSENT_VERSION)
        check("and the account's queries still carry its login afterwards",
              sid in {c["id"] for c in db.list_children(fresh)})
        db.sign_out(fresh)

        print("remembered login")
        token = db.current_refresh_token(parent)
        restored = db.new_client()
        new_token = db.restore_session(restored, token)
        check("a fresh client logs back in from a refresh token and gets a new one",
              bool(new_token) and new_token != token)
        check("and its queries carry the login",
              sid in {c["id"] for c in db.list_children(restored)})
        db.sign_out(restored)

        print("admin dashboard")
        check("a test account isn't an admin", db.is_admin(parent) is False)
        try:
            db.admin_dashboard(parent)
            check("and the dashboard refuses it", False)
        except Exception:
            check("and the dashboard refuses it", True)
        try:
            db.admin_dashboard(db.new_client())
            check("a logged-out visitor is refused the dashboard", False)
        except Exception:
            check("a logged-out visitor is refused the dashboard", True)

        print("Row Level Security")
        anon = db.new_client()
        check("a logged-out client sees no children", _rows_or_denied(anon, "students") == [])
        check("a logged-out client sees no attempts", _rows_or_denied(anon, "attempts") == [])
        check("a logged-out client sees no chats", _rows_or_denied(anon, "chats") == [])
        check("a logged-out client sees no messages", _rows_or_denied(anon, "messages") == [])
        try:
            anon.table("attempts").insert({"student_id": sid, "topic": "x", "correct": True}).execute()
            check("a logged-out client cannot add attempts", False)
        except Exception:
            check("a logged-out client cannot add attempts", True)

        if os.environ.get("TEST_OTHER_EMAIL"):
            other = _signed_in("TEST_OTHER_EMAIL", "TEST_OTHER_PASSWORD")
            check("another account cannot see this child",
                  other.table("students").select("id").eq("id", sid).execute().data == [])
            summary = other.rpc("student_summary", {"p_student_id": sid, "p_window": 5}).execute().data
            check("another account's summary of this child is empty",
                  summary["attempts"] == 0 and summary["recent"] == [])
            try:
                other.table("attempts").insert({"student_id": sid, "topic": "x", "correct": True}).execute()
                check("another account cannot add attempts to this child", False)
            except Exception:
                check("another account cannot add attempts to this child", True)
            check("another account cannot see this child's chats",
                  other.table("chats").select("id").eq("student_id", sid).execute().data == [])
            check("or their messages",
                  other.table("messages").select("id").eq("chat_id", chat["db_id"]).execute().data == [])
            try:
                other.table("messages").insert(db.message_to_row(chat["db_id"], 99, {"role": "user", "text": "x"})).execute()
                check("another account cannot add messages to this child's chat", False)
            except Exception:
                check("another account cannot add messages to this child's chat", True)
            db.rename_child(other, sid, "Hijacked")
            db.delete_child(other, sid)
            still = parent.table("students").select("display_name").eq("id", sid).execute().data
            check("another account cannot rename or delete this child",
                  still == [{"display_name": "Live Test Renamed"}])
            db.sign_out(other)
        else:
            print("  skip cross-account checks (TEST_OTHER_EMAIL not set)")

        print("reset")
        student_tracker.reset(sid)
        check("reset() leaves no attempts", student_tracker.stats(sid)["attempts"] == 0)

        print("delete")
        student_tracker.record(sid, "Addition", True)
        db.delete_child(parent, sid)
        check("delete_child() removes the profile",
              parent.table("students").select("id").eq("id", sid).execute().data == [])
        check("and its attempts with it",
              parent.table("attempts").select("id").eq("student_id", sid).execute().data == [])
        check("and its chats and messages",
              parent.table("chats").select("id").eq("student_id", sid).execute().data == []
              and parent.table("messages").select("id").eq("chat_id", chat["db_id"]).execute().data == [])
    finally:
        db.detach(sid)
        parent.table("students").delete().eq("id", sid).execute()
        db.sign_out(parent)
        print("throwaway child profile removed")

    print("textbook search")
    from scripts import retrieval
    chunks = retrieval._load_chunks()
    uploaded = db.chunk_count()
    if uploaded == 0:
        print("  skip textbook search checks (run scripts/upload_chunks.py first)")
    else:
        check(f"every chunk is uploaded ({uploaded} of {len(chunks)})", uploaded == len(chunks))
        anon = db.new_client()
        try:
            anon.table("chunks").update({"page": 0}).eq("id", 0).execute()
            unchanged = anon.table("chunks").select("page").eq("id", 0).execute().data
            check("the public key cannot change the textbook",
                  unchanged == [{"page": chunks[0]["page"]}])
        except Exception:
            check("the public key cannot change the textbook", True)
        ids = db.match_chunks(retrieval._embed("how many sides does a triangle have"), (2, 3),
                              retrieval.FRONT_MATTER_MAX_PAGE, 10)
        check("match_chunks returns 10 chunks, all in classes 2-3 and past the front matter",
              len(ids) == 10 and all(chunks[i]["grade"] in (2, 3)
                                     and chunks[i]["page"] > retrieval.FRONT_MATTER_MAX_PAGE
                                     for i in ids))
        retrieval._all_chunks_uploaded = None
        hits = retrieval.retrieve_with_metadata("how many sides does a triangle have", 3)
        check("the whole retrieval runs through Supabase and returns 3 chunks",
              retrieval._all_chunks_uploaded is True and len(hits) == 3)

    print(f"\n{_passed} passed, {_failed} failed")
    if _failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
