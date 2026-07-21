"""Ask the tutor a question interactively.

Run:  python -m scripts.llm.ask
"""
import os
from dotenv import load_dotenv
from openai import OpenAI

from scripts.retrieval import retrieve
from scripts.llm import prompt_registry

load_dotenv()
client = OpenAI(base_url="https://api.groq.com/openai/v1",
                api_key=os.environ["GROQ_API_KEY"])

MODEL_ID = "openai/gpt-oss-120b"
PARAMS = {"temperature": 0.3, "max_tokens": 1024, "top_p": 0.9,
          "frequency_penalty": 0.3}
VERSION = "v4-graded-refusal"


def ask(question: str, grade: int) -> str:
    chunks = retrieve(question, grade)
    messages = prompt_registry.build_messages(
        question, grade, chunks, version=VERSION)
    resp = client.chat.completions.create(
        model=MODEL_ID, messages=messages, **PARAMS)
    return resp.choices[0].message.content

if __name__ == "__main__":
    print("Ask the maths tutor a question (Ctrl+C to quit).\n")
    while True:
        try:
            raw = input("Grade (1-5): ").strip()
            if not raw.isdigit() or not (1 <= int(raw) <= 5):
                print("Please enter a number from 1 to 5.\n")
                continue
            grade = int(raw)
            question = input("Question: ").strip()
            print("\n" + "-" * 50)
            print(ask(question, grade))
            print("-" * 50 + "\n")
        except (KeyboardInterrupt, EOFError):
            print("\nBye!")
            break