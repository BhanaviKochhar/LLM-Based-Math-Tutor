"""scripts/llm/common.py — shared plumbing for all model files.

Each model file (gpt_oss.py, llama33.py, qwen3.py) defines its own
MODEL_ID, PROVIDERS, PARAMS and calls chat() from here.

Env: HF_TOKEN must be set (export HF_TOKEN=hf_xxx, or .env + python-dotenv).
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

from dotenv import load_dotenv
load_dotenv()

BASE_URL = "https://router.huggingface.co/v1"
LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "llm_runs.jsonl"

_client = None


def client() -> OpenAI:
    global _client
    if _client is None:
        token = os.environ.get("HF_TOKEN")
        if not token:
            raise RuntimeError("Set the HF_TOKEN environment variable first.")
        _client = OpenAI(base_url=BASE_URL, api_key=token, timeout=60)
    return _client


def chat(model_id: str, providers: list[str], messages: list[dict],
         params: dict, retries_per_provider: int = 2) -> dict:
    """Try providers in order; return a structured result dict (never raises)."""
    last_err = None
    for provider in providers:
        model_str = f"{model_id}:{provider}"
        for attempt in range(retries_per_provider):
            t0 = time.perf_counter()
            try:
                resp = client().chat.completions.create(
                    model=model_str, messages=messages, **params)
                choice = resp.choices[0]
                usage = getattr(resp, "usage", None)
                return {
                    "ok": True,
                    "model_id": model_id,
                    "provider": provider,
                    "text": (choice.message.content or "").strip(),
                    "finish_reason": choice.finish_reason,
                    "latency_s": round(time.perf_counter() - t0, 3),
                    "prompt_tokens": getattr(usage, "prompt_tokens", None),
                    "completion_tokens": getattr(usage, "completion_tokens", None),
                    "error": None,
                }
            except Exception as e:  # log + fall through to retry/next provider
                last_err = f"{provider} attempt {attempt + 1}: {e}"
                time.sleep(attempt + 1)
    return {"ok": False, "model_id": model_id, "provider": None, "text": "",
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
