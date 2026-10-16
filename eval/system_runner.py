"""eval/system_runner.py -- the "system" condition for the paper
evaluation's baseline-vs-system comparison.

This calls the ACTUAL production, controller-driven tutoring flow -- the
exact call path frontend/app.py's chat page drives per turn
(frontend.episode.submit_turn: input safety -> scope gate -> retrieval ->
compute-first verification -> controller state machine -> generation ->
post-check) -- never a reimplementation of any of it. This is the direct
counterpart to eval/baseline_runner.py; the two conditions run on the SAME
item set, on the SAME underlying model by construction: both ultimately
fall back to llm_client.default_targets() when nothing overrides the
target list (confirmed in scripts.llm.llm_client.stream/chat and in
scripts.llm.pipeline.TurnStream/hints.generate_hint, which never pass an
explicit `targets=`), which is exactly what eval/baseline_runner.py also
resolves to when run with its default (no --model flag). This module
therefore deliberately offers no --model flag of its own -- the real app
never has one either, and adding one here would let the two conditions
silently drift onto different models.

Session shape: builds the same plain
{"id", "messages", "episode", "thread_notes"} dict frontend/state.py's
chats hold, and drives it with submit_turn() exactly as
frontend/episode.process_pending_turn() does, minus the Streamlit
container/rerun choreography (that exists only so the question bubble
appears on screen before the slow reply -- irrelevant to a batch run with
no UI).

Side effects this harness deliberately isolates, so a multi-thousand-turn
run doesn't permanently pollute local dev data with synthetic rows:
  - scripts.llm.student_tracker.STORE and scripts.llm.telemetry.LOG_PATH
    are redirected to scratch files under eval/results/system_runs/ for
    this process's lifetime (restored on exit; the scratch files are left
    on disk for inspection, not auto-deleted -- they ARE this run's
    traceability for personalization/telemetry effects, just kept out of
    data/students.json and data/interaction_events.jsonl).
  - frontend.state._student_id / frontend.episode._student_id both read
    Streamlit's st.session_state, which behaves as a single process-wide
    dict even outside a real browser session ("bare mode", confirmed: it
    works, just logs noisy warnings) -- harmless for one real session, but
    this harness runs many journeys CONCURRENTLY (frontend/app.py never
    does), so left alone every worker thread would silently share ONE
    resolved identity and cross-contaminate the very student_level
    stratification the dataset is built around. Patched to a
    threading.local()-backed id instead, set once per journey on whichever
    thread runs it -- every item/journey gets its OWN fresh synthetic id
    (f"sysrun-{item_id}"), so personalization never bleeds between
    different items, while still allowing genuine WITHIN-journey
    personalization across one multi-turn item's own turns (part of what
    those journeys exist to test).
  - scripts.llm.student_tracker's module-level JSON store has no locking
    (a classic load-modify-save race under concurrent writers to the same
    file) -- its public functions are wrapped with one process-wide lock
    for this run's lifetime.

CLI:
    python -m eval.system_runner --dataset eval/datasets/out_of_scope.jsonl
    python -m eval.system_runner --dataset eval/datasets/multi_turn.json --limit 5 --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from eval.baseline_runner import _grade_of, _item_id, _student_turns, load_items
from scripts.llm import llm_client

ROOT = Path(__file__).resolve().parent.parent

_tls = threading.local()


def _level_of(item: dict) -> str | None:
    return item.get("student_level")  # absent on out_of_scope items; None is a valid fallback


def _threadlocal_student_id() -> str:
    return getattr(_tls, "student_id", None) or "sysrun-unknown"


def _warm_up_retrieval() -> None:
    """Call retrieve_with_metadata once per grade, single-threaded, BEFORE
    the concurrent run starts. scripts.retrieval's chroma-collection and
    BM25-index caches are both @lru_cache(maxsize=...) -- normally safe
    under concurrent access, but a live run surfaced a ChromaDB
    "Could not connect to tenant" error on the very first concurrent
    cross-thread call in a fresh process (an internal chromadb race on
    first-use tenant/database setup, not something scripts/retrieval.py
    controls). Pre-populating every grade's cache entry here, before any
    worker thread touches it, removes that race window entirely."""
    from scripts.retrieval import retrieve_with_metadata
    for grade in range(1, 6):
        try:
            retrieve_with_metadata("warm up the retrieval caches", grade)
        except Exception:
            pass


class _ThreadErrorCapture(logging.Handler):
    """Attached to frontend.episode's logger for this run's lifetime.
    submit_turn() deliberately swallows every exception from
    advance_episode/start_episode and returns a generic apology reply
    instead (never a raise) -- which is the right UX contract, but means a
    harness checking only "is the returned text non-empty" would wrongly
    call that apology a successful turn. episode.py already logs the real
    exception via logger.exception() right before returning that apology;
    this handler catches that same log record (on the SAME thread that
    produced it, via record.thread) so run_turn can report the turn as
    failed with the real underlying error, not a guessed string match."""

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread == threading.get_ident() and record.levelno >= logging.ERROR:
            _tls.captured_error = self.format(record)


@contextmanager
def _isolated_side_effects():
    """Redirect student_tracker/telemetry storage to scratch files, patch
    _student_id to the thread-local id above, and serialize student_tracker
    access -- see module docstring. Restores everything on exit, even if
    the run raises."""
    from frontend import episode as ep, state as st_mod
    from scripts.llm import student_tracker, telemetry

    scratch_dir = ROOT / "eval" / "results" / "system_runs"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    orig = {
        "store": student_tracker.STORE,
        "log_path": telemetry.LOG_PATH,
        "ep_sid": ep._student_id,
        "state_sid": st_mod._student_id,
        "record": student_tracker.record,
        "stats": student_tracker.stats,
        "classify": student_tracker.classify,
        "reset": student_tracker.reset,
    }

    lock = threading.Lock()

    def _locked(fn):
        def wrapper(*a, **kw):
            with lock:
                return fn(*a, **kw)
        return wrapper

    student_tracker.STORE = str(scratch_dir / "student_tracker_scratch.json")
    telemetry.LOG_PATH = scratch_dir / "interaction_events_scratch.jsonl"
    ep._student_id = _threadlocal_student_id
    st_mod._student_id = _threadlocal_student_id
    student_tracker.record = _locked(orig["record"])
    student_tracker.stats = _locked(orig["stats"])
    student_tracker.classify = _locked(orig["classify"])
    student_tracker.reset = _locked(orig["reset"])

    error_handler = _ThreadErrorCapture()
    episode_logger = logging.getLogger("frontend.episode")
    episode_logger.addHandler(error_handler)
    try:
        yield
    finally:
        episode_logger.removeHandler(error_handler)
        student_tracker.STORE = orig["store"]
        telemetry.LOG_PATH = orig["log_path"]
        ep._student_id = orig["ep_sid"]
        st_mod._student_id = orig["state_sid"]
        student_tracker.record = orig["record"]
        student_tracker.stats = orig["stats"]
        student_tracker.classify = orig["classify"]
        student_tracker.reset = orig["reset"]


def _new_chat(chat_id: str) -> dict:
    return {"id": chat_id, "messages": [], "episode": None, "thread_notes": []}


def _reply_text(reply: dict) -> str:
    """kind="turn" replies carry "text"; kind="chat" replies (scope gloss,
    the friendly fallback, the caught-exception fallback) carry "reply"."""
    return (reply.get("text") if reply.get("kind") == "turn" else reply.get("reply")) or ""


def run_turn(chat: dict, student_message: str, grade: int | None, ui_level: str | None) -> dict:
    """Run one system turn via the REAL frontend.episode.submit_turn -- the
    same call frontend/app.py's chat page makes per turn. submit_turn's own
    contract is "never raises"; the try/except below is a harness-side
    guard against that contract being violated, not an expected path."""
    from frontend import episode as ep

    t0 = time.perf_counter()
    chat["messages"].append({"role": "user", "text": student_message})
    active_turns = ep.build_active_turns(chat["messages"][:-1])
    _tls.captured_error = None
    harness_error = None
    try:
        reply = ep.submit_turn(chat, student_message, grade or 3, ui_level, active_turns)
    except Exception as exc:
        reply = {"role": "assistant", "kind": "chat", "question": student_message, "reply": ""}
        harness_error = repr(exc)
    chat["messages"].append(reply)
    latency_s = time.perf_counter() - t0
    text = _reply_text(reply)
    # submit_turn itself never raises -- an internal advance_episode/
    # start_episode failure is caught there and replaced with a generic
    # apology reply (non-empty text!), so "text is non-empty" alone is not
    # enough; _ThreadErrorCapture catches the real exception episode.py
    # logs right before returning that apology.
    harness_error = harness_error or getattr(_tls, "captured_error", None)
    return {
        "student": student_message,
        "response": text,
        "ok": bool(text.strip()) and harness_error is None,
        "mode": reply.get("mode"),
        "kind": reply.get("kind"),
        "terminal": reply.get("terminal"),
        "outcome": reply.get("outcome"),
        "verify": reply.get("verify"),
        "latency_s": latency_s,
        "error": harness_error,
    }


def run_journey(item_id: str, grade: int | None, ui_level: str | None,
                student_turns: list[str]) -> dict:
    """Run every turn of one journey in order, system-only, in its own
    fresh chat + synthetic student identity (see module docstring). Stops
    early (and flags it) if a turn comes back not-ok, mirroring
    baseline_runner.run_journey's same early-stop rule."""
    _tls.student_id = f"sysrun-{item_id}"
    chat = _new_chat(str(item_id))
    turns_out = []
    all_ok = True
    for i, student_message in enumerate(student_turns, 1):
        result = run_turn(chat, student_message, grade, ui_level)
        turns_out.append({"turn": i, **result})
        if not result["ok"]:
            all_ok = False
            break  # no point continuing a conversation whose last turn produced nothing
    return {"grade": grade, "condition": "system", "all_turns_ok": all_ok, "turns": turns_out}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="Path to an eval/datasets/* file")
    parser.add_argument("--checkpoint", default=None,
                        help="JSONL checkpoint path (default: eval/results/system_runs/<dataset-stem>.jsonl)")
    parser.add_argument("--limit", type=int, default=None, help="Only run the first N items")
    parser.add_argument("--max-workers", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would run (item count, ids, grades/levels) without any LLM call")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    items = load_items(dataset_path)
    if args.limit:
        items = items[: args.limit]

    if args.dry_run:
        print(f"{len(items)} item(s) from {dataset_path}")
        for item in items[:5]:
            print(f"  {_item_id(item)}: grade={_grade_of(item)}, level={_level_of(item)}, "
                  f"{len(_student_turns(item))} turn(s)")
        if len(items) > 5:
            print(f"  ... and {len(items) - 5} more")
        print(f"groq_key_count={llm_client.groq_key_count()}, "
              f"default_max_workers={llm_client.default_max_workers()}")
        return

    checkpoint = (Path(args.checkpoint) if args.checkpoint
                  else ROOT / "eval" / "results" / "system_runs" / f"{dataset_path.stem}.jsonl")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)

    jobs = [{"id": _item_id(item), "item": item} for item in items]

    def call_fn(job: dict) -> dict:
        item = job["item"]
        return run_journey(job["id"], _grade_of(item), _level_of(item), _student_turns(item))

    already_done = set()
    if checkpoint.exists():
        with open(checkpoint, encoding="utf-8") as f:
            already_done = {json.loads(line)["id"] for line in f if line.strip()}
    n_pending = sum(1 for j in jobs if j["id"] not in already_done)
    print(f"{len(jobs)} job(s) total, {len(already_done & {j['id'] for j in jobs})} already "
          f"in checkpoint, {n_pending} to run -> {checkpoint} "
          f"(max_workers={args.max_workers or llm_client.default_max_workers()})")
    print("Warming up retrieval caches (single-threaded) before the concurrent run...")
    _warm_up_retrieval()
    with _isolated_side_effects():
        results = llm_client.run_batch(
            jobs, call_fn,
            checkpoint_path=checkpoint,
            max_workers=args.max_workers,
        )
    n_ok = sum(1 for r in results if r.get("all_turns_ok"))
    print(f"Done: {n_ok}/{len(results)} journeys completed every turn ok. "
          f"Checkpoint: {checkpoint}")


if __name__ == "__main__":
    main()
