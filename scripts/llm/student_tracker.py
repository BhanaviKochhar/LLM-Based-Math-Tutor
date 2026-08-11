"""Rule-based student performance tracking + level classification.

Objective 2 lives here: the level is decided by transparent rules, not a model.

Two changes from the first MVP cut:
  * Classification is SESSION-AWARE. classify() looks at recent attempts, not a
    hidden all-time tally, so a good run this session doesn't silently promote a
    child forever (and a rough patch doesn't strand them at "beginner").
  * reset() clears a student's record, so the UI's "Clear chat" can start fresh.

The store still keeps a cumulative record per student for analytics; only the
*classification window* is recent. Level names stay beginner/intermediate/advanced.
"""
import json
import os

STORE = "data/students.json"

# How many of the most recent attempts drive the level decision.
WINDOW = 5
# Need at least this many attempts before we move off the neutral default.
MIN_ATTEMPTS = 3


def _load() -> dict:
    if os.path.exists(STORE):
        try:
            with open(STORE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save(data: dict) -> None:
    os.makedirs("data", exist_ok=True)
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _blank() -> dict:
    return {"attempts": 0, "correct": 0, "weak_topics": {}, "recent": []}


def record(student_id: str, topic: str, correct: bool) -> None:
    """Log one attempt for a student (cumulative totals + a recent window)."""
    data = _load()
    s = data.setdefault(student_id, _blank())
    # Older records may predate the "recent" field; heal them on write.
    s.setdefault("recent", [])
    s["attempts"] += 1
    if correct:
        s["correct"] += 1
    else:
        s["weak_topics"][topic] = s["weak_topics"].get(topic, 0) + 1
    # Keep only the last WINDOW outcomes for classification.
    s["recent"].append(1 if correct else 0)
    s["recent"] = s["recent"][-WINDOW:]
    _save(data)


def reset(student_id: str) -> None:
    """Forget everything for one student. Called by the UI's Clear chat so the
    level and history don't leak across sessions."""
    data = _load()
    if student_id in data:
        del data[student_id]
        _save(data)


def stats(student_id: str) -> dict:
    """All-time totals plus the recent-window accuracy used for classification."""
    data = _load()
    s = data.get(student_id, _blank())
    recent = s.get("recent", [])
    lifetime_acc = s["correct"] / s["attempts"] if s["attempts"] else 0.0
    recent_acc = sum(recent) / len(recent) if recent else 0.0
    weak = sorted(s["weak_topics"], key=s["weak_topics"].get, reverse=True)
    return {
        "attempts": s["attempts"],
        "recent_attempts": len(recent),
        "accuracy": round(lifetime_acc, 2),        # kept for analytics/UI
        "recent_accuracy": round(recent_acc, 2),   # drives classify()
        "weak_topics": weak,
    }


def classify(student_id: str) -> str:
    """Rule-based level from RECENT performance. Fully interpretable.

    Uses the last WINDOW attempts so the level tracks how the child is doing
    now, not their entire history. New/low-data students stay neutral.
    """
    st = stats(student_id)
    if st["recent_attempts"] < MIN_ATTEMPTS:
        return "intermediate"
    acc = st["recent_accuracy"]
    if acc < 0.4:
        return "beginner"
    if acc < 0.75:
        return "intermediate"
    return "advanced"