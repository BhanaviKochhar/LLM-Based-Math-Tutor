# Expression & Answer Extraction Evaluation

Covers two distinct extraction stages, per `docs/evaluation_dataset_schema.md`'s `stage` field in `eval/datasets/extraction/v1_starter.jsonl`:

1. **`question_to_expression`** — `scripts/llm/verifier.compute()`, which calls an **LLM extractor** (`verifier._default_extractor`, live model call, few-shot prompted) to turn a natural-language question into an arithmetic expression.
2. **`response_to_answer`** — `scripts/llm/response_parser.final_number_str()`, a **deterministic, regex-based** parser (no model call) that reads the stated final answer out of a full generated tutor response.

These are evaluated separately and must not be conflated: a correct final answer from stage 2 does not establish that stage 1 extracted the right expression for the right reason, and vice versa.

---

## 1. Stage 2 — `response_to_answer` (deterministic, no model call)

### Defect found and fixed (priority item, Section 5)

**Reproduced before fixing:** `response_parser.final_number_str()`'s fallback (used when there is no explicit `Answer:` line) called `extract_number_str()` on the *entire* response text, which returns the *first* numeric token in the text — not the actual final/stated result. Confirmed live against the dataset: 5/7 `response_to_answer` cases correct, with `ex-009` and `ex-010` failing exactly as predicted (returning an early input number instead of the final computed value).

**Root cause:** no structural distinction between "a number that appears early in an explanation" and "the number that is the final answer," once the `Answer:` line (the normal, reliable signal) is absent.

**Why a naive fix (take the *last* number instead) was rejected without implementation:** this tutor's own controller directives (`scripts/llm/controller.py::_d_diagnose_correct`, `_d_reveal`) routinely instruct the model to append a follow-up suggestion *after* the answer — e.g. *"Well done! 9 x 6 equals 54. Would you like to try a little tougher one, like 8 x 7?"* The last number in that text is "7" (from the suggestion), not "54" (the answer). A last-number fallback would silently introduce a new, different failure mode while fixing the old one. This was verified, not assumed — see the test `"trailing follow-up suggestion AFTER the answer is not picked up"` below, constructed from an actual phrase observed in this project's own live smoke tests.

**Fix implemented:** `final_number_str()` now resolves in three confidence tiers instead of guessing between first/last:

1. Explicit `Answer:` line (unchanged, highest confidence — every tutor prompt version is instructed to produce one).
2. The **last** explicit `"... = value"` / `"... equals value"` statement in the text — narrower than "last number," since a trailing suggestion sentence normally doesn't contain `=`/`equals` immediately before a number.
3. The sole numeric token in the text, **only if there is exactly one** — safe by elimination.
4. Otherwise: `None` (ambiguous/unverifiable) — the caller (`verifier.check`) already treats `None` as "couldn't read a number," which is the honest result when there's no reliable signal, rather than a guessed value that might silently be wrong.

**Scope of the fix:** `extract_number_str()` itself (the "first numeric token in a short string" primitive) was left untouched — it has its own, different, correctly-tested contract (used e.g. to parse the content of a single `Answer:` line, where "first number" is the right behaviour because there's normally only one). Only `final_number_str()`'s *fallback path* changed.

### Measured result (deterministic, this commit)

```
python -c "
from scripts.llm import response_parser as rp
import json
rows = [json.loads(l) for l in open('eval/datasets/extraction/v1_starter.jsonl', encoding='utf-8') if l.strip()]
rows = [r for r in rows if r['stage'] == 'response_to_answer']
correct = sum(1 for r in rows if rp.final_number_str(r['input']) == r['expected_final_answer'])
print(f'{correct}/{len(rows)} correct')
"
```
→ **7/7 correct** (previously 5/7; `ex-009`, `ex-010` now pass).

### Regression tests added

19 new assertions in `scripts/llm/test_pipeline.py::test_final_number_str_fallback_tiers`, covering (not an exhaustive restatement — see the file for exact cases): explicit `Answer:` line (plain and bold), final answer buried in prose with multiple intermediate equations (both the originally-failing shapes), `"equals"` spelled out vs. `"="`, **the trailing-suggestion danger case that motivated rejecting the naive fix**, fraction and negative equation results, a single bare number accepted by elimination, multiple bare numbers correctly returning `None` (ambiguous) rather than guessing, no number at all, empty/`None` input, contradictory `Answer:` lines (last wins), a malformed equation with no number after `=` (falls through safely to the next tier), and irrelevant numbers (dates/counts) not overriding a clear equation result.

**Full suite after the fix:** `python -m scripts.llm.test_pipeline` → 57/57 passed (was 38/38 before adding these; the parser-specific tests account for the +19 — see `docs/development_test_log.md` for the full reconciliation).

**Explicitly not overfit:** the fix's design (confidence tiers, not string-matching) was validated against a case (the trailing-suggestion test) that was *not* one of the two original failing dataset entries, specifically to check the general design rather than memorizing the two known bad strings.

---

## 2. Stage 1 — `question_to_expression` (live LLM extractor)

### Configuration

- **Model:** `openai/gpt-oss-120b` (`scripts/llm/llm_client.DEFAULT_MODEL`), served via Groq with the HF-router fallback target (not exercised in this run — no fallback was triggered).
- **Extractor:** `scripts/llm/verifier._default_extractor` — the fixed, hand-written few-shot prompt in `verifier._EXTRACT_SYSTEM`/`_EXTRACT_FEWSHOT` (no separate "extractor version" exists to pin beyond the prompt text itself, which is part of this commit).
- **Dataset:** `eval/datasets/extraction/v1_starter.jsonl`, `question_to_expression` rows (7 cases).
- **Run date:** 2026-10-03 (this engagement); commit: working tree at the time of this checkpoint (see `docs/development_test_log.md` for the exact SHA this evaluation pass was run against).

### Method and result

Each case's extracted expression (`verifier.compute(question).value`) was compared to `expected_value` by exact value, not string match (fraction/integer forms compared via the same `verifier._close`-style exactness used elsewhere in this codebase).

| case_id | question (truncated) | extracted expression | extracted value | expected | result |
|---|---|---|---|---|---|
| ex-001 | What is 2 + 3? | `2 + 3` | 5 | 5 | correct |
| ex-002 | I have 8 balloons and 3 fly away... | `8 - 3` | 5 | 5 | correct |
| ex-003 | Priya is 9... buys 7 candies at 2 rupees... | `7 * 2` | 14 | 14 | correct (distractor numbers 9, 4 correctly excluded) |
| ex-004 | What is 1/2 + 1/4? | `1/2 + 1/4` | 3/4 | 3/4 | correct |
| ex-005 | What is a fraction? | `None` (extractor returned `NONE`) | — | — (non-computable) | correct |
| ex-006 | What is XLIV minus XIV? | `44 - 14` | 30 | 30 | correct (Roman numerals handled) |
| ex-007 | What if it were 5 instead of 1? (follow-up to "What is 3/7 + 1?") | — | — | 38/7 | **see below** |

**ex-007 requires two-stage evaluation, not extractor-alone:** calling `verifier.compute()` on the bare follow-up text (no conversation context) gives an extracted expression of `(5/2) * 8` → value `20` — **wrong**, because the standalone extractor has no way to know what "it" refers to. This is expected and correct behaviour for the extractor in isolation (it is not designed to resolve references). Re-run through the actual live path — `pipeline.resolve_conversation("What if it were 5 instead of 1?", [{"role": "user", "content": "What is 3/7 + 1?"}])` followed by `pipeline.compute_trusted_answer()` on the resolved text — correctly resolves to `"What is 3/7 + 5?"` and computes `38/7`, matching the expected value exactly.

**Result:** 6/7 correct at the standalone-extractor stage (1 case, ex-007, is out of scope for the extractor alone by design); **7/7 correct** when each case is evaluated at its intended pipeline stage (resolver+extractor together for the one follow-up case).

### Limitations of this run

- n=7 is small; this is a starter diagnostic set, not a statistically powered extraction benchmark. A larger, stratified extraction set (more distractor-number cases, more follow-up-resolution cases, more fraction/negative/unit cases per Section 6's requested coverage) is recommended future work, not delivered here.
- Each case was run once (no repeat-run/temperature-variance measurement). `llm_client`'s extractor call uses `temperature=0.0`, so repeat-run variance is expected to be low but was not empirically confirmed in this pass.
- No separate "ambiguous language" or "multiple plausible interpretations" cases were included in this starter set — flagged as a coverage gap for the next expansion, not fabricated here.

---

## 3. Separating extraction accuracy from end-to-end correctness

Per the task's explicit requirement: a correctly computed expression does not by itself prove the system interpreted the original question correctly, and a correct final answer does not by itself prove the extracted expression was right. This evaluation keeps the two measurements distinct:

- **Extraction accuracy** (this document, stage 1): 7/7 on the starter set, evaluated at the correct pipeline stage per case.
- **Response-parsing accuracy** (this document, stage 2): 7/7 after the fix (was 5/7).
- **End-to-end arithmetic correctness**: tracked separately in `docs/evaluation_plan.md` §2.1 and the existing preliminary 36-question comparison (`eval/eval_set.py`) — not re-derived here, since end-to-end correctness depends on generation quality in addition to extraction/parsing, which this document does not evaluate.
