"""scripts/llm/conversation_resolver.py — generic conversational routing.

This is intentionally NOT a list of hard-coded child scenarios.

The model performs a small, generic routing task:
    * NEW            -> a new standalone question
    * MATH_FOLLOWUP  -> a new math question that modifies the previous one
    * CONCEPT_FOLLOWUP -> asks about an idea/step already discussed
    * CONFUSION      -> "I don't understand", "what?", etc.
    * CORRECTION     -> rejects/corrects the tutor's last reply
    * FRAGMENT       -> incomplete/unclear continuation

Only MATH_FOLLOWUP/NEW are sent through compute-first. CONFUSION/CORRECTION
and ambiguous fragments are deliberately kept out of standalone RAG/solver
queries; their meaning comes from the live conversation already supplied to
the tutor.

A tiny deterministic rule handles the unambiguous grammar pattern
"X instead of Y" because it is safe, transparent, and avoids an unnecessary
LLM call. It is a guardrail, not a catalogue of domain scenarios.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass


MODES = {
    "NEW",
    "MATH_FOLLOWUP",
    "CONCEPT_FOLLOWUP",
    "CONFUSION",
    "CORRECTION",
    "FRAGMENT",
    "BEYOND_PRIMARY",
}

_ROUTER_SYSTEM_TEMPLATE = """You are a conversation router for a Class {grade} maths tutor.
Your job is to understand the CHILD'S CURRENT MESSAGE in the context of the
recent conversation. Do not solve maths and do not write a tutor answer.

Return ONLY valid JSON with these keys:
{
  "mode": "NEW|MATH_FOLLOWUP|CONCEPT_FOLLOWUP|CONFUSION|CORRECTION|FRAGMENT",
  "resolved_question": "...",
  "retrieval_query": "...",
  "confidence": 0.0
}

Meaning of modes:
- NEW: a self-contained new maths/topic question. Keep it as the question.
- MATH_FOLLOWUP: the child modifies, continues, or refers to the previous
  mathematical problem. Resolve references such as it/that/instead/another
  one into a self-contained mathematical question.
- CONCEPT_FOLLOWUP: the child asks why/how about an idea or step already
  discussed. Preserve the conceptual intent; do not turn it into a new
  arithmetic problem.
- CONFUSION: the child says they do not understand, is lost, or asks for the
  same explanation again without specifying a new question.
- CORRECTION: the child rejects/corrects the tutor's last response (for
  example "no", "that's not what I meant", or a correction).
- FRAGMENT: the message is too incomplete or ambiguous to safely resolve.

Critical rules:
1. Never invent a new textbook problem, story, numbers, objects, or facts.
2. For MATH_FOLLOWUP, change ONLY what the child clearly changed. Preserve
   the rest of the previous mathematical problem.
3. For CONCEPT_FOLLOWUP, CONFUSION, CORRECTION, and FRAGMENT, do NOT invent a
   standalone question. Keep resolved_question equal to the child's message
   unless a minimal contextual wording is genuinely necessary.
4. retrieval_query is only for substantive NEW/MATH_FOLLOWUP/CONCEPT_FOLLOWUP
   questions. For CONFUSION, CORRECTION, or FRAGMENT return an empty string.
5. The retrieval query is a concise description of the topic/problem, not an
   answer and not a fabricated example.
6. Confidence means confidence in the routing/resolution, not confidence in
   the maths answer.
"""


@dataclass(frozen=True)
class Resolution:
    original: str
    resolved_question: str
    retrieval_query: str
    mode: str
    confidence: float
    changed: bool
    use_rag: bool
    use_verifier: bool
    # True when the opener router already judged whether the message needs
    # maths beyond Class 5, so the caller must not ask the small model again.
    scope_checked: bool = False

    @property
    def conversational(self) -> bool:
        return self.mode != "NEW"


def _recent_turns(active_turns: list[dict] | None, limit: int = 8) -> list[dict]:
    clean: list[dict] = []
    for t in (active_turns or [])[-limit:]:
        role = t.get("role")
        content = (t.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            clean.append({"role": role, "content": content})
    return clean


def _last_user(active_turns: list[dict] | None) -> str:
    for t in reversed(_recent_turns(active_turns)):
        if t["role"] == "user":
            return t["content"]
    return ""


def _extract_expression(text: str) -> str | None:
    if not text:
        return None
    patterns = [
        r"(?<!\w)(\d+\s*/\s*\d+(?:\s*[+\-*/]\s*\d+(?:\s*/\s*\d+)?)+)(?!\w)",
        r"(?<!\w)(\d+(?:\s*[+\-*/]\s*\d+)+)(?!\w)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


def _deterministic_math_followup(question: str, previous: str) -> str | None:
    """Safely resolve the generic 'new value instead of old value' grammar."""
    expr = _extract_expression(previous)
    if not expr:
        return None

    m = re.search(
        r"(?:plus|add)\s+(-?\d+(?:\.\d+)?)\s+instead\s+of\s+(-?\d+(?:\.\d+)?)",
        question,
        re.I,
    )
    if not m:
        return None

    new_value, old_value = m.group(1), m.group(2)
    parts = re.split(r"(\s*[+\-*/]\s*)", expr)
    for i in range(len(parts) - 1, -1, -1):
        if re.fullmatch(r"\s*" + re.escape(old_value) + r"\s*", parts[i]):
            parts[i] = new_value
            return "".join(parts)

    # Only replace one exact standalone operand; never rewrite arbitrary text.
    return re.sub(
        rf"(?<![\d.]){re.escape(old_value)}(?![\d.])",
        new_value,
        expr,
        count=1,
    )


def _parse_json(text: str) -> dict | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass

    # Defensive extraction if a reasoning model wraps the JSON in prose/fences.
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _normalise(obj: dict, original: str) -> Resolution | None:
    mode = str(obj.get("mode", "")).strip().upper()
    if mode not in MODES:
        return None

    try:
        confidence = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    resolved = str(obj.get("resolved_question") or original).strip()
    retrieval_query = str(obj.get("retrieval_query") or "").strip()

    # Never allow the model to turn conversational repair into a fabricated
    # standalone question.
    if mode in {"CONFUSION", "CORRECTION", "FRAGMENT"}:
        resolved = original
        retrieval_query = ""
        use_rag = False
        use_verifier = False
    elif mode == "NEW":
        resolved = original if not resolved else resolved
        retrieval_query = retrieval_query or resolved
        use_rag = True
        use_verifier = True
    elif mode == "MATH_FOLLOWUP":
        retrieval_query = retrieval_query or resolved
        use_rag = True
        use_verifier = True
    else:  # CONCEPT_FOLLOWUP
        retrieval_query = retrieval_query or resolved
        use_rag = True
        use_verifier = False

    # A low-confidence rewrite is unsafe. Preserve the child's wording and
    # route it as a fragment so the tutor can clarify from live conversation.
    if mode in {"MATH_FOLLOWUP", "CONCEPT_FOLLOWUP"} and confidence < 0.70:
        return Resolution(
            original, original, "", "FRAGMENT", confidence, False, False, False
        )

    changed = resolved.strip() != original.strip()
    return Resolution(
        original=original,
        resolved_question=resolved,
        retrieval_query=retrieval_query,
        mode=mode,
        confidence=confidence,
        changed=changed,
        use_rag=use_rag,
        use_verifier=use_verifier,
    )


def _llm_route(question: str, active_turns: list[dict] | None,
               grade: int = 3) -> Resolution | None:
    from . import llm_client

    turns = _recent_turns(active_turns)
    conversation = "\n".join(
        f"{t['role'].upper()}: {t['content']}" for t in turns
    ) or "(no previous conversation)"

    messages = [
        # Plain substring replace, not str.format(): the template's JSON
        # schema example below is full of literal { }, which .format() would
        # try (and fail) to parse as format fields.
        {"role": "system", "content": _ROUTER_SYSTEM_TEMPLATE.replace("{grade}", str(grade))},
        {
            "role": "user",
            "content": (
                f"RECENT CONVERSATION:\n{conversation}\n\n"
                f"CURRENT MESSAGE:\n{question}\n\n"
                "Route this message now."
            ),
        },
    ]
    result = llm_client.chat(
        messages,
        params={"temperature": 0.0, "max_tokens": 220, "top_p": 1.0},
    )
    return _normalise(_parse_json(result.get("text") or "") or {}, question)


# ---------------------------------------------------------------- openers
# Routes a session's FIRST message: NEW (a maths task or topic can be
# identified -- however it is spelled), CLARIFY (nothing to act on without
# more information) or ADVANCED (it needs maths beyond Class 5). Hybrid,
# cheapest first:
#   1. a message with a quantity in it ("15 pencils and 4 more") is a real
#      problem -- no call here (the caller runs scope.needs_beyond_primary
#      on it). An ordinal ("the 2nd one") is not a quantity.
#   2. anything else: one short call to a SMALL model (gpt-oss-20b, its own
#      Groq rate limits, low reasoning effort) that answers both questions
#      at once, so a number-free opener never needs a second scope call. A
#      rules-only detector was rejected: it would have asked "Name a fruit
#      that is round" to clarify ("that" read as a reference) and can't see
#      that "circles?" is a topic but "I'm stuck." is not.
#   3. any failure -> NEW, i.e. exactly the v1 behaviour.
OPENER_MODEL = "openai/gpt-oss-20b"
_HAS_QUANTITY = re.compile(r"\d(?!\d*\s*(?:st|nd|rd|th)\b)")


def _opener_system(grade: int) -> str:
    from . import scope
    return (f"A Class {grade} child (India, NCERT maths) has just opened a maths tutoring chat. "
            "This is their FIRST message: there is no earlier conversation, and the tutor cannot "
            "see their book, homework or anything they did before.\n\n"
            "Answer ADVANCED if answering it properly needs maths beyond Class 5, even when it is "
            "asked in simple words without naming the topic. Class 1-5 maths covers: "
            + scope.CLASS_1_5_MATHS + ". Maths beyond Class 5 includes: "
            + scope.BEYOND_CLASS_5_MATHS + ".\n"
            "Otherwise answer NEW if the tutor could start helping right away -- even if the "
            "message is badly spelled, in broken grammar, mixes Hindi and English, or is just a "
            'topic word ("fractions", "tables"). This includes questions about everyday things, '
            "the child's own home, classroom, body or surroundings (\"name something at home that "
            'is round", "is my arm longer than my finger"), days, months and seasons, and general '
            '"why" questions: the tutor answers those from general knowledge, so nothing is missing.\n'
            "Answer CLARIFY only if the message depends on one SPECIFIC thing that was never given: "
            "a particular problem, sum, answer, number, list or earlier conversation it points to "
            '("it", "this one", "the other way", "mine", "my homework", "the same as before", '
            '"the answer"), or it is only a greeting or a feeling with no question at all.\n'
            "Spelling, grammar and punctuation never make a message CLARIFY.\n"
            "Reply with one word: NEW, CLARIFY or ADVANCED.")


_OPENER_FEWSHOT = [
    ("hw 2 do long divison", "NEW"),
    ("wht is a evn numbr", "NEW"),
    ("tables", "NEW"),
    ("why we carry over when adding", "NEW"),
    ("is it correct", "CLARIFY"),
    ("help me with this one", "CLARIFY"),
    ("good morning", "CLARIFY"),
    ("the one we did", "CLARIFY"),
]


def classify_opener(question: str, grade: int = 3, chat_fn=None) -> str:
    """'NEW', 'CLARIFY' or 'ADVANCED' for a session's first message.
    chat_fn(messages) is injectable for tests; never raises. A message with
    a quantity returns 'NEW' without a call (scope is then checked by the
    caller)."""
    if _HAS_QUANTITY.search(question or ""):
        return "NEW"
    messages = [{"role": "system", "content": _opener_system(grade)}]
    for ex, lab in _OPENER_FEWSHOT:
        messages += [{"role": "user", "content": ex}, {"role": "assistant", "content": lab}]
    messages.append({"role": "user", "content": question})
    try:
        if chat_fn is None:
            from . import llm_client, scope
            # Its own target name: llm_client keys 429 cooldowns by target
            # name, and Groq limits are per model. Same settings as the scope
            # check, since this call also makes the scope judgement.
            targets = [llm_client.Target("groq-opener", llm_client.GROQ_URL, "GROQ_API_KEY", OPENER_MODEL)]
            chat_fn = lambda msgs: llm_client.chat(msgs, params=scope.SCOPE_PARAMS, targets=targets)
        text = (chat_fn(messages).get("text") or "").upper()
    except Exception:
        return "NEW"
    found = re.findall(r"\b(NEW|CLARIFY|ADVANCED)\b", text)
    return found[-1] if found else "NEW"


def resolve_question(
    question: str,
    active_turns: list[dict] | None = None,
    grade: int = 3,
    opener_fn=None,
) -> Resolution:
    original = (question or "").strip()
    if not original:
        return Resolution("", "", "", "FRAGMENT", 1.0, False, False, False)

    previous = _last_user(active_turns)
    if not previous:
        # The session's FIRST message. v1 always treated it as NEW, so an
        # opener with nothing to refer to ("Which is the bigger one?",
        # "What about mine?") got a lesson instead of a clarifying question,
        # and the child's next, concrete problem was then never graded
        # in the paper-eval v1 run. FRAGMENT here makes the caller ask what
        # the child means without opening an episode.
        asked_model = not _HAS_QUANTITY.search(original)
        label = classify_opener(original, grade=grade, chat_fn=opener_fn)
        if label == "CLARIFY":
            return Resolution(original, original, "", "FRAGMENT", 0.9, False, False, False,
                              scope_checked=True)
        if label == "ADVANCED":
            return Resolution(original, original, "", "BEYOND_PRIMARY", 0.9, False, False, False,
                              scope_checked=True)
        return Resolution(
            original, original, original, "NEW", 1.0, False, True, True,
            scope_checked=asked_model,
        )

    # Generic conversational-act guardrails. These are NOT maths scenarios:
    # they classify discourse markers whose conversational function is
    # unambiguous when a previous tutor response exists.
    if re.fullmatch(
        r"(?:no|nope|nah|not really|that's not it|that is not it|"
        r"thats not it|not what i meant|you misunderstood|"
        r"that's wrong|that is wrong|thats wrong)\s*[.!?]*",
        original,
        flags=re.I,
    ):
        return Resolution(
            original=original,
            resolved_question=original,
            retrieval_query="",
            mode="CORRECTION",
            confidence=0.99,
            changed=False,
            use_rag=False,
            use_verifier=False,
        )

    # Safe, domain-agnostic grammatical substitution for the known pattern.
    direct = _deterministic_math_followup(original, previous)
    if direct:
        return Resolution(
            original=original,
            resolved_question=direct,
            retrieval_query=direct,
            mode="MATH_FOLLOWUP",
            confidence=1.0,
            changed=True,
            use_rag=True,
            use_verifier=True,
        )

    try:
        routed = _llm_route(original, active_turns, grade=grade)
    except Exception:
        routed = None

    if routed is not None:
        return routed

    # Conservative failure mode: do not invent a query. Let the tutor use the
    # live conversation to ask/answer a clarification instead of bad RAG.
    return Resolution(
        original, original, "", "FRAGMENT", 0.0, False, False, False
    )
