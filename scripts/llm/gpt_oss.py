"""scripts/llm/gpt_oss.py — gpt-oss-120b. Groq direct first, HF router fallback."""
from . import common, prompt

MODEL_NAME = "gpt-oss-120b"
PARAMS = {"temperature": 0.3, "max_tokens": 1024, "top_p": 0.9}

BACKENDS = [
    {"name": "groq-direct", "base_url": common.GROQ_URL,
     "key_env": "GROQ_API_KEY", "model": "openai/gpt-oss-120b"},
    {"name": "hf:groq", "base_url": common.HF_URL,
     "key_env": "HF_TOKEN", "model": "openai/gpt-oss-120b:groq"},
    {"name": "hf:nscale", "base_url": common.HF_URL,
     "key_env": "HF_TOKEN", "model": "openai/gpt-oss-120b:nscale"},
]


def generate(question: str, grade: int, chunks: list[str]) -> str:
    messages = prompt.build_messages(question, grade, chunks)
    result = common.chat(BACKENDS, messages, PARAMS)
    common.log_run(MODEL_NAME, question, grade, chunks, messages, PARAMS, result)
    return result["text"] if result["ok"] else f"[ERROR] {result['error']}"