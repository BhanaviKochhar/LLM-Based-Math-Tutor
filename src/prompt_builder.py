"""Build structured LLM prompts from retrieved math tutoring context.

This module is responsible only for prompt construction. Retrieval decides
which chunks are relevant; this module decides how those chunks are presented
to the tutoring LLM.
"""

from __future__ import annotations


PROMPT_TEMPLATE = """You are a friendly and patient math tutor teaching a Grade {grade} student.

Your goal is to help the student understand the concept clearly using simple words and step-by-step explanations.

---

<context>
{retrieved_chunks}
</context>

---

INSTRUCTIONS:

* Use ONLY the information provided in the <context>
* Do NOT make up any information
* Explain in simple language suitable for a Grade {grade} student
* Solve the problem step-by-step
* Do NOT skip steps
* Keep explanations short and clear
* Use examples if helpful

If the answer cannot be found in the context, say:
"I don’t know based on the given information."

---

QUESTION:
{user_query}

---

OUTPUT FORMAT (STRICT):

FINAL ANSWER:
...

STEPS:
1.
2.
3.

HINT:
...

CONFIDENCE:
...

---"""


def format_context(results: list[dict]) -> str:
    """Combine retrieved chunk text into a delimited context string.

    Only the ``text`` field from each retrieval result is included. The order of
    ``results`` is preserved so the highest-ranked chunk remains first.
    """

    if not isinstance(results, list):
        raise TypeError("Results must be provided as a list of dictionaries.")

    if not results:
        return ""

    chunks: list[str] = []
    for index, result in enumerate(results, start=1):
        if not isinstance(result, dict):
            raise TypeError(f"Result at position {index} must be a dictionary.")
        if "text" not in result:
            raise KeyError(f"Result at position {index} is missing the 'text' field.")

        text = result["text"]
        if not isinstance(text, str):
            raise TypeError(f"Text in result at position {index} must be a string.")

        chunks.append(text)

    return "\n\n---\n\n".join(chunks)


def build_prompt(query: str, results: list[dict], grade: int = 3) -> str:
    """Build the final structured tutoring prompt for the LLM.

    Args:
        query: The student's question. Must be a non-empty string.
        results: Retrieved chunks from ``retrieval.py``.
        grade: Student grade level to insert into the tutoring instructions.

    Returns:
        A complete prompt string using the strict tutoring template.
    """

    if not isinstance(query, str):
        raise TypeError("Query must be a string.")

    user_query = query.strip()
    if not user_query:
        raise ValueError("Query must not be empty.")

    retrieved_chunks = format_context(results)

    return PROMPT_TEMPLATE.format(
        grade=grade,
        retrieved_chunks=retrieved_chunks,
        user_query=user_query,
    )


def _verification_examples() -> None:
    """Run simple local checks for prompt formatting behavior.

    Example usage:

        prompt = build_prompt(
            query="What is half?",
            results=[
                {
                    "text": "Half means one of two equal parts.",
                    "score": 0.91,
                    "source": "mock_textbook.pdf",
                    "page": 4,
                }
            ],
            grade=3,
        )
        print(prompt)

    Expected behavior:
    - Prompt contains properly formatted <context> content.
    - Query is inserted correctly.
    - Structure matches the required prompt template.
    """

    examples = [
        (
            "What is half?",
            [
                {
                    "text": "Half means one of two equal parts.",
                    "score": 0.95,
                    "source": "mock_math_book.pdf",
                    "page": 10,
                },
                {
                    "text": "When a whole is split into two equal parts, each part is one half.",
                    "score": 0.88,
                    "source": "mock_math_book.pdf",
                    "page": 11,
                },
            ],
        ),
        (
            "How do I add 24 and 13?",
            [
                {
                    "text": "Add ones first, then add tens.",
                    "score": 0.9,
                    "source": "mock_addition_book.pdf",
                    "page": 6,
                },
                {
                    "text": "24 has 2 tens and 4 ones. 13 has 1 ten and 3 ones.",
                    "score": 0.84,
                    "source": "mock_addition_book.pdf",
                    "page": 7,
                },
            ],
        ),
        (
            "What is symmetry?",
            [],
        ),
    ]

    for query, results in examples:
        prompt = build_prompt(query=query, results=results, grade=3)

        assert "<context>" in prompt
        assert "</context>" in prompt
        assert f"QUESTION:\n{query}" in prompt
        assert "FINAL ANSWER:" in prompt
        assert "STEPS:" in prompt
        assert "HINT:" in prompt
        assert "CONFIDENCE:" in prompt

        print("=" * 80)
        print(prompt)


if __name__ == "__main__":
    _verification_examples()
