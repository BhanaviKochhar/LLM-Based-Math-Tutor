"""eval/intent_spike.py — measure the intent classifier before the controller
depends on it (Tier B risk gate).

Runs a labeled set of realistic Class 1-5 student turns through
intent.classify_intent and reports overall accuracy, per-label recall, and a
confusion breakdown. If accuracy is high, free-text intent can be first-class;
if it's shaky on some labels, we lean on the UI buttons for those and rely on
the classifier only where it's reliable.

Run:
    python -m eval.intent_spike            # live (needs GROQ_API_KEY/HF_TOKEN)
    python -m eval.intent_spike --mock     # offline: uses keyword fallback only
    python -m eval.intent_spike --sleep 2  # pace between calls if you hit 429s

Each case: (turn, context, expected). `context` is what the tutor just said,
which the classifier may use to disambiguate.
"""
from __future__ import annotations

import argparse
import time
from collections import defaultdict

from scripts.llm import intent

_INVITE = "Now you try — what do you think?"
_ASKED_ATTEMPT = "What answer did you get?"

# (turn, context, expected_label)
CASES = [
    # --- attempts (incl. restate, bare number, approach) ---
    ("56", _ASKED_ATTEMPT, "ATTEMPT"),
    ("is it 12?", _INVITE, "ATTEMPT"),
    ("i think its 20", _INVITE, "ATTEMPT"),
    ("you add 7 and 5", _INVITE, "ATTEMPT"),
    ("how many mangoes again", _INVITE, "ATTEMPT"),
    ("maybe 7 left over", _ASKED_ATTEMPT, "ATTEMPT"),
    ("5 + 3 = 8", _ASKED_ATTEMPT, "ATTEMPT"),
    ("i did 40 then took away 5", _INVITE, "ATTEMPT"),
    ("42?", _ASKED_ATTEMPT, "ATTEMPT"),
    ("i think we multiply", _INVITE, "ATTEMPT"),
    # --- hint requests ---
    ("give me a hint", _INVITE, "HINT"),
    ("hint pls", _INVITE, "HINT"),
    ("i need a little help to start", _INVITE, "HINT"),
    ("where do i begin", _INVITE, "HINT"),
    ("im stuck can you hint", _INVITE, "HINT"),
    # --- solve requests ---
    ("just tell me the answer", _INVITE, "SOLVE"),
    ("show me how to do it", _INVITE, "SOLVE"),
    ("whats the answer", _INVITE, "SOLVE"),
    ("can you solve it", _INVITE, "SOLVE"),
    ("i dont want to try just show me", _INVITE, "SOLVE"),
    # --- give up ---
    ("i dont know", _INVITE, "GIVE_UP"),
    ("idk", _ASKED_ATTEMPT, "GIVE_UP"),
    ("this is too hard", _INVITE, "GIVE_UP"),
    ("i cant do it", _INVITE, "GIVE_UP"),
    ("i give up", _INVITE, "GIVE_UP"),
    ("i not know add number teach me", _INVITE, "GIVE_UP"),
    # --- new question ---
    ("what is 8 times 3", _ASKED_ATTEMPT, "NEW_QUESTION"),
    ("can we do fractions now", _INVITE, "NEW_QUESTION"),
    ("how do i subtract big numbers", _INVITE, "NEW_QUESTION"),
    ("what about division", _INVITE, "NEW_QUESTION"),
]


def main():
    ap = argparse.ArgumentParser(description="Intent classifier spike.")
    ap.add_argument("--mock", action="store_true",
                    help="offline: force keyword fallback (no API)")
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()

    # In mock mode, force the classifier to the keyword fallback by injecting a
    # classify_fn that returns None (so classify_intent falls back).
    mock_fn = (lambda t: None) if args.mock else None

    correct = 0
    per_label = defaultdict(lambda: [0, 0])   # label -> [right, total]
    confusion = defaultdict(lambda: defaultdict(int))  # expected -> got -> n

    print(f"{'expected':>13}  {'got':>13}   turn")
    print("-" * 64)
    for turn, ctx, expected in CASES:
        got = intent.classify_intent(turn, context=ctx, classify_fn=mock_fn)
        ok = got == expected
        correct += ok
        per_label[expected][1] += 1
        per_label[expected][0] += ok
        confusion[expected][got] += 1
        flag = "" if ok else "  <-- MISS"
        print(f"{expected:>13}  {got:>13}   {turn[:34]}{flag}")
        if not args.mock:
            time.sleep(args.sleep)

    n = len(CASES)
    print(f"\noverall accuracy: {correct}/{n} = {correct / n:.0%}")
    print("\nper-label recall:")
    for lab in intent.LABELS:
        right, total = per_label[lab]
        if total:
            print(f"  {lab:>13}: {right}/{total} = {right / total:.0%}")

    print("\nconfusion (expected -> got: count), misses only:")
    for exp in intent.LABELS:
        for got, cnt in confusion[exp].items():
            if got != exp:
                print(f"  {exp} -> {got}: {cnt}")


if __name__ == "__main__":
    main()