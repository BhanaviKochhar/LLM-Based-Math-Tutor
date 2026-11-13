"""frontend/markdown_utils.py -- tiny markdown-subset renderer for LLM replies."""
from __future__ import annotations

import re


_MD_BOLD_RE = re.compile(r"\*\*(?!\s)([^*\n]+?)(?<!\s)\*\*")
_MD_CODE_RE = re.compile(r"`([^`\n]+?)`")


def _markdown_lite(escaped_text: str) -> str:
    """Convert the two markdown emphasis forms an LLM reply commonly uses
    (**bold**, `code`) into real HTML tags, applied AFTER html.escape() so
    the regex only ever sees literal '*'/'`' characters, never
    attacker-controlled markup. Streamlit's own markdown engine does not
    reprocess text nested inside a raw HTML block (the chat-reply/
    answer-block/hint-tag divs below are exactly that), so without this a
    reply using **bold** rendered the literal asterisks to the child
    instead of bold text (U-08).

    Deliberately does NOT convert single-asterisk *italic* -- this is a
    primary-school maths tutor where a bare '*' routinely means
    multiplication inside the model's own generated text (e.g. "7 * 8"),
    and treating every stray pair of multiplication asterisks as italic
    markup would scramble formatting far more often than it would ever
    legitimately render italics.
    """
    text = _MD_CODE_RE.sub(r"<code>\1</code>", escaped_text)
    text = _MD_BOLD_RE.sub(r"<strong>\1</strong>", text)
    return text
