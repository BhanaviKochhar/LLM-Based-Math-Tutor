"""scripts/llm/smoke_live.py — real end-to-end smoke test.

One command to confirm the whole MVP path works once your keys and index are
in place: retrieval -> streaming generation (Groq primary, HF-router
fallback) -> sympy verification, for a few representative questions. Tokens
print live so you can see streaming actually happening.

Run from the repo root:
    python -m scripts.llm.smoke_live
    python -m scripts.llm.smoke_live --hint                 # also pull Hint 1
    python -m scripts.llm.smoke_live -q "What is 12 / 4?" -g 3   # custom Q

Needs:
    .env with GROQ_API_KEY (primary) and/or HF_TOKEN (fallback)
    data/chromadb built   ->  python scripts/load_chromadb.py

Exit codes:
    0  at least one question completed a full round-trip
    1  every question failed to stream (plumbing problem)
    2  preflight failed (missing keys or missing/broken index)

A verification *mismatch* is reported (in red) but does NOT fail the smoke
test — the pipeline still worked; a mismatch points at model quality, which
is exactly what you want surfaced.
"""
from __future__ import annotations

import argparse
import os
import sys

# Load .env early so keys placed there are visible to the preflight check.
try:  # pragma: no cover
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


# Representative coverage: arithmetic, word problem, conceptual, trap/refusal.
DEFAULT_CASES = [
    ("What is 7 times 8?", 3, "arithmetic — should verify"),
    ("I have 8 balloons and 3 fly away. How many are left?", 1, "word problem — should verify"),
    ("What is a fraction?", 4, "conceptual — answers, not verifiable"),
    ("What is the square root of 144?", 2, "trap — should refuse"),
]


# --- tiny ANSI helpers (no color when output isn't a terminal) -------------
def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else s


def GREEN(s):  return _c("32", s)
def RED(s):    return _c("31", s)
def YELLOW(s): return _c("33", s)
def DIM(s):    return _c("2", s)
def BOLD(s):   return _c("1", s)


def preflight() -> None:
    """Fail early and clearly if keys or the vector store aren't ready."""
    has_groq = bool(os.environ.get("GROQ_API_KEY"))
    has_hf = bool(os.environ.get("HF_TOKEN"))
    if not (has_groq or has_hf):
        print(RED("✗ No API key found."))
        print("  Set GROQ_API_KEY (primary) and/or HF_TOKEN (fallback) in your .env.")
        sys.exit(2)
    keys = [k for k, present in
            (("GROQ_API_KEY", has_groq), ("HF_TOKEN", has_hf)) if present]
    print(DIM(f"keys: {', '.join(keys)}"))

    # Confirm the Chroma index answers a trivial query.
    try:
        from scripts.retrieval import retrieve

        retrieve("test", 1)
    except Exception as e:  # noqa: BLE001
        print(RED(f"✗ Retrieval failed: {e}"))
        print("  Build the vector store first:  python scripts/load_chromadb.py")
        print("  (and run this from the repo root so data/ resolves)")
        sys.exit(2)
    print(DIM("index: data/chromadb reachable"))


def _print_verdict(v: dict) -> None:
    match = v.get("match")
    if match is True:
        print(GREEN(f"   ✓ verified: computed {v['computed']} == answer {v['model_value']}"))
    elif match is False:
        print(RED(f"   ✗ mismatch: computed {v['computed']} != answer {v['model_value']}"))
    else:
        print(DIM(f"   – not verified ({v.get('note')})"))


def run_case(question: str, grade: int, note: str, do_hint: bool = False) -> bool:
    """One full retrieve -> stream -> verify round-trip. Returns True if the
    answer streamed (regardless of the verification verdict)."""
    from scripts.llm import pipeline

    print()
    print(BOLD(f"Q (Class {grade}): {question}"))
    print(DIM(f"   [{note}]"))

    turn = pipeline.prepare(question, grade)
    print(DIM(f"   retrieved {len(turn.chunks)} chunks · "
              f"source: {turn.source or 'n/a'} · level: {turn.level}"))

    if do_hint:
        try:
            hint = pipeline.get_hint(question, grade, turn.chunks, turn.level, 1)
            print(YELLOW(f"   Hint 1: {hint}"))
        except Exception as e:  # noqa: BLE001
            print(RED(f"   hint failed: {e}"))

    print("   answer: ", end="", flush=True)
    got_any = False
    for piece in turn.stream():
        got_any = True
        sys.stdout.write(piece)
        sys.stdout.flush()
    print()

    info = {}
    try:
        info = turn._handle.as_result() if turn._handle else {}
    except Exception:  # noqa: BLE001
        pass
    if info.get("provider"):
        print(DIM(f"   [provider: {info.get('provider')} · {info.get('latency_s')}s]"))

    if not got_any:
        print(RED("   ✗ no tokens streamed — check keys/providers"))
        if info.get("attempts"):
            print(DIM(f"     attempts: {info['attempts']}"))
        return False

    _print_verdict(turn.finalize())
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="Live end-to-end smoke test for the tutor pipeline.")
    ap.add_argument("-q", "--question", help="run a single custom question instead of the defaults")
    ap.add_argument("-g", "--grade", type=int, default=3, help="grade for --question (1-5)")
    ap.add_argument("--hint", action="store_true", help="also pull Hint 1 for each question")
    args = ap.parse_args()

    preflight()

    if args.question:
        if not 1 <= args.grade <= 5:
            print(RED("grade must be 1-5"))
            sys.exit(2)
        cases = [(args.question, args.grade, "custom")]
    else:
        cases = DEFAULT_CASES

    completed = 0
    for q, g, note in cases:
        try:
            if run_case(q, g, note, do_hint=args.hint):
                completed += 1
        except Exception as e:  # noqa: BLE001
            print(RED(f"   ✗ error: {e}"))

    print()
    print(BOLD(f"{completed}/{len(cases)} questions completed a full "
               f"retrieve→stream→verify round-trip."))
    sys.exit(0 if completed else 1)


if __name__ == "__main__":
    main()
