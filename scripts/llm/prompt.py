"""scripts/llm/prompt.py — builds messages from the retrieve() output.

Team contract input: question (str), grade (int), chunks (list of 3 strings).
Prompt version is a constant so it lands in the logs; bump it when you
change the wording during the prompt-engineering phase.
"""

PROMPT_VERSION = "v1-basic"

SYSTEM_PROMPT = """You are a friendly mathematics tutor for a Class {grade} student \
following the NCERT syllabus (India). Rules:
- Answer using ONLY the context provided below.
- Explain step by step, in short sentences a Class {grade} child understands.
- Use small numbers and everyday examples (fruits, toffees, toys).
- If the context does not contain what is needed, say: "Let's ask your teacher \
about this one!" and do not invent an answer."""

USER_TEMPLATE = """Context from the textbook:
{context}

Student's question: {question}"""


def build_messages(question: str, grade: int, chunks: list[str],
                   no_think: bool = False) -> list[dict]:
    context = "\n\n".join(f"[{i}] {c}" for i, c in enumerate(chunks, 1)) \
        or "(no context found)"
    user = USER_TEMPLATE.format(context=context, question=question)
    if no_think:
        user += " /no_think"
    return [
        {"role": "system", "content": SYSTEM_PROMPT.format(grade=grade)},
        {"role": "user", "content": user},
    ]
