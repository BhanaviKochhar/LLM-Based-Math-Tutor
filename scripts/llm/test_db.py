"""Offline tests for scripts/llm/db.py and student_tracker's hand-off to it.

No network and no Supabase project: a small in-memory stand-in plays the
client, answering the same table and rpc calls db.py makes. The real
database (schema.sql, Row Level Security, the student_summary function) is
covered by scripts/llm/test_db_live.py, run by hand.

Run:  python -m scripts.llm.test_db
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


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Just the PostgREST builder calls db.py uses on the attempts table."""

    def __init__(self, rows: list, op: str, payload=None):
        self.rows, self.op, self.payload, self.filters = rows, op, payload, []

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        if self.op == "insert":
            row = dict(self.payload, id=len(self.rows) + 1)
            self.rows.append(row)
            return _Result([row])
        keep = [r for r in self.rows if not all(r[c] == v for c, v in self.filters)]
        gone = len(self.rows) - len(keep)
        self.rows[:] = keep
        return _Result([{}] * gone)


class _Table:
    def __init__(self, rows):
        self.rows = rows

    def insert(self, payload):
        return _Query(self.rows, "insert", payload)

    def delete(self):
        return _Query(self.rows, "delete")


class FakeClient:
    """Stands in for a logged-in supabase client. rpc('student_summary')
    mirrors the SQL function in supabase/schema.sql."""

    def __init__(self):
        self.attempts: list[dict] = []

    def table(self, name):
        assert name == "attempts", name
        return _Table(self.attempts)

    def rpc(self, name, params):
        assert name == "student_summary", name
        rows = [r for r in self.attempts if r["student_id"] == params["p_student_id"]]
        weak: dict[str, int] = {}
        for r in rows:
            if not r["correct"]:
                weak[r["topic"]] = weak.get(r["topic"], 0) + 1
        recent = [1 if r["correct"] else 0 for r in rows][-params["p_window"]:]
        return _Rpc(_Result({
            "attempts": len(rows),
            "correct": sum(1 for r in rows if r["correct"]),
            "weak_topics": [[t, n] for t, n in weak.items()],
            "recent": recent,
        }))


class _Rpc:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


# A run of graded answers with repeated topics, ties in wrong counts and more
# attempts than the classification window.
_SEQUENCE = [
    ("Addition", True), ("Fractions", False), ("Time", False), ("Fractions", False),
    ("Time", False), ("Addition", True), ("Money", False), ("Addition", True),
    ("Fractions", True), ("Time", True), ("Money", True),
]


def _with_temp_store(fn):
    old = student_tracker.STORE
    with tempfile.TemporaryDirectory() as tmp:
        student_tracker.STORE = os.path.join(tmp, "students.json")
        try:
            return fn()
        finally:
            student_tracker.STORE = old


def test_attached_child_matches_json_store() -> None:
    print("an attached child's stats and level match the JSON store for the same answers")

    def run():
        for i in range(len(_SEQUENCE) + 1):
            prefix = _SEQUENCE[:i]
            file_id, remote_id = f"file-{i}", f"remote-{i}"
            client = FakeClient()
            db.attach(remote_id, client)
            try:
                for topic, correct in prefix:
                    student_tracker.record(file_id, topic, correct)
                    student_tracker.record(remote_id, topic, correct)
                same_stats = student_tracker.stats(file_id) == student_tracker.stats(remote_id)
                same_level = student_tracker.classify(file_id) == student_tracker.classify(remote_id)
            finally:
                db.detach(remote_id)
            if not (same_stats and same_level):
                return i
        return None

    mismatch = _with_temp_store(run)
    check(f"identical stats() and classify() after each of 0..{len(_SEQUENCE)} answers "
          f"(first mismatch: {mismatch})", mismatch is None)


def test_attached_child_never_touches_json_file() -> None:
    print("an attached child's answers go to the database, not data/students.json")

    def run():
        client = FakeClient()
        db.attach("kid", client)
        try:
            student_tracker.record("kid", "Addition", True)
            student_tracker.record("kid", "Time", False)
            wrote_file = os.path.exists(student_tracker.STORE)
            rows = len(client.attempts)
            student_tracker.reset("kid")
            after_reset = len(client.attempts)
        finally:
            db.detach("kid")
        return wrote_file, rows, after_reset

    wrote_file, rows, after_reset = _with_temp_store(run)
    check("no JSON file written", not wrote_file)
    check("two attempt rows inserted", rows == 2)
    check("reset() deletes that child's attempt rows", after_reset == 0)


def test_reset_only_clears_that_child() -> None:
    print("reset() on one attached child leaves another child's rows alone")
    client = FakeClient()
    db.attach("a", client)
    db.attach("b", client)
    try:
        student_tracker.record("a", "Addition", True)
        student_tracker.record("b", "Addition", False)
        student_tracker.reset("a")
        left = [r["student_id"] for r in client.attempts]
    finally:
        db.detach("a")
        db.detach("b")
    check("only child b's row remains", left == ["b"])


def test_unattached_ids_keep_using_json() -> None:
    print("guests and unattached ids (eval runs, tests) keep using the JSON file")

    def run():
        student_tracker.record("guest", "Addition", True)
        return os.path.exists(student_tracker.STORE), student_tracker.stats("guest")["attempts"]

    wrote_file, attempts = _with_temp_store(run)
    check("JSON file written for an unattached id", wrote_file)
    check("its attempt counted there", attempts == 1)
    check("store_for(None) is None", db.store_for(None) is None)
    check("store_for an unknown id is None", db.store_for("nobody") is None)


def test_detach_falls_back_to_json() -> None:
    print("after detach (log out) the same id is no longer sent to the database")
    client = FakeClient()
    db.attach("kid", client)
    db.detach("kid")

    def run():
        student_tracker.record("kid", "Addition", True)
        return os.path.exists(student_tracker.STORE)

    check("detached id writes to the JSON file", _with_temp_store(run))
    check("and nothing reached the client", client.attempts == [])


def test_configured_needs_both_settings() -> None:
    print("db.configured() needs both SUPABASE_URL and SUPABASE_ANON_KEY")
    saved = {k: os.environ.get(k) for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY")}
    try:
        for k in saved:
            os.environ.pop(k, None)
        none = db.configured()
        os.environ["SUPABASE_URL"] = "https://example.supabase.co"
        url_only = db.configured()
        os.environ["SUPABASE_ANON_KEY"] = "anon"
        both = db.configured()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    check("neither set -> False", none is False)
    check("URL only -> False", url_only is False)
    check("both set -> True", both is True)


def test_auth_errors_become_parent_friendly() -> None:
    print("Supabase auth errors become messages fit to show a parent")

    class _AuthFail(Exception):
        def __init__(self, code):
            super().__init__(code)
            self.code = code

    class _Auth:
        def __init__(self, code):
            self.code = code

        def sign_in_with_password(self, creds):
            raise _AuthFail(self.code)

    class _Client:
        def __init__(self, code):
            self.auth = _Auth(code)

    def message(code):
        try:
            db.sign_in(_Client(code), "a@b.co", "pw")
        except db.AccountError as exc:
            return str(exc)
        return None

    check("wrong password", "don't match" in (message("invalid_credentials") or ""))
    check("unconfirmed email", "confirm your email" in (message("email_not_confirmed") or ""))
    check("unknown code -> generic message, not raw API text",
          message("some_new_code") == "Something went wrong. Please try again.")
    check("wrong or expired reset code", "wrong or has expired" in (message("otp_expired") or ""))

    class _RefreshFails:
        def refresh_session(self, token):
            raise _AuthFail("refresh_token_already_used")

    class _ClientR:
        auth = _RefreshFails()

    try:
        db.restore_session(_ClientR(), "old-token")
        restored = "no error"
    except db.AccountError as exc:
        restored = str(exc)
    check("a remembered login that no longer works asks the parent to log in again",
          restored == "Please log in again.")


# Message shapes the app stores (frontend/episode.py): a child's message, a
# tutor turn, a small-talk reply (text under "reply"), a blocked input.
_MESSAGES = [
    {"role": "user", "text": "What is 25 + 17?"},
    {"role": "assistant", "kind": "turn", "mode": "teach_invite", "text": "Let's add!",
     "buttons": ["Give me a hint"], "terminal": False, "outcome": None, "hint_number": None,
     "source": "", "verify": {"ok": True}, "self_check_issues": [], "continues_episode": False,
     "safety": {"output_checked": True, "output_blocked": False}},
    {"role": "user", "text": "hi"},
    {"role": "assistant", "kind": "chat", "question": "hi", "reply": "Hello! Ready for maths?"},
    {"role": "user", "text": "[hidden for privacy]"},
]


def test_messages_survive_a_round_trip() -> None:
    print("every stored message shape comes back exactly as it went in")
    for i, m in enumerate(_MESSAGES):
        back = db.row_to_message(db.message_to_row("c", i, m))
        check(f"{m['role']} / {m.get('kind', '-')}: identical after save and load", back == m)
    row = db.message_to_row("c", 3, _MESSAGES[3])
    check("a small-talk reply's text is stored as the row's content",
          row["content"] == "Hello! Ready for maths?" and "reply" not in row["metadata"])


class _ChatTable:
    def __init__(self, store, name):
        self.store, self.name, self.op, self.payload = store, name, None, None

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def eq(self, column, value):
        return self

    def execute(self):
        self.store["calls"].append((self.name, self.op))
        if self.name == "chats" and self.op == "insert":
            row = dict(self.payload, id="chat-uuid")
            self.store["chats"].append(row)
            return _Result([row])
        if self.name == "messages":
            self.store["messages"].extend(self.payload)
        return _Result([])


class _ChatClient:
    def __init__(self):
        self.store = {"chats": [], "messages": [], "calls": []}

    def table(self, name):
        return _ChatTable(self.store, name)


def test_save_chat_inserts_only_new_messages() -> None:
    print("save_chat creates the chat once, then adds only the messages not saved yet")
    client = _ChatClient()
    chat = {"messages": list(_MESSAGES[:2]), "thread_notes": ["note"]}
    db.save_chat(client, "kid", chat, "What is 25 + 17?")
    check("first save creates one chat row for the child",
          len(client.store["chats"]) == 1 and client.store["chats"][0]["student_id"] == "kid")
    check("and inserts both messages at positions 0 and 1",
          [r["position"] for r in client.store["messages"]] == [0, 1])
    chat["messages"] += _MESSAGES[2:4]
    db.save_chat(client, "kid", chat, "What is 25 + 17?")
    check("second save updates the chat row instead of creating another",
          len(client.store["chats"]) == 1 and ("chats", "update") in client.store["calls"])
    check("and inserts only the two new messages, at positions 2 and 3",
          [r["position"] for r in client.store["messages"]] == [0, 1, 2, 3])
    db.save_chat(client, "kid", chat, "What is 25 + 17?")
    check("a save with nothing new inserts no messages",
          [r["position"] for r in client.store["messages"]] == [0, 1, 2, 3])
    check("thread notes are saved with the chat",
          client.store["chats"][0]["thread_notes"] == ["note"])


def main() -> None:
    test_attached_child_matches_json_store()
    test_attached_child_never_touches_json_file()
    test_reset_only_clears_that_child()
    test_unattached_ids_keep_using_json()
    test_detach_falls_back_to_json()
    test_configured_needs_both_settings()
    test_auth_errors_become_parent_friendly()
    test_messages_survive_a_round_trip()
    test_save_chat_inserts_only_new_messages()
    print(f"\n{_passed} passed, {_failed} failed")
    if _failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
