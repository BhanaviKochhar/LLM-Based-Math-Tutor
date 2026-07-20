"""scripts/llm/qwen3.py — Qwen3-32B (tertiary candidate).

Qwen3 is a hybrid thinking model. For an interactive tutor we disable
thinking (/no_think in the user turn) and additionally strip any
<think>...</think> block if one still appears.
"""
import re

from . import common, prompt

MODEL_NAME = "qwen3-32b"
MODEL_ID = "Qwen/Qwen3-32B"
PROVIDERS = ["groq", "nscale", "deepinfra"]
PARAMS = {"temperature": 0.3, "max_tokens": 1024, "top_p": 0.9}

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def generate(question: str, grade: int, chunks: list[str]) -> str:
    messages = prompt.build_messages(question, grade, chunks, no_think=True)
    result = common.chat(MODEL_ID, PROVIDERS, messages, PARAMS)
    result["text"] = _THINK_RE.sub("", result["text"]).strip()
    common.log_run(MODEL_NAME, question, grade, chunks, messages, PARAMS, result)
    if not result["ok"]:
        return f"[ERROR] {result['error']}"
    return result["text"]
