"""scripts/llm/llm_client.py — one streaming LLM client for the whole app.

Primary target: Groq (direct, OpenAI-compatible endpoint).
Fallbacks:      Hugging Face Inference Providers router (non-Groq providers).

Targets are tried in order. Fallback happens only *before* the first token
of a target; once a target has emitted a token we commit to it, because a
half-streamed answer can't be un-sent. Missing API keys simply disable
their targets rather than raising.

Env:
    GROQ_API_KEY   — enables the primary target
    HF_TOKEN       — enables the router fallbacks

Public surface:
    stream(messages, params=None, targets=None, handle=None) -> generator[str]
    chat(messages, params=None, targets=None) -> result dict
    StreamHandle                      — carries text + metadata after a stream
    default_targets(model) -> list[Target]

`openai` and `python-dotenv` are imported lazily so this module (and every
module that builds on it) can be imported and unit-tested without them.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

# Load a .env if python-dotenv is available; never a hard dependency.
try:  # pragma: no cover - trivial
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

GROQ_URL = "https://api.groq.com/openai/v1"
HF_URL = "https://router.huggingface.co/v1"

DEFAULT_MODEL = "openai/gpt-oss-120b"

# Matches the values used by ask.py / tutor.py in the prompt-engineering branch.
DEFAULT_PARAMS = {
    "temperature": 0.3,
    "max_tokens": 1024,
    "top_p": 0.9,
    "frequency_penalty": 0.3,
}


@dataclass(frozen=True)
class Target:
    """One place we can send a request. `name` shows up in the run logs."""
    name: str
    base_url: str
    key_env: str
    model: str


def default_targets(model: str = DEFAULT_MODEL) -> list["Target"]:
    """Groq first, then two HF-router providers.

    We deliberately do NOT route to Groq *through* the HF router as a
    fallback — if Groq is down, going back to Groq via HF gains nothing.
    """
    return [
        Target("groq-direct", GROQ_URL, "GROQ_API_KEY", model),
        Target("hf-nscale", HF_URL, "HF_TOKEN", f"{model}:nscale"),
        Target("hf-deepinfra", HF_URL, "HF_TOKEN", f"{model}:deepinfra"),
    ]


# Clients are cached per (base_url, key) so repeated calls reuse connections.
_clients: dict[tuple[str, str], object] = {}


def _client_for(target: "Target"):
    """Return an OpenAI client for this target, or None if its key is unset."""
    key = os.environ.get(target.key_env)
    if not key:
        return None
    cache_key = (target.base_url, key)
    if cache_key not in _clients:
        from openai import OpenAI  # lazy: keeps this module import-safe offline

        _clients[cache_key] = OpenAI(base_url=target.base_url, api_key=key, timeout=60)
    return _clients[cache_key]


class StreamHandle:
    """Mutable holder so callers can read the full text and run metadata
    *after* a `stream(...)` generator has been exhausted."""

    def __init__(self) -> None:
        self.text = ""
        self.ok = False
        self.provider = None
        self.model_id = None
        self.finish_reason = None
        self.latency_s = None
        self.prompt_tokens = None
        self.completion_tokens = None
        self.error = None
        self.attempts: list[str] = []  # human-readable trail of what was tried

    def as_result(self) -> dict:
        """Shaped exactly like common.chat()'s result dict, so common.log_run
        and existing analysis code accept it unchanged."""
        return {
            "ok": self.ok,
            "model_id": self.model_id,
            "provider": self.provider,
            "text": self.text.strip(),
            "finish_reason": self.finish_reason,
            "latency_s": self.latency_s,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "error": self.error,
            "attempts": self.attempts,
        }


def stream(messages, params=None, targets=None, handle=None):
    """Yield text deltas from the first target that responds.

    Note: token counts aren't captured while streaming (providers differ on
    `stream_options` support, and we favour portability over usage stats in
    the live path). Use chat() when you don't need streaming.
    """
    params = {**DEFAULT_PARAMS, **(params or {})}
    targets = targets or default_targets()
    h = handle if handle is not None else StreamHandle()

    for target in targets:
        client = _client_for(target)
        if client is None:
            h.attempts.append(f"{target.name}: skipped (no {target.key_env})")
            continue

        t0 = time.perf_counter()
        started = False
        try:
            resp = client.chat.completions.create(
                model=target.model, messages=messages, stream=True, **params
            )
            for chunk in resp:
                choices = getattr(chunk, "choices", None)
                if not choices:
                    continue
                choice = choices[0]
                if getattr(choice, "finish_reason", None):
                    h.finish_reason = choice.finish_reason
                delta = getattr(choice, "delta", None)
                piece = getattr(delta, "content", None) if delta else None
                if piece:
                    started = True
                    h.text += piece
                    yield piece

            h.ok = True
            h.provider = target.name
            h.model_id = target.model
            h.latency_s = round(time.perf_counter() - t0, 3)
            h.attempts.append(f"{target.name}: ok")
            return

        except Exception as e:  # noqa: BLE001 — we want to fall through
            msg = f"{target.name}: {e}"
            h.attempts.append(msg)
            if started:
                # Committed to this target once tokens flowed; stop here.
                h.provider = target.name
                h.model_id = target.model
                h.latency_s = round(time.perf_counter() - t0, 3)
                h.error = msg
                h.ok = False
                return
            # Nothing emitted yet — safe to try the next target.
            continue

    h.ok = False
    h.error = " | ".join(h.attempts) or "no targets available"


def chat(messages, params=None, targets=None) -> dict:
    """Non-streaming convenience built on stream(). Returns a result dict."""
    h = StreamHandle()
    for _ in stream(messages, params=params, targets=targets, handle=h):
        pass
    return h.as_result()
