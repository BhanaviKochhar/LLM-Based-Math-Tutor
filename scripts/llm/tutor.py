"""Personalized tutor: classifies the student's level, adapts the
explanation, and records performance after each question.

Run:  python -m scripts.llm.tutor
"""
import os
from dotenv import load_dotenv
from openai import OpenAI

from scripts.retrieval import retrieve
from scripts.llm import prompt_registry, student_tracker

load_dotenv()
client = OpenAI(base_url="https://api.groq.com/openai/v1",
                api_key=os.environ["GROQ_API_KEY"])

MODEL_ID = "openai/gpt-oss-120b"
PARAMS = {"temperature": 0.3, "max_tokens": 1024, "top_p": 0.9,
          "frequency_penalty": 0.3}


def answer(question: str, grade: int, level: str) -> str:
    chunks = retrieve(question, grade)
    messages = prompt_registry.build_messages(
        question, grade, chunks, version="v5-personalized", level=level)
    resp = client.chat.completions.create(
        model=MODEL_ID, messages=messages, **PARAMS)
    return resp.choices[0].message.content


if __name__ == "__main__":
    student_id = input("Student name/id: ").strip() or "student_001"

    while True:
        try:
            raw = input("\nGrade (1-5): ").strip()
            if not raw.isdigit() or not (1 <= int(raw) <= 5):
                print("Please enter a number from 1 to 5.")
                continue
            grade = int(raw)
            question = input("Question: ").strip()

            # 1. classify this student from their history (rule-based)
            level = student_tracker.classify(student_id)
            print(f"[level: {level}]")

            # 2. get a level-appropriate answer
            print("-" * 50)
            print(answer(question, grade, level))
            print("-" * 50)

            # 3. record how they did (drives future level)
            got = input("Did the student get it right? (y/n): ").strip().lower()
            student_tracker.record(student_id, topic=question[:30],
                                   correct=(got == "y"))

            st = student_tracker.stats(student_id)
            print(f"[progress: {st['attempts']} attempts, "
                  f"accuracy {st['accuracy']}]")

        except (KeyboardInterrupt, EOFError):
            print("\nBye!")
            break