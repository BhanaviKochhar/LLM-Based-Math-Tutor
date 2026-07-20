"""scripts/llm/gpt_oss.py — gpt-oss-120b (primary candidate).

Usage:
    from scripts.llm.gpt_oss import generate
    answer = generate(question, grade, chunks)   # chunks = retrieve(question, grade)
"""
from . import common, prompt

MODEL_NAME = "gpt-oss-120b"
MODEL_ID = "openai/gpt-oss-120b"
PROVIDERS = ["groq", "nscale", "deepinfra"]   # preference order
PARAMS = {"temperature": 0.3, "max_tokens": 1024, "top_p": 0.9}


def generate(question: str, grade: int, chunks: list[str]) -> str:
    messages = prompt.build_messages(question, grade, chunks)
    result = common.chat(MODEL_ID, PROVIDERS, messages, PARAMS)
    common.log_run(MODEL_NAME, question, grade, chunks, messages, PARAMS, result)
    if not result["ok"]:
        return f"[ERROR] {result['error']}"
    return result["text"]
