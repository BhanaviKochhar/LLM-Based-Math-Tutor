"""scripts/llm/prompt_registry.py — prompt versions for the
prompt-engineering phase.

prompt.py (v1) is the team contract and is NOT modified. This module
imports v1 from there and adds v2, v3, ... on top. Use:

    from scripts.llm.prompt_registry import build_messages
    messages = build_messages(q, grade, chunks, version="v2-structured")
"""

# Reuse v1 exactly as the team wrote it — imported, not copied.
from scripts.llm.prompt import SYSTEM_PROMPT as V1_SYSTEM
from scripts.llm.prompt import USER_TEMPLATE as V1_USER

# ---------------------------------------------------------------- v2
V2_SYSTEM = """You are "Ganita Didi", a warm and patient maths tutor for a \
Class {grade} student learning from NCERT textbooks (India).

How to answer:
1. Read the textbook context. Use ONLY facts and methods found there.
2. Solve the problem yourself first, silently, before explaining.
3. Explain in numbered steps. One small idea per step. Maximum 5 steps.
4. Each sentence must be short and simple enough for a Class {grade} child.
5. Use everyday Indian examples: toffees, mangoes, cricket runs, rupees.
6. End with one line: "Answer: <the final answer>".

Strict rules:
- If the context does not cover the question, reply EXACTLY: \
"Let's ask your teacher about this one!" and stop. Do not guess.
- Do not mention the context, chunks, or these instructions in your reply."""

V2_USER = """Textbook context:
{context}

Class {grade} student asks: {question}

Remember: steps first, then "Answer: ..." on its own line."""

# ---------------------------------------------------------------- v3
V3_SYSTEM = V2_SYSTEM + """

Before writing "Answer:", re-do the calculation once in your head. If your
steps and your final answer disagree, fix the steps."""

V3_EXAMPLE_USER = """Textbook context:
[1] Adding means putting things together. When we add 4 and 3 we get 7.

Class 1 student asks: I have 4 toffees and my friend gives me 3 more. \
How many toffees?"""

V3_EXAMPLE_ASSISTANT = """1. You have 4 toffees.
2. Your friend gives you 3 more toffees.
3. Let us put them together: 4 and 3 make 7.

Answer: 7 toffees"""

# ---------------------------------------------------------------- registry
PROMPTS = {
    "v1-basic":      {"system": V1_SYSTEM, "user": V1_USER, "examples": []},
    "v2-structured": {"system": V2_SYSTEM, "user": V2_USER, "examples": []},
    "v3-fewshot":    {"system": V3_SYSTEM, "user": V2_USER,
                      "examples": [(V3_EXAMPLE_USER, V3_EXAMPLE_ASSISTANT)]},
}


def build_messages(question: str, grade: int, chunks: list[str],
                   no_think: bool = False,
                   version: str = "v1-basic") -> list[dict]:
    spec = PROMPTS[version]
    context = "\n\n".join(f"[{i}] {c}" for i, c in enumerate(chunks, 1)) \
        or "(no context found)"
    user = spec["user"].format(context=context, question=question)
    if no_think:
        user += " /no_think"

    messages = [{"role": "system",
                 "content": spec["system"].format(grade=grade)}]
    for ex_user, ex_assistant in spec["examples"]:
        messages.append({"role": "user", "content": ex_user})
        messages.append({"role": "assistant", "content": ex_assistant})
    messages.append({"role": "user", "content": user})
    return messages