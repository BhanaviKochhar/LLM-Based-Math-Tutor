"""scripts/llm/llama33.py — Llama-3.3-70B. Groq direct first, HF router fallback.

Note: Groq uses its own model id ("llama-3.3-70b-versatile"), different
from the HF repo id. Verify current ids at console.groq.com -> Models.
"""
from . import common, prompt

MODEL_NAME = "llama3.3-70b"
PARAMS = {"temperature": 0.3, "max_tokens": 1024, "top_p": 0.9}

BACKENDS = [
    {"name": "groq-direct", "base_url": common.GROQ_URL,
     "key_env": "GROQ_API_KEY", "model": "llama-3.3-70b-versatile"},
    {"name": "hf:groq", "base_url": common.HF_URL,
     "key_env": "HF_TOKEN", "model": "meta-llama/Llama-3.3-70B-Instruct:groq"},
    {"name": "hf:novita", "base_url": common.HF_URL,
     "key_env": "HF_TOKEN", "model": "meta-llama/Llama-3.3-70B-Instruct:novita"},
]


def generate(question: str, grade: int, chunks: list[str]) -> str:
    messages = prompt.build_messages(question, grade, chunks)
    result = common.chat(BACKENDS, messages, PARAMS)
    common.log_run(MODEL_NAME, question, grade, chunks, messages, PARAMS, result)
    return result["text"] if result["ok"] else f"[ERROR] {result['error']}"