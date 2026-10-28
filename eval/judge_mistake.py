"""eval/judge_mistake.py -- the LLM judge for the MathDial "student mistake"
items (eval/datasets/mathdial_sample.jsonl): how a tutor reply handles a
child's wrong attempt. Same judge model and Groq target as eval/judge.py.

The judge sees the problem, the child's working, the correct answer, the
child's (wrong) answer and the confusion a teacher named for it, and the
tutor's reply -- never which condition wrote it -- and returns JSON:

  mistake_identified  true if the reply tells the child their answer is wrong
                      AND points to where or why it went wrong
  answer_revealed     true if the reply states the correct final answer
  guidance            1-5: how well the reply helps the child fix the mistake
                      themselves (5 = a clear next step or question they can act
                      on; 1 = no help, or simply the full solution handed over)
  quote               the words that support mistake_identified (or "")

Its numbers are used only if it agrees with the two raters' mini-sheet
(eval/make_mathdial_sheet.py), kappa at least 0.6 on mistake_identified.

CLI:
    python -m eval.judge_mistake --transcripts eval/results/system_runs_v2/mathdial_sample.jsonl \\
        --out eval/results/judge_runs/system_mathdial_sample.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from eval.baseline_runner import _item_id, load_items
from eval.judge import JUDGE_PARAMS, JUDGE_TARGETS
from scripts.llm import llm_client

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "eval" / "datasets" / "mathdial_sample.jsonl"

SYSTEM = """You grade one maths-tutor reply to a primary-school child (India, Class 1-5) who has shown \
their working for a word problem and asked whether their answer is right. The child's answer is wrong. \
Judge only the reply's text. Be strict and literal.

- mistake_identified: true only if the reply says the child's answer is not right AND points to where or \
why the working went wrong (the step, the operation, the misread number). Praise or a generic "let's check" \
is not enough.
- answer_revealed: true if the reply states the correct final answer anywhere.
- guidance, 1-5: 5 the child gets a clear next step or question they can act on to fix the mistake \
themselves; 3 some help but vague, or mixed with doing the work for them; 1 no useful help, or the whole \
solution simply handed over.
- quote: copy the words that show the mistake being identified ("" if none).

Reply with JSON only, reasoning first:
{"reasoning": "<1-3 sentences>", "mistake_identified": true|false, "answer_revealed": true|false, \
"guidance": n, "quote": "..."}"""


def build_messages(item: dict, reply: str) -> list[dict]:
    user = (f"Problem: {item['problem']}\n\nThe child's message (their working):\n{item['question']}\n\n"
            f"Correct answer: {item['expected_answer']}\nChild's answer: {item['student_answer']}\n"
            f"Where the child went wrong (teacher's note): {item.get('student_confusion') or 'not given'}\n\n"
            f"Tutor reply to grade:\n<<<\n{reply}\n>>>")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def parse(text: str) -> dict | None:
    text = re.sub(r"(?s)<think>.*?</think>", "", text or "")
    start = text.find("{")
    if start < 0:
        return None
    for end in range(len(text), start, -1):
        if text[end - 1] != "}":
            continue
        try:
            v = json.loads(text[start:end])
            break
        except json.JSONDecodeError:
            continue
    else:
        return None
    if not isinstance(v.get("mistake_identified"), bool) or not isinstance(v.get("answer_revealed"), bool):
        return None
    if not isinstance(v.get("guidance"), int) or not 1 <= v["guidance"] <= 5:
        return None
    return v


def judge_one(item: dict, reply: str, chat_fn=None, retries: int = 1) -> dict:
    fn = chat_fn or (lambda msgs: llm_client.chat(msgs, params=JUDGE_PARAMS, targets=JUDGE_TARGETS))
    last = None
    for _ in range(retries + 1):
        last = fn(build_messages(item, reply))
        v = parse(last.get("text") or "")
        if v is not None:
            return {"ok": True, "verdict": v}
    return {"ok": False, "verdict": None, "raw": (last or {}).get("text"), "error": (last or {}).get("error")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcripts", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-workers", type=int, default=4)
    args = parser.parse_args()
    items = {_item_id(i): i for i in load_items(DATASET)}
    replies = {}
    for line in open(args.transcripts, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            if r.get("turns"):
                replies[r["id"]] = r["turns"][0].get("response") or ""   # the reply to the child's attempt
    jobs = [{"id": i} for i in items if i in replies]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    results = llm_client.run_batch(jobs, lambda j: judge_one(items[j["id"]], replies[j["id"]]),
                                   checkpoint_path=out, max_workers=args.max_workers)
    print(f"judged {sum(1 for r in results if r.get('ok'))}/{len(jobs)} -> {out}")


if __name__ == "__main__":
    main()
