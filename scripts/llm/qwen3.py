"""scripts/llm/qwen3.py — Qwen3-32B. Groq direct first, HF router fallback.

Thinking mode is disabled via /no_think and any residual <think> block
is stripped. Verify Groq's current id at console.groq.com -> Models
(expected: "qwen/qwen3-32b").
"""
import re

from . import common, prompt

MODEL_NAME = "qwen3-32b"
PARAMS = {"temperature": 0.3, "max_tokens": 1024, "top_p": 0.9}

BACKENDS = [
    {"name": "groq-direct", "base_url": common.GROQ_URL,
     "key_env": "GROQ_API_KEY", "model": "qwen/qwen3-32b"},
    {"name": "hf:nscale", "base_url": common.HF_URL,
     "key_env": "HF_TOKEN", "model": "Qwen/Qwen3-32B:nscale"},
    {"name": "hf:deepinfra", "base_url": common.HF_URL,
     "key_env": "HF_TOKEN", "model": "Qwen/Qwen3-32B:deepinfra"},
]

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def generate(question: str, grade: int, chunks: list[str]) -> str:
    messages = prompt.build_messages(question, grade, chunks, no_think=True)
    result = common.chat(BACKENDS, messages, PARAMS)
    result["text"] = _THINK_RE.sub("", result["text"]).strip()
    common.log_run(MODEL_NAME, question, grade, chunks, messages, PARAMS, result)
    return result["text"] if result["ok"] else f"[ERROR] {result['error']}"