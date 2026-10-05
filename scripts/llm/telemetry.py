"""scripts/llm/telemetry.py — structured per-turn tutoring-interaction log.

Deliberately separate from common.log_run(): that file logs GENERATION
events (one record per actual model call — full prompt messages, raw
params, raw result). This file logs TUTORING INTERACTION events (one record
per student turn, structured and compact) so a turn can be reconstructed —
what was decided, not what the model's raw prompt looked like. See the
stabilization brief's distinction between the two.

No personally-identifying profile fields belong here -- student_id is
already just a stable, opaque per-session internal id (see
frontend/app.py's _student_id()), not a name/email/etc, and nothing else
identifying is added by this module.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "interaction_events.jsonl"


def log_interaction(**fields) -> None:
    """Append one structured interaction-event record. Never raises --
    telemetry must not be able to break a tutoring turn."""
    try:
        record = {
            "event_id": uuid.uuid4().hex[:12],
            "ts": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass
