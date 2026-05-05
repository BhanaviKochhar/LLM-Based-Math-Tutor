"""Hugging Face chat model API integration for the math tutoring pipeline.

This module receives a fully formatted prompt and returns only the generated
model response. Retrieval and prompt construction are intentionally handled by
separate modules.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv
from huggingface_hub import InferenceClient


DEFAULT_MODEL = "mistralai/Mistral-7B-Instruct-v0.2"
FALLBACK_RESPONSE = "Error: Unable to generate response."

logger = logging.getLogger(__name__)

load_dotenv()


def _get_api_key() -> str:
    """Return the Hugging Face API key loaded from the environment."""

    api_key = os.getenv("HF_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "HF_API_KEY is missing. Add it to your .env file or environment."
        )

    return api_key


def _get_client() -> InferenceClient:
    """Create a Hugging Face inference client."""

    return InferenceClient(token=_get_api_key())


def _extract_response_text(completion: Any) -> str:
    """Extract plain text from a Hugging Face chat completion response."""

    try:
        response_text = completion.choices[0].message["content"]
    except (AttributeError, IndexError, KeyError, TypeError) as exc:
        raise ValueError("Invalid Hugging Face chat completion response.") from exc

    if not isinstance(response_text, str):
        raise ValueError("Hugging Face response content was not a string.")

    return response_text.strip()


def generate_response(
    prompt: str,
    model: str = DEFAULT_MODEL,
) -> str:
    """Generate a tutoring response from a fully formatted prompt.

    Args:
        prompt: Final prompt string produced by ``prompt_builder.py``.
        model: Hugging Face chat model name to use for generation.

    Returns:
        The clean model-generated text, or a safe fallback message if the
        request fails or the model returns an empty response.

    Raises:
        TypeError: If ``prompt`` is not a string.
        ValueError: If ``prompt`` is empty or only whitespace.
    """

    if not isinstance(prompt, str):
        raise TypeError("Prompt must be a string.")

    if not prompt.strip():
        raise ValueError("Prompt must not be empty.")

    logger.info("Generating response with model: %s", model)

    try:
        client = _get_client()
        messages = [{"role": "user", "content": prompt}]
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=256,
            temperature=0.7,
        )
        response_text = _extract_response_text(completion)
    except Exception as exc:
        logger.error("Response generation failed with model %s: %s", model, exc)
        return FALLBACK_RESPONSE

    if not response_text:
        logger.error("Hugging Face response was empty for model: %s", model)
        return FALLBACK_RESPONSE

    logger.info("Response generated successfully with model: %s", model)
    return response_text


def _run_cli_examples() -> None:
    """Run simple manual checks when executing this module directly."""

    examples = [
        ("Simple question", "Explain what is half for a grade 3 student"),
        (
            "Tutoring-style prompt",
            """You are a friendly and patient math tutor teaching a Grade 3 student.

Your goal is to help the student understand the concept clearly using simple words and step-by-step explanations.

---

<context>
Half means one of two equal parts.

When a whole is split into two equal parts, each part is one half.
</context>

---

INSTRUCTIONS:

* Use ONLY the information provided in the <context>
* Do NOT make up any information
* Explain in simple language suitable for a Grade 3 student
* Solve the problem step-by-step
* Do NOT skip steps
* Keep explanations short and clear
* Use examples if helpful

If the answer cannot be found in the context, say:
"I don't know based on the given information."

---

QUESTION:
What is half?

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

---""",
        ),
        ("Empty prompt", ""),
    ]

    for title, prompt in examples:
        print(f"\n=== {title} ===")
        try:
            print(generate_response(prompt))
        except (TypeError, ValueError) as exc:
            print(f"Error: {exc}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )
    _run_cli_examples()
