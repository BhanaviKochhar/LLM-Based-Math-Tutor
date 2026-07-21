"""Rule-based student performance tracking + level classification."""
import json
import os

STORE = "data/students.json"


def _load() -> dict:
    if os.path.exists(STORE):
        with open(STORE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(data: dict) -> None:
    os.makedirs("data", exist_ok=True)
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def record(student_id: str, topic: str, correct: bool) -> None:
    """Log one attempt for a student."""
    data = _load()
    s = data.setdefault(student_id, {"attempts": 0, "correct": 0,
                                     "weak_topics": {}})
    s["attempts"] += 1
    if correct:
        s["correct"] += 1
    else:
        s["weak_topics"][topic] = s["weak_topics"].get(topic, 0) + 1
    _save(data)


def stats(student_id: str) -> dict:
    data = _load()
    s = data.get(student_id, {"attempts": 0, "correct": 0, "weak_topics": {}})
    accuracy = s["correct"] / s["attempts"] if s["attempts"] else 0.0
    weak = sorted(s["weak_topics"], key=s["weak_topics"].get, reverse=True)
    return {"attempts": s["attempts"], "accuracy": round(accuracy, 2),
            "weak_topics": weak}

def classify(student_id: str) -> str:
    """Rule-based level from performance. Fully interpretable."""
    st = stats(student_id)
    # New students start in the middle until we have evidence.
    if st["attempts"] < 3:
        return "intermediate"
    if st["accuracy"] < 0.4:
        return "beginner"
    if st["accuracy"] < 0.75:
        return "intermediate"
    return "advanced"

