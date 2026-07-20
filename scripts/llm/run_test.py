"""scripts/llm/run_test.py — full RAG round-trip through all three models.

Run from project root (needs data/chromadb built and HF_TOKEN set):
    python -m scripts.llm.run_test
"""
from scripts.retrieval import retrieve
from scripts.llm import gpt_oss, llama33, qwen3

MODELS = [gpt_oss, llama33, qwen3]

TESTS = [
    ("How do I subtract with borrowing?", 3),
    ("What is a fraction of a whole?", 4),
]

if __name__ == "__main__":
    for question, grade in TESTS:
        chunks = retrieve(question, grade)
        print(f"\n{'=' * 70}\nQ (Class {grade}): {question}")
        print(f"Retrieved {len(chunks)} chunks. First chunk: {chunks[0][:80]}...")
        for m in MODELS:
            print(f"\n--- {m.MODEL_NAME} ---")
            print(m.generate(question, grade, chunks))
    print("\nAll runs logged to data/llm_runs.jsonl")
