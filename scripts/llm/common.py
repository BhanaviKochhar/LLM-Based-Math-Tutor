"""scripts/llm/common.py — run logging for the tutor pipeline.

Appends one self-contained JSONL record per generation to
data/llm_runs.jsonl. Called by pipeline.py after each answer is streamed.
(The old multi-provider chat()/client() helpers lived here too; they were
retired when generation moved to llm_client.py.)
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "llm_runs.jsonl"


def log_run(model_name: str, question: str, grade: int, chunks: list[str],
            messages: list[dict], params: dict, result: dict) -> None:
    """Append one self-contained JSONL record per generation."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "id": uuid.uuid4().hex[:12],
        "model": model_name,
        "question": question,
        "grade": grade,
        "chunks": chunks,
        "messages": messages,
        "params": params,
        "result": result,
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")