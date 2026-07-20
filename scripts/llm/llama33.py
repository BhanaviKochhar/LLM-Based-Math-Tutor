"""scripts/llm/llama33.py — Llama-3.3-70B-Instruct (secondary candidate)."""
from . import common, prompt

MODEL_NAME = "llama3.3-70b"
MODEL_ID = "meta-llama/Llama-3.3-70B-Instruct"
PROVIDERS = ["groq", "novita", "featherless-ai", "scaleway"]
PARAMS = {"temperature": 0.3, "max_tokens": 1024, "top_p": 0.9}


def generate(question: str, grade: int, chunks: list[str]) -> str:
    messages = prompt.build_messages(question, grade, chunks)
    result = common.chat(MODEL_ID, PROVIDERS, messages, PARAMS)
    common.log_run(MODEL_NAME, question, grade, chunks, messages, PARAMS, result)
    if not result["ok"]:
        return f"[ERROR] {result['error']}"
    return result["text"]
