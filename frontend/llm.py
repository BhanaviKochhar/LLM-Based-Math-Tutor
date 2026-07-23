"""
llm.py — Turns retrieved NCERT chunks into a tutor-style answer.

Uses the Anthropic API. Set ANTHROPIC_API_KEY as an environment variable
before running (never hardcode it in the file).

    export ANTHROPIC_API_KEY=sk-ant-...        (mac/linux)
    setx ANTHROPIC_API_KEY "sk-ant-..."         (windows)
"""

from __future__ import annotations

import os

import anthropic

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a patient, encouraging maths tutor for Indian \
primary school students (Class 1-5), teaching strictly from the NCERT \
syllabus.

Rules:
- Only use the textbook excerpts given to you as context. If they don't \
contain enough to answer, say so honestly instead of guessing.
- Explain in short, numbered steps a child can follow.
- Use simple words and everyday examples (fruits, chocolates, rotis, etc).
- Keep the tone warm and encouraging, never condescending.
- End with the final answer clearly stated on its own line.
- Do not mention "the context" or "the excerpts" to the student — just \
teach.
"""


def generate_answer(question: str, chunks: list[dict]) -> str:
    """
    chunks: list of {"text": str, "source": str, "grade": int, "score": float}
            as returned by retrieval.hybrid_retrieve()
    """
    if not chunks:
        return (
            "I couldn't find this topic in the Class textbook yet — try "
            "rephrasing the question, or ask your teacher to check if it's "
            "covered in a different chapter."
        )

    context = "\n\n".join(
        f"[Excerpt {i+1} — {c['source']}]\n{c['text']}" for i, c in enumerate(chunks)
    )

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Textbook excerpts:\n\n{context}\n\n"
                    f"Student's question: {question}"
                ),
            }
        ],
    )

    return response.content[0].text


def ask_tutor(question: str, grade: int) -> dict:
    """
    Full pipeline: retrieve -> generate. This is the function app.py should
    import once you flip MOCK_MODE off.
    """
    from retrieval import hybrid_retrieve

    chunks = hybrid_retrieve(question, grade=grade, top_k=5)
    answer = generate_answer(question, chunks)
    top_source = chunks[0]["source"] if chunks else None

    return {"answer": answer, "source": top_source}
