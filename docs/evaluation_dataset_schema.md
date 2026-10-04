# Evaluation Dataset Schemas

Defines the structure of every file under `eval/datasets/`. All datasets are versioned by filename (`v1_starter.*`) rather than by an internal `version` field, so a breaking schema change should ship as `v2_starter.*` alongside the old file, not an in-place edit.

General rules across all datasets:
- IDs are stable, human-readable, and prefixed by dataset (`ar-`, `ex-`, `rq-`, `ctl-`, `co-`, `mt-`). Never reuse or renumber an ID once published — add new ones.
- Every item has a `provenance` field. Valid values (free text, but should state one of): `manual` (hand-written by a reviewer), `derived from an observed live interaction, de-identified`, `synthetic, written for this review`, or a reference to an existing project dataset/log.
- No item may claim a curriculum citation, chunk ID, or corpus fact that was not independently checked against `data/extracted_json/ncert_chunks.json` or the live retriever/verifier at the time of writing. Items that could not be fully verified are explicitly marked `NEEDS_REVIEW` or `NEEDS_LIVE_VERIFICATION` in their notes field — do not treat these as scored until resolved.
- No student-identifying information. Cases derived from real interactions retain only the message text and de-identified context, never a name, session ID, or timestamp that could re-identify a person.

### Review status (added Phase B)

This project is built by a university capstone team, not by primary-school teachers. Every claim of "review" in this repository must say, specifically, *who* reviewed *what* — a bare `provenance: manual` does not by itself mean the item's pedagogy, age-appropriateness, or curriculum fit has been checked by anyone beyond its author. The `review_status` field (present on datasets added from Phase B onward; older datasets record equivalent information inline in `provenance`/`notes` instead of a dedicated field) uses these distinctions:

- **`programmatically verified (...)`** — a numeric expected answer was independently checked with `scripts.llm.verifier._safe_eval` or a direct `sympy` call at authoring time. This confirms the *arithmetic*, not the *interpretation* of a word problem, the appropriateness of the framing for the stated grade, or the quality of a conceptual explanation.
- **`project-team drafted; not yet independently reviewed`** — written by one member of this project, not yet read or confirmed by a second. Used for items (e.g. the Phase B out-of-scope set) where the judgment required is not reducible to a symbolic check — scope recognition, pedagogical framing, age-appropriateness.
- **A claim of "teacher-reviewed" or "professionally validated" must never appear anywhere in this repository unless an actual primary-school teacher reviewed the specific items in question.** No dataset in this project currently has that review. Where `docs/`/paper text refers to "human evaluation" or "teacher ratings" as a *planned* protocol (see `docs/evaluation_plan.md`), that remains planned, not retroactively satisfied by project-team review.
- Items derived from an observed live interaction (`provenance: derived from an observed live interaction, de-identified`) have their *behavioral observation* verified (the system really did produce the quoted output) but not necessarily their *rubric judgment* (whether that output was good or bad is still the reviewing team member's read, stated as such).

---

## `eval/datasets/arithmetic/v1_starter.jsonl` (JSON Lines, one object per line)

| Field | Type | Required | Meaning |
|---|---|---|---|
| `case_id` | string | yes | Stable ID, `ar-NNN`. |
| `question` | string | yes | The natural-language question as a student would type it. |
| `grade` | int (1-5) | yes | Target grade level. |
| `topic` | string | yes | Short topic tag (e.g. `fraction_addition`, `division_remainder`). |
| `expected_answer` | string or null | yes | The single canonical answer string, or `null` if `verifiable` is `false`. |
| `accepted_equivalents` | list[string] | yes (may be empty) | Other acceptable renderings of the same value (decimal forms, remainder notation, alternate reduced fractions). |
| `trusted_expression` | string or null | yes | The plain arithmetic expression `scripts.llm.verifier._safe_eval` should be able to evaluate, or `null` when not reducible to one expression. |
| `required_assumptions` | list[string] | yes (may be empty) | Any non-obvious interpretive assumption needed to accept the expected answer (e.g. remainder framing). |
| `verifiable` | bool | yes | `false` marks a case that is intentionally NOT reducible to one checkable value (ambiguous, comparison, or out-of-scope for the current verifier) — used to test that the system does not silently fabricate a check for it. |
| `verification_notes` | string | yes | Why the expected answer is correct, and/or why `verifiable` is `false`. |
| `provenance` | string | yes | See general rules above. |

**Validation rules:** `case_id` unique across the file; `expected_answer is None` iff `verifiable is False`; `trusted_expression`, when not null, must parse under `scripts.llm.verifier._safe_eval`.

---

## `eval/datasets/arithmetic/v2_phaseB_extension.jsonl` (JSON Lines)

A separately-versioned **addition** to `arithmetic/v1_starter.jsonl`, not an edit to it — `v1_starter.jsonl`'s exact item count and content are cited by name in `docs/extraction_evaluation.md` and `docs/retrieval_evaluation.md`'s prior results, so it must not change under them. New arithmetic items go in a new file, per the general versioning rule above.

Added in Phase B (see `docs/curriculum_coverage_matrix.md`) to fill the two largest confirmed curriculum gaps found by that matrix: Class 1 addition/subtraction within 9 (zero items previously), and Class 5 Factors & Multiples / decimals (zero items previously, despite confirmed corpus support).

Same fields as `arithmetic/v1_starter.jsonl` above, plus one addition:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `review_status` | string | yes | Distinguishes verification state explicitly (see "Review status" section below). All six Phase B items are `"programmatically verified (sympy); not yet reviewed by a second project-team member"` — their numeric answers were independently checked with `scripts.llm.verifier._safe_eval` or `sympy.gcd`/`sympy.lcm` directly at authoring time, but no second human has read them yet. |

Two items (`ar-018` HCF, `ar-019` LCM) have `trusted_expression: null` with a note in `required_assumptions` explaining why: HCF/LCM are outside `scripts.llm.verifier`'s current arithmetic grammar (`+ - * / ** ( )` only), so they were checked with `sympy.gcd`/`sympy.lcm` directly during authoring, not through the production verifier path. A case like this cannot yet be auto-scored end-to-end by the live system — that would require extending the verifier's grammar, which is out of scope for a dataset-only pass.

**Validation rules:** same as `v1_starter.jsonl`, plus: no `case_id` in this file may collide with one already used in `v1_starter.jsonl` (IDs are never reused once published, even across versioned files for the same dataset); `grade` must be 1-5; `review_status` must be present.

---

## `eval/datasets/out_of_scope/v1_starter.jsonl` (JSON Lines)

Added in Phase B (B4). Deliberately kept in its **own directory**, never merged into `arithmetic/` or `extraction/`, because these items test scope recognition and honest refusal, not in-curriculum mathematical accuracy — mixing the two would silently corrupt an accuracy score with items that are correctly *supposed* to be declined, not solved.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `case_id` | string | yes | `oos-NNN`. A distinct prefix from every in-scope dataset's IDs. |
| `question` | string | yes | The out-of-scope question as a student might ask it. |
| `out_of_scope_topic` | string | yes | The mathematical area beyond Class 1-5 (algebra, calculus, trigonometry, etc.). |
| `out_of_scope_reason` | string | yes | Why this topic doesn't appear in `verified_ncert_class_1_5_topics.md`. |
| `boundary_case` | bool | yes | `true` when the item is deliberately designed to *look* like simple primary content (small numbers, familiar wording) despite requiring an out-of-scope concept — the harder, more realistic test of scope recognition. |
| `boundary_case_note` | string | only when `boundary_case` is true | What specifically makes the item deceptively simple-looking. |
| `expected_behavior` | string | yes | What an honest, scope-aware response should do, at a high level (not a scripted reply). |
| `must_avoid` | list[string] | yes | Specific failure modes this item is designed to catch. |
| `provenance` | string | yes | See general rules above. |
| `review_status` | string | yes | See "Review status" section below. All 12 starter items are `"project-team drafted; not yet independently reviewed"` — they were authored in this pass to seed the category and have not yet had a second reviewer confirm the `expected_behavior`/`must_avoid` judgments. |
| `notes` | string | optional | Any additional caveat. |

**Scoring convention:** never aggregate these items into an in-curriculum accuracy metric. The intended measurement is categorical (did the system recognize the scope limitation and respond honestly, yes/no), not numeric-answer correctness, since most of these questions have no single primary-level answer to check against.

**Validation rules:** `case_id` unique, all prefixed `oos-`; required fields present; the file must live under `eval/datasets/out_of_scope/`, never under `arithmetic/` or `extraction/`; `out_of_scope_topic` must name one of the recognised beyond-curriculum concepts the validator checks for.

**What this starter set is not:** 12 items is a seed, not a comprehensive out-of-scope benchmark. It covers one example each of algebra, quadratics, calculus (three forms), trigonometry, complex numbers, logarithms, matrices, permutations/combinations, vectors, and the factorial/factors wording collision — chosen to include several deliberately deceptive boundary cases, not to exhaustively sample "everything beyond Class 5."

---

## `eval/datasets/extraction/v1_starter.jsonl` (JSON Lines)

Two case *stages* share one file, distinguished by the `stage` field, because they test two different functions:

- `question_to_expression` — tests `scripts.llm.verifier.compute()` / its LLM extractor: natural-language question → arithmetic expression.
- `response_to_answer` — tests `scripts.llm.response_parser.final_number_str()`: a full generated tutor response → the stated final answer.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `case_id` | string | yes | `ex-NNN`. |
| `stage` | string | yes | `question_to_expression` or `response_to_answer`. |
| `input` | string | yes | The question (stage 1) or the full response text (stage 2). |
| `grade` | int | stage 1 only | Grade context for the extractor. |
| `prior_turn` | string | optional | Previous turn's text, for follow-up-resolution cases (stage 1). |
| `expected_expression` | string or null | stage 1 only | Expected extracted expression, or `null` if the question is non-computable. |
| `expected_expression_equivalents` | list[string] | stage 1 only | Other acceptable textual forms of the same expression. |
| `expected_value` | string or null | stage 1 only | The expression's evaluated value, for convenience. |
| `expected_final_answer` | string or null | stage 2 only | The value `final_number_str` should return, or `null` if none should be found. |
| `has_distractor_numbers` | bool | yes | Whether the input contains numeric tokens that must NOT be picked up. |
| `notes` | string | yes | Rationale, and for known-gap cases, a description of the expected (possibly failing) behaviour and why. |
| `provenance` | string | yes | See general rules above. |

**Validation rules:** `case_id` unique; `stage` ∈ {`question_to_expression`, `response_to_answer`}; a `response_to_answer` row must not set the stage-1-only fields and vice versa.

---

## `eval/datasets/retrieval/v1_starter.jsonl` (JSON Lines)

| Field | Type | Required | Meaning |
|---|---|---|---|
| `query_id` | string | yes | `rq-NNN`. |
| `query` | string | yes | The query text as sent to `scripts.retrieval.retrieve_with_metadata`. |
| `grade` | int | yes | Grade used for the grade filter `G(g)`. |
| `category` | string | yes | One of: `single_word_topic`, `short_conceptual`, `specific_conceptual`, `grade_scope_mismatch`, `paraphrase`, `out_of_corpus_topic`, `curriculum_grade_specific`, `numeric_arithmetic_question`. |
| `relevant_chunks` | list[{`grade`, `page`}] | yes (may be empty) | Chunks independently confirmed relevant by reading `data/extracted_json/ncert_chunks.json`, identified by (grade, page) since the corpus has no separate stable chunk ID. Empty list for `grade_scope_mismatch` / `out_of_corpus_topic` categories where no relevant chunk is expected to exist. |
| `expected_subject` | string | yes | Human description of what SHOULD be retrieved. |
| `corpus_coverage_note` | string | yes | How `relevant_chunks` was verified (grep pattern used, manual read, etc.), or a note that coverage was NOT exhaustively checked. |
| `observed_result` | string | yes | What `retrieve_with_metadata` actually returned when run live, with grade/page/text snippet. |
| `observed_hit_at_3` | bool or null | yes | Whether a `relevant_chunks` entry appeared in the top 3, or `null` when not scorable (no relevant set defined). |
| `observed_rank_of_first_relevant` | int or null | yes | 1-indexed rank of the first relevant hit, or `null` if none / not applicable. |
| `ambiguity_notes` | string | yes | Caveats, uncertainty, or `NEEDS_REVIEW` flags. |
| `provenance` | string | yes | See general rules above. |

**Scoring convention:** exclude `grade_scope_mismatch` and `out_of_corpus_topic` categories from Recall@k / MRR aggregates — score them separately as a grade-filter / corpus-coverage correctness check, since "nothing relevant was returned" is the CORRECT outcome for those categories, not a miss.

**Validation rules:** `query_id` unique; every `(grade, page)` pair in `relevant_chunks` must exist in `data/extracted_json/ncert_chunks.json` (checked by the validation script, not just asserted).

---

## `eval/datasets/controller/v1_scenarios.json` (single JSON object)

| Field | Type | Required | Meaning |
|---|---|---|---|
| `schema_version` | string | yes | Top-level only. |
| `notes` | string | yes | Top-level only; states this is a traceability index, not a separate test runner. |
| `scenarios[].scenario_id` | string | yes | `ctl-NNN`. |
| `scenarios[].description` | string | yes | What the scenario covers. |
| `scenarios[].test_reference` | string | yes | Which file/test/manual-log actually exercises this, or `"none (proposed future work)"`. |
| `scenarios[].status` | string | yes | e.g. `"deterministic, passing"`, `"real-LLM smoke test, passing (single run)"`, `"known limitation, not a test"`, `"known gap"`. |
| `scenarios[].evidence_type` | string | yes | One of: pure controller unit test (no LLM), mocked integration test, real provider call, not applicable. |

**Validation rules:** `scenario_id` unique; if `test_reference` is not `"none..."`, the referenced file must exist in the repository.

---

## `eval/datasets/conceptual/v1_starter.jsonl` (JSON Lines)

| Field | Type | Required | Meaning |
|---|---|---|---|
| `case_id` | string | yes | `co-NNN`. |
| `scenario` | string | yes | Short scenario tag. |
| `prior_context` | list[string] | yes (may be empty) | Prior tutor/student turns needed to interpret `student_input`. |
| `student_input` | string | yes | The turn under evaluation. |
| `student_likely_understanding` | string | yes | Reviewer's reading of what the student does/doesn't understand. |
| `mathematically_correct_or_incorrect` | string | yes | `"Correct"`, `"Incorrect"`, `"Incomplete/ambiguous"`, or `"not_applicable"`. |
| `what_tutor_response_should_accomplish` | string | yes | The goal of an ideal response. |
| `disposition` | string | yes | One of: `acknowledge_and_clarify`, `acknowledge_and_confirm`, `scaffold_toward_specific_question`, `confirm_and_extend`, `correct_specifically`, `clarify_ambiguous_form`, `start_new_episode`. |
| `essential_elements` | list[string] | yes | What a response MUST do to be acceptable. |
| `must_avoid` | list[string] | yes | What a response must NOT do. |
| `rubric_dimensions_most_relevant` | list[string] | yes | Subset of the rubric dimensions defined in `docs/evaluation_plan.md` §Conceptual rubric. |
| `observed_system_behaviour` | string | yes | What the live system actually did, if run; or a note that it has not yet been run (`NEEDS_LIVE_VERIFICATION`). |
| `provenance` | string | yes | See general rules above. |

**Validation rules:** `case_id` unique; every value in `rubric_dimensions_most_relevant` must be a name defined in the rubric table in `docs/evaluation_plan.md`.

---

## `eval/datasets/multi_turn/v1_starter.json` (single JSON object)

| Field | Type | Required | Meaning |
|---|---|---|---|
| `schema_version` | string | yes | Top-level only. |
| `conversations[].conversation_id` | string | yes | `mt-NNN`. |
| `conversations[].title` | string | yes | Short descriptive title. |
| `conversations[].grade` | int | yes | Grade context. |
| `conversations[].topic` | string | yes | Topic tag. |
| `conversations[].reference_answer` | string or null | yes | Trusted final answer, or `null` for conceptual conversations. |
| `conversations[].turns[].turn` | int | yes | 1-indexed turn number. |
| `conversations[].turns[].student` | string | yes | Student's message for that turn. |
| `conversations[].turns[].expected_controller_action` | string | yes | Expected mode/outcome, in plain text. |
| `conversations[].turns[].expected_disclosure` | string | yes | What should/should not be revealed at this turn. |
| `conversations[].turns[].known_issue` | string | optional | Flags a turn known to currently misbehave, with a cross-reference to the relevant controller/conceptual/retrieval case. |
| `conversations[].evaluation_rubric` | list[string] | yes | Rubric dimensions most relevant to this whole conversation. |
| `conversations[].known_ambiguity` | string | yes | Caveats about this conversation as a test case. |
| `conversations[].status` | string | yes | Evidence class (deterministic / live-smoke-tested / observed / synthetic). |
| `conversations[].provenance` | string | yes | See general rules above. |

**Validation rules:** `conversation_id` unique; `turns[].turn` strictly increasing from 1 within a conversation.

---

## Validation

`eval/validate_datasets.py` checks the structural rules above (uniqueness, required fields, cross-references into the corpus and into `docs/evaluation_plan.md`'s rubric) and is run the same way as the project's other lightweight test scripts:

```bash
python -m eval.validate_datasets
```

It does **not** validate subjective content (whether a relevance label or rubric judgement is "correct") — that is a manual review responsibility, tracked via the `NEEDS_REVIEW` / `NEEDS_LIVE_VERIFICATION` markers in the notes fields.
