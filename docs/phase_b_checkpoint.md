# Phase B Checkpoint — Versioned, Curriculum-Aligned Evaluation Datasets

**Date:** 2026-10-04
**Branch:** `final-development`
**Starting HEAD:** `6d7879ceead1ffd85918a0a1ecb9837063ed967e` (Phase A closure)
**Scope executed:** B1 (versioning), B2 (coverage matrix), B3 (annotation/review-status conventions), B4 (out-of-scope dataset), B5 (validator extension), and a modest, targeted B8 dataset expansion. Phase C (scoring runners), baseline reconciliation, live experiments, paper revisions, deployment, and authentication were **not** touched, per the stop condition.

## What was independently re-verified before any change

- Branch `final-development`, HEAD `6d7879c`, working tree clean except the pre-existing untracked `docs/current_state_evaluation.md` — matches the reported checkpoint exactly.
- `main` untouched at `696af96`.
- **Correction to the prior audit's own claim:** `docs/current_state_evaluation.md` stated the extraction dataset had 7 items. Re-counting directly in this pass found **14** (7 `question_to_expression` + 7 `response_to_answer`, `ex-001`..`ex-014`) — the prior count only read the first several lines of the file. Recorded in `docs/curriculum_coverage_matrix.md` rather than silently carried forward.
- `docs/verified_ncert_class_1_5_topics.md` did not yet exist as a repository file (it had only been supplied in conversation). Saved **verbatim**, with no reinterpretation, since this task repeatedly references it as a repo path.

## B1 — Versioned dataset structure

**Finding:** a versioning convention already existed and is documented in `docs/evaluation_dataset_schema.md` line 3 ("versioned by filename... a breaking schema change should ship as `v2_starter.*` alongside the old file, not an in-place edit") — this did not need to be invented. What Phase B added:

- `eval/datasets/arithmetic/v2_phaseB_extension.jsonl` — a **new, separate file**, not an edit to `v1_starter.jsonl`. `v1_starter.jsonl`'s exact content is cited by name in `docs/extraction_evaluation.md` and `docs/retrieval_evaluation.md`'s already-recorded results, so it was left untouched.
- `eval/datasets/out_of_scope/v1_starter.jsonl` — a new dataset category, not a new version of an existing one.
- Extended `docs/evaluation_dataset_schema.md` with schema sections for both new files, and added an explicit **"Review status"** section (see B3) that the schema doc did not previously have as a dedicated section (it existed implicitly via `provenance`).

No existing `v1_starter.*` file's content, IDs, or labels were changed.

## B2 — Curriculum coverage matrix

Created `docs/curriculum_coverage_matrix.md`, mapping all **34** topic cells of the verified taxonomy (7+6+7+7+7 across Classes 1-5) to actual dataset coverage and corpus support, independently checked in this pass (not assumed from any prior document).

**Headline numbers (before this pass's dataset expansion):**
- 13 of 34 topic cells had zero evaluation items of any kind.
- 11 of 34 had only a retrieval query, several of which are tagged to the wrong class/topic relative to what they actually probe (flagged, not corrected in place).
- Only 10 of 34 had at least one graded/computable item.
- Fractions (Class 4) alone accounts for 20+ items across five dataset types — by far the most concentrated single topic in the project, a known artifact of project history, not deliberate weighting.

**Two genuine discrepancies found and reported (not silently resolved):**
1. Keyword search for 3D-shape terms (cube/cylinder/cone/sphere) found **zero** matches at grade 2, where the verified taxonomy places "Shapes & Spatial Geometry," and **30** matches at grade 5. Reported as an open question for a project-team member to resolve by reading the actual grade-2 pages, not as a correction to the verified taxonomy.
2. Keyword search for pictograph/bar-graph terminology found **zero** matches across the entire corpus, all five grades — Class 4 "Data Handling" could not be located by this method at all.

Every "Confirmed" corpus-support claim in the matrix cites the actual keyword match and a page number, checked in this pass; every "Not checked" cell is labeled as such rather than implied absent.

## B3 — Dataset quality and annotation

- Added a **"Review status"** section to `docs/evaluation_dataset_schema.md` explicitly distinguishing `programmatically verified (sympy)` from `project-team drafted; not yet independently reviewed`, and stating plainly that **no dataset in this repository has been reviewed by an actual primary-school teacher** — only by this project's own (university-student) team, and that must never be described otherwise.
- Every new item added in this pass (6 arithmetic extension items, 12 out-of-scope items) carries an explicit `review_status` field honestly stating its verification state — none are marked as reviewed beyond what was actually done.
- The 6 new arithmetic items' numeric answers were independently checked with `scripts.llm.verifier._safe_eval` (4 items) or a direct `sympy.gcd`/`sympy.lcm` call (2 items, `ar-018`/`ar-019`, since HCF/LCM fall outside the production verifier's current arithmetic grammar — recorded as a limitation, not glossed over).
- The 12 out-of-scope items have no numeric answer to check; their `expected_behavior`/`must_avoid` judgments are recorded as `project-team drafted; not yet independently reviewed` — they were authored by this session alone, with no second reviewer yet.

## B4 — Out-of-scope dataset

Created `eval/datasets/out_of_scope/v1_starter.jsonl`, 12 items (`oos-001`..`oos-012`), in its **own directory**, never mixed into `arithmetic/` or `extraction/`. Covers one example each of: algebra (linear and quadratic), differentiation, integration, trigonometry, complex numbers, logarithms, matrices, permutations/combinations, limits, vectors, and factorial notation.

7 of the 12 items are explicitly marked `boundary_case: true` — deliberately deceptive items designed to look like ordinary primary content (small numbers, familiar word-problem framing) despite requiring an out-of-scope concept, including one (`oos-012`) specifically probing whether "factorial" gets confused with the genuinely in-scope Class 5 topic "factors and multiples" by surface wording alone.

This is explicitly documented as a **starter seed, not a comprehensive benchmark** (stated in both the dataset schema doc and the dataset itself).

## B5 — Validator extension

Extended `eval/validate_datasets.py` with two new functions, following the existing one-function-per-file convention (no generic/shared schema was imposed):

- `test_arithmetic_v2_phaseb()` — validates the new arithmetic extension file, including a cross-file check that no `case_id` in it collides with `v1_starter.jsonl` (IDs are never reused).
- `test_out_of_scope()` — validates the new out-of-scope file, including that it lives in its own directory (never under `arithmetic/`/`extraction/`) and that every item's `out_of_scope_topic` names a recognized beyond-curriculum concept.

No existing validation rule was weakened. No existing dataset needed a rule exception.

## B8 — Modest, targeted dataset expansion

Per the task's explicit preference for "breadth, correctness, provenance and balance... over volume," only **6 new items** were added, each targeting a specific, confirmed gap from the coverage matrix:

| ID | Class | Topic | Fills |
|---|---|---|---|
| `ar-016` | 1 | addition | Class 1 had zero subtraction-paired addition coverage |
| `ar-017` | 1 | subtraction | Class 1 "Addition & Subtraction (1 to 9)" had only one addition item, no subtraction |
| `ar-018` | 5 | HCF | Class 5 "Factors & Multiples" — zero items, confirmed corpus support |
| `ar-019` | 5 | LCM | Same topic as `ar-018` |
| `ar-020` | 5 | fraction-to-decimal | Class 5 "Fractions & Decimals" — zero decimal items, confirmed corpus support |
| `ar-021` | 5 | decimal addition | Same topic as `ar-020` |

All six are new items with newly minted IDs (`ar-016`..`ar-021`); none reuse or renumber an existing ID. No item from `v1_starter.jsonl` was altered.

## Tests and validation run

| Command | Result |
|---|---|
| `python -m eval.validate_datasets` | **36 passed, 0 failed** (was 23; +13 from the two new dataset validators) |
| `PYTHONIOENCODING=utf-8 python -m frontend.test_app` | 36 passed, 0 failed (unchanged — Phase B touched no frontend code) |
| `python -m eval.controller_walk` | 33 passed, 0 failed (unchanged) |
| `python -m scripts.llm.test_pipeline` | 79 passed, 0 failed (unchanged) |

Total: **184 passed, 0 failed**. No live-LLM calls were made; no API cost was incurred.

## Git checkpoint

- Diff inspected before staging (`git diff --stat`): only the two intended modified files (`docs/evaluation_dataset_schema.md`, `eval/validate_datasets.py`) plus the new files listed below.
- Confirmed `docs/verified_ncert_class_1_5_topics.md` was saved verbatim from the attached document — no topic, subtopic, or wording was added, removed, or reinterpreted.
- Confirmed `docs/current_state_evaluation.md` remains untracked and was neither modified nor staged.
- No secrets, student data, or generated log artifacts were added — all new files are hand-authored dataset/documentation content.
- Files staged for this phase's commit: `docs/evaluation_dataset_schema.md`, `docs/curriculum_coverage_matrix.md`, `docs/verified_ncert_class_1_5_topics.md`, `docs/phase_b_checkpoint.md`, `eval/datasets/arithmetic/v2_phaseB_extension.jsonl`, `eval/datasets/out_of_scope/v1_starter.jsonl`, `eval/validate_datasets.py`.

## Dataset categories — item counts before/after

| Category | Before | After | Notes |
|---|---|---|---|
| Arithmetic | 15 (`v1_starter`) | 15 + 6 (`v2_phaseB_extension`) = 21 | New file, v1 untouched |
| Extraction | 14 (corrected from a prior miscount of 7) | 14 | Unchanged this phase |
| Retrieval | 29 | 29 | Unchanged this phase |
| Conceptual | 9 | 9 | Unchanged this phase |
| Multi-turn | 6 conversations | 6 | Unchanged this phase |
| Controller scenarios | 25 (unused by any runner) | 25 | Unchanged this phase |
| **Out-of-scope** | **0 (did not exist)** | **12** | New category |

## Unresolved items / human-review requirements

- Two class-placement/corpus discrepancies (Class 2 3D shapes; Class 4 Data Handling, see B2 above) need a project-team member to read the actual source pages — keyword search alone could not resolve them.
- All 18 newly-added items (6 arithmetic + 12 out-of-scope) are marked `review_status`-honest but **not yet reviewed by a second team member** — that review is still outstanding.
- `ar-018`/`ar-019` (HCF/LCM) cannot be auto-scored by the live system today — the production verifier's grammar doesn't cover HCF/LCM. This is a Phase C/implementation question, not resolved here, and is recorded as a `required_assumptions` note in the dataset itself.
- 11 of 34 curriculum topic cells remain entirely uncovered by any dataset item after this pass (down from 13); the full remaining list is in `docs/curriculum_coverage_matrix.md`.
- No scoring runner exists yet for any dataset (Phase C, not started).

## Is Phase B complete?

**Partially complete, by design, matching the task's own stop condition.** B1, B2, B3, B4, and B5 each have a genuine, grounded deliverable in the repository now (versioning convention documented and used correctly; coverage matrix with independently-checked corpus evidence; explicit review-status conventions; a real out-of-scope starter set; an extended validator). The dataset **expansion** itself (B8) was deliberately modest — 6 new arithmetic items against 24 confirmed-or-partial gap cells identified in the matrix — because the task explicitly prioritizes correctness, provenance, and balance over hitting a target count, and because most remaining gaps need either corpus-page confirmation or a second reviewer before more items can be added responsibly.

Phase B is **not** being claimed as "fully complete" in the sense of every category having adequate coverage — 11 topic cells remain untested, and the two corpus discrepancies are open. It is complete in the sense the task defines for a stopping point: "finish the dataset inventory, coverage matrix, versioning/annotation approach and a meaningful initial dataset expansion, then stop."

## Recommended next task

Per the roadmap, the next step would be **Phase C** (build the scoring runners that actually execute `arithmetic/v1_starter.jsonl` + `v2_phaseB_extension.jsonl` and `extraction/v1_starter.jsonl` against the live pipeline and record real metrics) — but that is explicitly out of scope for this task and requires your separate approval to begin, per the stop condition.

A smaller, lower-risk option before Phase C: have a second project-team member read the two flagged corpus-discrepancy pages (Class 2 3D shapes, Class 4 Data Handling) directly, which would let the coverage matrix's two "discrepancy" rows be resolved one way or the other without touching any code.
