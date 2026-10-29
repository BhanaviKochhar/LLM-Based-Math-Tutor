"""eval/judge_mistake_extra.py -- two more MathDial dimensions from the MRBench
tutor-evaluation taxonomy (Maurya et al., 2025; the BEA 2025 shared task),
judged on the same replies as eval/judge_mistake.py with the same judge model
and Groq target:

  mistake_location  does the reply point to the genuine mistake and where it is
                    in the child's working?
  actionability     is it clear from the reply what the child should do next?

Each takes MRBench's three labels: Yes | To some extent | No. The desired label
for both is Yes; results are reported as the desired annotation match rate
(the share of replies labelled Yes). No human labels exist for these two, so
they are reported as judge-only and exploratory.

CLI:
    python -m eval.judge_mistake_extra --transcripts eval/results/system_runs_v2/mathdial_sample.jsonl \\
        --out eval/results/judge_runs/system_mathdial_extra.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from eval.baseline_runner import _item_id, load_items
from eval.judge import JUDGE_PARAMS, JUDGE_TARGETS
from eval.judge_mistake import DATASET
from scripts.llm import llm_client

LABELS = ("Yes", "To some extent", "No")

SYSTEM = """You grade one maths-tutor reply to a primary-school child (India, Class 1-5) who has shown \
their working for a word problem and asked whether their answer is right. The child's answer is wrong. \
Judge only the reply's text. Be strict and literal. Use exactly one of: "Yes", "To some extent", "No".

- mistake_location: does the reply point to the child's genuine mistake and where it is in their working \
(the step, the number or the operation that went wrong)? "Yes" = the exact place is named; "To some \
extent" = the right area is hinted at but not pinned down; "No" = the mistake is not located, or a wrong \
place is named.
- actionability: is it clear from the reply what the child should do next? "Yes" = a concrete next step or \
question the child can act on; "To some extent" = a vague direction; "No" = no next step, or the whole \
solution is simply given so nothing is left for the child to do.

Reply with JSON only, reasoning first:
{"reasoning": "<1-3 sentences>", "mistake_location": "Yes|To some extent|No", \
"actionability": "Yes|To some extent|No"}"""


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
    if v.get("mistake_location") not in LABELS or v.get("actionability") not in LABELS:
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
                replies[r["id"]] = r["turns"][0].get("response") or ""
    jobs = [{"id": i} for i in items if i in replies]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    results = llm_client.run_batch(jobs, lambda j: judge_one(items[j["id"]], replies[j["id"]]),
                                   checkpoint_path=out, max_workers=args.max_workers)
    print(f"judged {sum(1 for r in results if r.get('ok'))}/{len(jobs)} -> {out}")


if __name__ == "__main__":
    main()
