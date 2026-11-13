"""eval/make_rating_sheet.py -- build the blind human rating sheet that
rates baseline (paper-eval-v1) against system (paper-eval-v2) replies and
audits the answer extractor (eval/answer_extraction.py). The items are drawn
fresh (SEED below), leaving out every item of the earlier round, whose key is
read from eval/blind_ratings/rating_key.json before it is replaced.

75 items, each answered by both conditions = 150 replies, shuffled, with
no condition shown:
  30 numeric curriculum items (all hard extraction cases first: replies
     the rules left undecided or where the old substring scorer and the new
     extractor disagree; the rest at random)
  20 conceptual curriculum items (judged against expected_key_idea)
  15 out-of-scope items (5 gloss, 7 decline incl. boundary cases, 3 probes)
  10 multi_turn conversations (the final turn, with the conversation so far)

Writes one workbook per rater (eval/blind_ratings/rating_sheet_rater_A.xlsx,
..._B.xlsx -- identical rows, rated independently) and the answer key
(eval/blind_ratings/rating_key.json: sheet row -> item id, condition). Raters
must not open the key. Same rubric text as the judge.

Run once:  python -m eval.make_rating_sheet
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from eval import answer_extraction
from eval.baseline_runner import _grade_of, _item_id, load_items
from eval.judge import JUDGE_SYSTEM, item_context
from eval.score_transcripts import _load_checkpoint, ground_truth_candidates, score_item

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ROOT / "eval" / "datasets"
RUNS = ROOT / "eval" / "results"
OUT = ROOT / "eval" / "blind_ratings"
# The rated round (decided 2026-10-27): baseline paper-eval-v1 against system
# paper-eval-v2, on 75 items the earlier round (seed 20261023, pre-fix system
# replies) did not use, so raters see nothing they have rated before.
SEED = 20261027
SYSTEM_RUNS = RUNS / "system_runs_v2"
EARLIER_ROUND_KEY = OUT / "rating_key.json"


def _earlier_items() -> set[str]:
    if not EARLIER_ROUND_KEY.exists():
        return set()
    key = json.load(open(EARLIER_ROUND_KEY, encoding="utf-8"))
    if key.get("seed") == SEED:   # already this round's key: nothing to exclude beyond what it records
        return set(key.get("excluded_earlier_items") or [])
    return {r["item_id"] for r in key["rows"]}


EXCLUDE = _earlier_items()


def _pairs(dataset: str) -> list[tuple[dict, dict, dict]]:
    path = DATASETS / dataset
    items = load_items(path)
    stem = path.stem
    b = _load_checkpoint(RUNS / "baseline_runs" / f"{stem}.jsonl")
    s = _load_checkpoint(SYSTEM_RUNS / f"{stem}.jsonl")
    return [(it, b[_item_id(it)], s[_item_id(it)]) for it in items if _item_id(it) not in EXCLUDE
            and b.get(_item_id(it), {}).get("turns") and s.get(_item_id(it), {}).get("turns")]


def _old_substring_correct(item: dict, journey: dict) -> bool:
    low = " ".join((journey["turns"][-1].get("response") or "").lower().split())
    return any(" ".join(c.lower().split()) in low for c in ground_truth_candidates(item))


def select(rng: random.Random) -> list[tuple[str, dict, dict, dict]]:
    curriculum = [p for g in range(1, 6) for p in _pairs(f"curriculum_benchmark_class{g}.jsonl")]
    numeric = [p for p in curriculum if ground_truth_candidates(p[0])]
    conceptual = [p for p in curriculum if not ground_truth_candidates(p[0]) and p[0].get("expected_key_idea")]

    def hard(p):
        it, b, s = p
        return any(score_item(it, j).get("needs_llm_extraction")
                   or (score_item(it, j)["correct"] is not None
                       and score_item(it, j)["correct"] != _old_substring_correct(it, j))
                   for j in (b, s))
    hard_numeric = [p for p in numeric if hard(p)]
    rng.shuffle(hard_numeric)
    picked_numeric = hard_numeric[:15]
    rest = [p for p in numeric if p not in picked_numeric]
    picked_numeric += rng.sample(rest, 30 - len(picked_numeric))

    oos = _pairs("out_of_scope.jsonl")
    by_kind = {k: [p for p in oos if expected_and_boundary(p[0]) == k] for k in
               ("gloss", "decline_boundary", "decline_plain", "answer")}
    picked_oos = (rng.sample(by_kind["gloss"], 5) + rng.sample(by_kind["decline_boundary"], 4)
                  + rng.sample(by_kind["decline_plain"], 3) + rng.sample(by_kind["answer"], 3))

    data = json.load(open(DATASETS / "multi_turn.json", encoding="utf-8"))
    b = _load_checkpoint(RUNS / "baseline_runs" / "multi_turn.jsonl")
    s = _load_checkpoint(SYSTEM_RUNS / "multi_turn.jsonl")
    mt = [(c, b[c["conversation_id"]], s[c["conversation_id"]]) for c in data["conversations"]
          if c["conversation_id"] not in EXCLUDE
          and b.get(c["conversation_id"], {}).get("turns") and s.get(c["conversation_id"], {}).get("turns")]
    picked_mt = rng.sample(mt, 10)

    return ([("numeric", *p) for p in picked_numeric] + [("conceptual", *p) for p in rng.sample(conceptual, 20)]
            + [("out_of_scope", *p) for p in picked_oos] + [("multi_turn", *p) for p in picked_mt])


def expected_and_boundary(item: dict) -> str:
    from eval.score_transcripts import expected_oos_behavior
    e = expected_oos_behavior(item)
    if e == "decline":
        return "decline_boundary" if item.get("boundary_case") else "decline_plain"
    return e


HEADERS = ["row", "class", "child's message", "conversation so far", "ground truth / what's expected",
           "tutor reply", "committed final answer", "answer correct?", "key idea", "teaches beyond Class 5?",
           "correctness 1-5", "grade fit 1-5", "clarity 1-5", "restraint 1-5", "hallucination?",
           "false claim, quoted", "why false / notes"]
WIDTHS = [6, 7, 40, 45, 40, 80, 22, 14, 12, 14, 12, 12, 12, 12, 13, 35, 35]


def human_context(item: dict) -> str:
    """The judge's ground-truth text, minus the lines addressed to the judge."""
    text = item_context(item)
    text = re.sub(r"(?m)^key_idea is n/a\.?$|^teaches_advanced is null\.?$|key_idea is n/a; teaches_advanced is null\.", "", text)
    text = text.replace(" -- set key_idea by whether the reply gets this idea across.", "")
    text = re.sub(r"Set teaches_advanced to true if (.*?); key_idea is n/a\.",
                  r"Mark 'teaches beyond Class 5?' Yes if \1.", text)
    return "\n".join(l for l in text.splitlines() if l.strip())


def build_rows(selection, rng: random.Random) -> tuple[list[list], list[dict]]:
    rows, key = [], []
    for stratum, item, b, s in selection:
        for condition, journey in (("baseline", b), ("system", s)):
            rows.append((stratum, item, condition, journey))
    rng.shuffle(rows)
    out = []
    for n, (stratum, item, condition, journey) in enumerate(rows, 1):
        turns = journey["turns"]
        convo = "\n\n".join(f"Child: {t['student']}\nTutor: {t.get('response') or ''}" for t in turns[:-1])
        out.append([n, _grade_of(item) or "", turns[-1]["student"], convo, human_context(item),
                    turns[-1].get("response") or ""])
        commit = answer_extraction.committed_answer(turns[-1].get("response") or "")
        key.append({"row": n, "item_id": _item_id(item), "condition": condition, "stratum": stratum,
                    "extractor_segment": commit.segment, "extractor_source": commit.source})
    return out, key


def write_workbook(path: Path, rows: list[list]) -> None:
    wb = Workbook()
    ins = wb.active
    ins.title = "Instructions"
    lines = [
        "Blind rating sheet -- rate on your own, don't discuss until both sheets are done.",
        "You don't know which system wrote each reply, and you shouldn't try to guess.",
        "For each row, read the child's message (and the conversation so far, if any), the ground truth, and the tutor reply.",
        "Fill the coloured columns. Leave a cell blank only if it truly doesn't apply (use N/A where offered).",
        "committed final answer: copy briefly the final answer the reply commits to; NONE if it gives none.",
        "answer correct?: does that committed answer match the ground truth? Unclear if you can't tell.",
        "key idea: for items with an 'Expected key idea', does the reply get it across? Otherwise n/a.",
        "teaches beyond Class 5?: for out-of-scope items only (ground truth says 'Expected behaviour'); otherwise N/A.",
        "hallucination: Yes only if the reply states something false as fact. Then quote the false words and say why.",
        "",
        "Rubric (same text the LLM judge gets):",
        *JUDGE_SYSTEM.split("\n"),
    ]
    for i, line in enumerate(lines, 1):
        ins.cell(row=i, column=1, value=line)
    ins.column_dimensions["A"].width = 160

    ws = wb.create_sheet("Ratings")
    ws.append(HEADERS)
    for r in rows:
        ws.append(r)
    for i, w in enumerate(WIDTHS, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    fill = PatternFill("solid", fgColor="FFF4D6")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    last = len(rows) + 1
    for row in ws.iter_rows(min_row=2, max_row=last):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if cell.column >= 7:
                cell.fill = fill
    ws.freeze_panes = "C2"

    def dv(options: str, col: str):
        v = DataValidation(type="list", formula1=f'"{options}"', allow_blank=True)
        ws.add_data_validation(v)
        v.add(f"{col}2:{col}{last}")
    dv("Yes,No,Unclear,N/A", "H")
    dv("present,partial,absent,n/a", "I")
    dv("Yes,No,N/A", "J")
    for col in "KLMN":
        dv("1,2,3,4,5", col)
    dv("Yes,No", "O")
    wb.save(path)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rater", default=None,
                        help="write ONE extra blank sheet (e.g. C) with the same rows; the key and "
                             "any filled sheets are left untouched")
    args = parser.parse_args()

    rng = random.Random(SEED)
    selection = select(rng)
    rows, key = build_rows(selection, rng)
    OUT.mkdir(parents=True, exist_ok=True)
    if args.rater:
        existing = json.load(open(OUT / "rating_key.json", encoding="utf-8"))["rows"]
        if [(k["row"], k["item_id"], k["condition"]) for k in existing] != \
           [(k["row"], k["item_id"], k["condition"]) for k in key]:
            raise SystemExit("rows differ from rating_key.json -- refusing to write a mismatched sheet")
        path = OUT / f"rating_sheet_rater_{args.rater}.xlsx"
        if path.exists():
            raise SystemExit(f"{path} already exists -- not overwriting it")
        write_workbook(path, rows)
        print(f"wrote {path} ({len(rows)} rows, same as rating_key.json)")
        return
    for rater in ("A", "B"):
        write_workbook(OUT / f"rating_sheet_rater_{rater}.xlsx", rows)
    with open(OUT / "rating_key.json", "w", encoding="utf-8") as f:
        json.dump({"seed": SEED, "system_runs": SYSTEM_RUNS.name, "excluded_earlier_items": sorted(EXCLUDE),
                   "rows": key}, f, indent=1, ensure_ascii=False)
    counts = {}
    for k in key:
        counts[k["stratum"]] = counts.get(k["stratum"], 0) + 1
    print(f"{len(rows)} rows -> {OUT}  by stratum: {counts}")


if __name__ == "__main__":
    main()
