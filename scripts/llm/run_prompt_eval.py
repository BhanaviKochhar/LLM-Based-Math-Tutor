"""Run every prompt version on the eval set and log results.

Calls Groq directly (free tier) because HF router credits are depleted.
Messages come from prompt_registry — no team files modified.

Run:  python -m scripts.llm.run_prompt_eval
"""
import json
import os
import time

from dotenv import load_dotenv
from openai import OpenAI

from scripts.retrieval import retrieve
from scripts.llm import prompt_registry
from scripts.llm.eval_questions import EVAL_QUESTIONS

load_dotenv()

MODEL_ID = "openai/gpt-oss-120b"          # Groq's id for gpt-oss-120b
PARAMS = {"temperature": 0.3, "max_tokens": 1024, "top_p": 0.9,
          "frequency_penalty": 0.3}
VERSIONS = ["v4-graded-refusal"]
OUT_PATH = "data/prompt_eval_results.jsonl"
REFUSAL_MARKER = "ask your teacher"

client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.environ["GROQ_API_KEY"],
)


def call_llm(messages: list[dict]) -> dict:
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=MODEL_ID, messages=messages, **PARAMS)
            return {"ok": True, "text": resp.choices[0].message.content,
                    "error": None}
        except Exception as e:
            err = str(e)
            print(f"  [warn] attempt {attempt+1}: {err[:120]}")
            if "429" in err:            # rate limited -> wait and retry
                time.sleep(15)
            else:
                time.sleep(3)
    return {"ok": False, "text": "", "error": err}


def main() -> None:
    os.makedirs("data", exist_ok=True)
    n_total = len(VERSIONS) * len(EVAL_QUESTIONS)
    done = 0

    with open(OUT_PATH, "a", encoding="utf-8") as f:
        for version in VERSIONS:
            print(f"\n===== {version} =====")
            for question, grade, expect_refusal in EVAL_QUESTIONS:
                done += 1
                chunks = retrieve(question, grade)
                messages = prompt_registry.build_messages(
                    question, grade, chunks, version=version)
                result = call_llm(messages)

                text = result["text"] or ""
                text_low = text.lower()
                row = {
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "prompt_version": version,
                    "model": MODEL_ID,
                    "provider": "groq-direct",
                    "question": question,
                    "grade": grade,
                    "expect_refusal": expect_refusal,
                    "refused": REFUSAL_MARKER in text_low,
                    "has_answer_line": "answer:" in text_low,
                    "chunks": chunks,
                    "output": text,
                    "ok": result["ok"],
                    "error": result["error"],
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()

                status = "REFUSED" if row["refused"] else \
                         ("FAILED" if not result["ok"] else "answered")
                print(f"[{done:2d}/{n_total}] g{grade} {question[:45]:45s} -> {status}")
                time.sleep(3)      # stay under Groq free-tier rate limits

    print(f"\nDone. Results in {OUT_PATH}")


if __name__ == "__main__":
    main()