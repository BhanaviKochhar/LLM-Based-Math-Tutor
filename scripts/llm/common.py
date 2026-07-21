"""scripts/llm/common.py — shared plumbing for all model files (v2, backend-aware).

A "backend" = an OpenAI-compatible endpoint + credentials + a model string.
Each model file declares its backends in preference order, e.g. Groq direct
first, HF router second. chat() walks the list until one succeeds.

Env (.env at project root, loaded automatically):
    GROQ_API_KEY=gsk_xxx     # console.groq.com -> API Keys
    HF_TOKEN=hf_xxx          # huggingface.co/settings/tokens
A backend whose env var is missing is skipped silently, so the code works
even if you only have one of the two keys.
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "llm_runs.jsonl"

# Base URLs for the endpoints we use. Add more here if needed (e.g. a local
# vLLM/Ollama server later — anything OpenAI-compatible works).
GROQ_URL = "https://api.groq.com/openai/v1"
HF_URL = "https://router.huggingface.co/v1"

_clients: dict[tuple[str, str], OpenAI] = {}


def _client(base_url: str, key_env: str) -> OpenAI | None:
    """Return a cached client for (base_url, key_env), or None if no key set."""
    token = os.environ.get(key_env)
    if not token:
        return None
    cache_key = (base_url, key_env)
    if cache_key not in _clients:
        _clients[cache_key] = OpenAI(base_url=base_url, api_key=token, timeout=60)
    return _clients[cache_key]


def chat(backends: list[dict], messages: list[dict], params: dict,
         retries_per_backend: int = 2) -> dict:
    """Try each backend in order; return a structured result dict (never raises).

    backends: [{"name": "groq", "base_url": GROQ_URL,
                "key_env": "GROQ_API_KEY", "model": "llama-3.3-70b-versatile"}, ...]
    """
    last_err = None
    for be in backends:
        cli = _client(be["base_url"], be["key_env"])
        if cli is None:
            last_err = f"{be['name']}: skipped ({be['key_env']} not set)"
            continue
        for attempt in range(retries_per_backend):
            t0 = time.perf_counter()
            try:
                resp = cli.chat.completions.create(
                    model=be["model"], messages=messages, **params)
                choice = resp.choices[0]
                usage = getattr(resp, "usage", None)
                return {
                    "ok": True,
                    "backend": be["name"],
                    "model_str": be["model"],
                    "text": (choice.message.content or "").strip(),
                    "finish_reason": choice.finish_reason,
                    "latency_s": round(time.perf_counter() - t0, 3),
                    "prompt_tokens": getattr(usage, "prompt_tokens", None),
                    "completion_tokens": getattr(usage, "completion_tokens", None),
                    "error": None,
                }
            except Exception as e:  # noqa: BLE001 — record and fall through
                last_err = f"{be['name']} attempt {attempt + 1}: {e}"
                time.sleep(attempt + 1)
    return {"ok": False, "backend": None, "model_str": None, "text": "",
            "finish_reason": None, "latency_s": None, "prompt_tokens": None,
            "completion_tokens": None, "error": last_err}


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