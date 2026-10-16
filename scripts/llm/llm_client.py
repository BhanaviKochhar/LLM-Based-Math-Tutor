"""scripts/llm/llm_client.py — one streaming LLM client for the whole app.

Primary target: Groq (direct, OpenAI-compatible endpoint).
Fallbacks:      Hugging Face Inference Providers router (non-Groq providers).

Targets are tried in order. Fallback happens only *before* the first token
of a target; once a target has emitted a token we commit to it, because a
half-streamed answer can't be un-sent. Missing API keys simply disable
their targets rather than raising.

Within a target, multiple keys rotate: GROQ_API_KEY may hold either one key
or (via GROQ_API_KEYS, comma-separated, plural) several, round-robinned
across calls so load spreads evenly rather than always hitting the first
key. A 429 on one key gets a bounded exponential backoff on that SAME key
before moving on to the next key for this target — only after every key for
a target is exhausted does the next target get tried. A key that keeps
429-ing gets a short cooldown so concurrent calls stop hammering it.

Env:
    GROQ_API_KEY    — one Groq key (single-key mode)
    GROQ_API_KEYS   — comma-separated Groq keys (rotation mode; takes
                      priority over GROQ_API_KEY if both are set)
    HF_TOKEN        — enables the router fallbacks (single key only)

Public surface:
    stream(messages, params=None, targets=None, handle=None) -> generator[str]
    chat(messages, params=None, targets=None) -> result dict
    StreamHandle                      — carries text + metadata after a stream
    default_targets(model) -> list[Target]
    groq_key_count() -> int
    default_max_workers(per_key=2) -> int
    run_batch(jobs, call_fn, checkpoint_path=None, max_workers=None,
              job_id_key="id") -> list[dict]
        -- runs call_fn(job) for many independent jobs concurrently, with
           incremental JSONL checkpointing so a multi-thousand-call run is
           resumable after a crash/interruption (an eval-harness concern,
           not a production-serving one; the live app calls chat()/stream()
           for one turn at a time and never touches this).

`openai` and `python-dotenv` are imported lazily so this module (and every
module that builds on it) can be imported and unit-tested without them.
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

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

# Per-key 429 handling: bounded retries on the SAME key, exponential backoff
# (respecting a Retry-After header if the provider sends one), then a short
# cooldown so other concurrent calls skip that key for a while too.
_MAX_RETRIES_PER_KEY = 2
_BACKOFF_BASE_S = 1.0
_BACKOFF_CAP_S = 8.0
_KEY_COOLDOWN_S = 20.0


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

# Round-robin start offset per target name, so consecutive calls spread
# across keys instead of always starting at the first one.
_rotation_counters: dict[str, int] = {}
_rotation_lock = threading.Lock()

# Keys currently cooling down after repeated 429s, keyed by (target.name, key_id).
_key_cooldown_until: dict[tuple[str, str], float] = {}
_cooldown_lock = threading.Lock()


def _keys_for(target: "Target") -> list[str]:
    """The keys configured for this target, in stable (file) order.

    A plural env var (key_env + "S", e.g. GROQ_API_KEY -> GROQ_API_KEYS)
    holding a comma-separated list takes priority if set and non-empty;
    otherwise falls back to the single key_env value. HF_TOKEN has no
    plural form today, so this is a no-op extra lookup for HF targets.
    """
    plural = os.environ.get(f"{target.key_env}S")
    if plural and plural.strip():
        return [k.strip() for k in plural.split(",") if k.strip()]
    single = os.environ.get(target.key_env)
    return [single] if single else []


def _client_for(target: "Target") -> list[tuple[str, object]]:
    """Return [(key_id, OpenAI client), ...] for this target's configured
    keys, in stable order. Empty list if no key is set. key_id is a stable,
    non-secret position label ("k1", "k2", ...) for logging/cooldown
    tracking — never the key material itself."""
    keys = _keys_for(target)
    out: list[tuple[str, object]] = []
    for i, key in enumerate(keys):
        key_id = f"k{i + 1}"
        cache_key = (target.base_url, key)
        if cache_key not in _clients:
            from openai import OpenAI  # lazy: keeps this module import-safe offline

            _clients[cache_key] = OpenAI(base_url=target.base_url, api_key=key, timeout=60)
        out.append((key_id, _clients[cache_key]))
    return out


def _rotated(target_name: str, items: list) -> list:
    """Rotate `items` by an incrementing per-target offset, so successive
    calls start at a different key instead of always hammering the first."""
    n = len(items)
    if n <= 1:
        return list(items)
    with _rotation_lock:
        start = _rotation_counters.get(target_name, 0) % n
        _rotation_counters[target_name] = start + 1
    return items[start:] + items[:start]


def _in_cooldown(target_name: str, key_id: str) -> bool:
    with _cooldown_lock:
        until = _key_cooldown_until.get((target_name, key_id))
    return until is not None and time.monotonic() < until


def _start_cooldown(target_name: str, key_id: str) -> None:
    with _cooldown_lock:
        _key_cooldown_until[(target_name, key_id)] = time.monotonic() + _KEY_COOLDOWN_S


def _is_rate_limited(e: Exception) -> bool:
    status = getattr(e, "status_code", None)
    if status == 429:
        return True
    code = getattr(e, "code", None)
    return code == "rate_limit_exceeded" or "429" in str(e)


def _retry_after_s(e: Exception) -> float | None:
    response = getattr(e, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    value = headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


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


def _stream_once(client, target: "Target", messages, params, h: "StreamHandle"):
    """Try one (target, client) pair. Yields text deltas. Returns
    (tag, retry_after_s): tag is "ok" (committed+succeeded),
    "committed_error" (tokens flowed, then broke — caller must stop
    entirely), "rate_limited" (429, nothing streamed, caller may
    retry/rotate), or "error" (other failure, nothing streamed, caller may
    rotate). retry_after_s is the provider's own Retry-After hint, if any."""
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
        return "ok", None

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
            return "committed_error", None
        if _is_rate_limited(e):
            return "rate_limited", _retry_after_s(e)
        return "error", None


def stream(messages, params=None, targets=None, handle=None):
    """Yield text deltas from the first target/key that responds.

    Note: token counts aren't captured while streaming (providers differ on
    `stream_options` support, and we favour portability over usage stats in
    the live path). Use chat() when you don't need streaming.
    """
    params = {**DEFAULT_PARAMS, **(params or {})}
    targets = targets or default_targets()
    h = handle if handle is not None else StreamHandle()

    for target in targets:
        clients = _client_for(target)
        if not clients:
            h.attempts.append(f"{target.name}: skipped (no {target.key_env})")
            continue

        for key_id, client in _rotated(target.name, clients):
            if _in_cooldown(target.name, key_id):
                h.attempts.append(f"{target.name} {key_id}: skipped (cooling down after 429)")
                continue

            outcome = None
            for attempt in range(_MAX_RETRIES_PER_KEY + 1):
                gen = _stream_once(client, target, messages, params, h)
                retry_after = None
                try:
                    while True:
                        yield next(gen)
                except StopIteration as stop:
                    outcome, retry_after = stop.value
                if outcome == "ok":
                    return
                if outcome == "committed_error":
                    return
                if outcome == "rate_limited" and attempt < _MAX_RETRIES_PER_KEY:
                    backoff = retry_after if retry_after is not None else min(
                        _BACKOFF_BASE_S * (2 ** attempt), _BACKOFF_CAP_S)
                    time.sleep(min(backoff, _BACKOFF_CAP_S))
                    continue
                break  # "error", or rate_limited retries exhausted

            if outcome == "rate_limited":
                _start_cooldown(target.name, key_id)
            # Nothing emitted yet on this key — safe to try the next key/target.

    h.ok = False
    h.error = " | ".join(h.attempts) or "no targets available"


def chat(messages, params=None, targets=None) -> dict:
    """Non-streaming convenience built on stream(). Returns a result dict."""
    h = StreamHandle()
    for _ in stream(messages, params=params, targets=targets, handle=h):
        pass
    return h.as_result()


def groq_key_count() -> int:
    """How many Groq keys are currently configured (GROQ_API_KEYS if set,
    else 1 if only GROQ_API_KEY is set, else 0)."""
    return len(_keys_for(Target("groq-direct", GROQ_URL, "GROQ_API_KEY", DEFAULT_MODEL)))


def default_max_workers(per_key: int = 2) -> int:
    """A safe default concurrency for run_batch(): scales with the number of
    configured Groq keys so a bigger rotation pool can sustain more parallel
    calls without any single key seeing more than `per_key` at once."""
    return max(per_key, groq_key_count() * per_key)


def run_batch(
    jobs: list[dict],
    call_fn,
    *,
    checkpoint_path: str | Path | None = None,
    max_workers: int | None = None,
    job_id_key: str = "id",
) -> list[dict]:
    """Run call_fn(job) for many independent jobs concurrently.

    Each job is an opaque dict with a unique `job_id_key` value; call_fn
    receives the whole job and returns a result dict. Built for an eval
    harness running thousands of independent LLM calls (or independent
    multi-turn journeys, each internally sequential) — not used by the
    live tutoring app, which only ever needs one call at a time.

    If checkpoint_path is given, every result is appended to it as JSONL
    the moment it completes, and on a re-run any job whose id is already
    in that file is skipped rather than re-executed — the resumability a
    several-thousand-call run needs after a crash, a quota exhaustion, or
    a deliberate interruption.
    """
    done: dict = {}
    ckpt = Path(checkpoint_path) if checkpoint_path is not None else None
    if ckpt is not None and ckpt.exists():
        with open(ckpt, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                done[rec[job_id_key]] = rec

    pending = [j for j in jobs if j[job_id_key] not in done]
    results = list(done.values())
    if not pending:
        return results

    workers = max_workers if max_workers is not None else default_max_workers()
    write_lock = threading.Lock()
    fh = open(ckpt, "a", encoding="utf-8") if ckpt is not None else None

    def _run_one(job: dict) -> dict:
        res = call_fn(job)
        if job_id_key not in res:
            res = {job_id_key: job[job_id_key], **res}
        if fh is not None:
            with write_lock:
                fh.write(json.dumps(res, ensure_ascii=False, default=str) + "\n")
                fh.flush()
        return res

    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(_run_one, j) for j in pending]
            for fut in as_completed(futures):
                results.append(fut.result())
    finally:
        if fh is not None:
            fh.close()
    return results
