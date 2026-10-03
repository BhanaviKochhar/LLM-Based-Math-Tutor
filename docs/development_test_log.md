# Development Test Log

This is a lightweight, chronological record of test runs against the controller-integration stabilization work. It is a development checkpoint log, **not** the final research-paper evaluation record (that will live under `eval/results/` once real evaluation runs are executed against a frozen configuration, per `LLM_Math_Tutor_Paper_First_Execution_Priority.md` Phase H).

Each entry states explicitly whether results are **deterministic**, **mocked**, **real-LLM (single run)**, or **manual observation** — these are not interchangeable evidence classes.

---

## Entry: 2026-10-03 — Controller stabilization checkpoint

- **Branch:** `final-development`
- **Base commit at time of testing:** `696af96` (working tree had uncommitted changes; see "Working-tree status" below — this entry is **not** a test of a committed snapshot)
- **Working-tree status at test time:** modified `frontend/app.py`, `scripts/llm/controller.py`, `scripts/llm/pipeline.py`, `scripts/llm/verifier.py`, `scripts/llm/test_pipeline.py`; new `frontend/test_app.py` and the `eval/datasets/*` / `docs/*` files introduced by this same checkpoint.
- **Environment:** Windows, Python (see `requirements.txt`), Groq + HF-router credentials present in `.env` (confirmed `GROQ_API_KEY` and `HF_TOKEN` set, values not inspected/logged).

### Deterministic unit tests

| Command | Result | Notes |
|---|---|---|
| `python -m scripts.llm.test_pipeline` | **38 passed, 0 failed** (exit 0) | Previously reported as 37 passed / 1 failed (`hint level-2 guidance present`). Investigated and fixed — see "Investigation: pipeline test failure" below. |
| `python -m eval.controller_walk` | **27 passed, 0 failed** (exit 0) | Unchanged across this entire checkpoint; controller.py's only change (reworded `_d_ack_conceptual` directive text) does not affect any assertion here. |
| `python -m frontend.test_app` | **34 passed, 0 failed** (exit 0) | New suite added in this checkpoint. Fully mocked/offline — no network calls. Covers: generation-failure rollback (3 tests), practice-problem shortcut removal (2), attempt-recording semantics (7), public API wrappers (5), post-check verification paths (5), and a deterministic diagnostic reproducing the conceptual-episode root cause (4). |

All three suites were re-run together, in sequence, against the same uncommitted working tree, immediately before the commit described in this checkpoint (see "Git checkpoint" in the final report). `data/students.json` was confirmed unmodified (`git status --short data/students.json` empty) after this full run.

### Investigation: pipeline test failure (`hint level-2 guidance present`)

**Reproduced:** yes, in the working tree prior to the fix, with `python -m scripts.llm.test_pipeline` exiting 1.

**Root cause, confirmed by direct inspection:**
- The failing assertion (`scripts/llm/test_pipeline.py`, `test_hints_and_levels`) called `hints.generate_hint("What is 3 x 4?", 3, [...], "beginner", 2, previous_hints=["think groups"], chat_fn=fake_chat)` — hint number 2, with `total_hints` left at its default of 3.
- `hints._guidance_for(hint_number=2, total_hints=3)` correctly routes to `_GUIDANCE_MIDDLE` (hint_number is neither 1 nor >= total_hints).
- `_GUIDANCE_MIDDLE`'s actual text is *"Continue naturally from the earlier hints, moving the child one real step closer to solving it — a concrete number or partial setup from the problem..."* — it does **not** contain the substring `"first concrete step"`.
- That phrase exists only in `_GUIDANCE_SINGLE` (`"...names the key idea AND the first concrete step..."`), which is used only when a problem has exactly one hint total (`total_hints <= 1`) — not the case being tested.
- Directly printed the actual generated user message (`build_hint_messages(...)`) to confirm this is not a formatting artifact: the guidance text is verbatim `_GUIDANCE_MIDDLE`, with no occurrence of "first concrete step" anywhere in the message.

**Conclusion:** this is an outdated test assertion, not a functional defect. `hints.py`'s step-scaled guidance (`_guidance_for`, with `_GUIDANCE_FIRST`/`_MIDDLE`/`_LAST`/`_SINGLE`) is working exactly as designed; the test was checking for wording that belongs to a different guidance tier than the one the test's own inputs actually exercise. Neither `hints.py` nor `test_pipeline.py` were touched by the controller-integration stabilization work (confirmed via `git diff --name-only` before this investigation began), so this predates that work entirely — it is not a regression introduced by the stabilization pass.

**Fix applied:** changed the assertion to check for `"one real step closer"`, a phrase unique to `_GUIDANCE_MIDDLE`, with an inline comment explaining why the old assertion was wrong. This is a one-line, scope-appropriate correction (a test-wording fix, not a behavioural change) and is within the stabilization task's explicit permission to correct outdated assertions. Re-ran the suite after the fix: 38/38, exit 0.

### Real-LLM smoke tests

Run against the live Groq provider with the final, test-pipeline-fixed working tree. Each scenario is a **single run**, not a statistical sample — reported as what was observed, not as evidence of overall tutoring reliability.

| # | Scenario | Input sequence | Observed controller transitions | Final outcome | Verified? | Coherent? | Notes |
|---|---|---|---|---|---|---|---|
| 1 | Correct on first attempt | "What is 6 times 9?" → "54" | teach_invite → diagnose_correct | solved, terminal | n/a (no injected answer in diagnose_correct turn) | yes | — |
| 2 | Wrong → hint → correct | "What is 8 times 7?" → "54" → "Give me a hint" (forced HINT) → "56" | teach_invite → diagnose_wrong → hint → diagnose_correct | solved, terminal | n/a | yes | hint did not state the final number |
| 3 | Cold-solve → reveal | "What is 2/3 + 1/6?" → "just show me" (forced SOLVE) → "just show me" (forced SOLVE) | teach_invite → redirect → reveal | shown, terminal | **yes** — `match: True, computed: '5/6', model_value: '5/6'` | yes | real post-check agreement |
| 4 | Give-up → co-solve | "What is 17 plus 9?" → "i dont know" | teach_invite → co_solve | gave_up, terminal | **yes** — `match: True, computed: '26'` | yes | — |
| 5 | New question mid-episode | "What is 4 times 4?" → "what is 10 minus 3" | teach_invite → (episode closed) → teach_invite (new episode) | n/a (new episode still open) | n/a | yes | confirmed `state.question` updated to the new text, old episode discarded |

**Generation-failure-and-recovery:** not tested live — triggering a genuine real-provider outage on demand is not something that can be done safely or deterministically. This is covered instead by the mocked tests in `frontend/test_app.py` (`test_generation_failure_rolls_back_state`, `test_empty_generation_treated_as_failure`, `test_start_episode_does_not_commit_on_failure`), which is the methodologically correct way to test this condition — explicitly **not** claimed as real-LLM evidence.

`data/students.json` was modified by each of these five live runs (real attempt recording) and reverted via `git checkout -- data/students.json` immediately after each run; final `git status --short data/students.json` is empty.

### Manual behavioural observation: the "fractions" conversation (Phase 3)

Reproduced live (not re-derived from memory) against the current code, including after the `_d_ack_conceptual` directive reword made in this checkpoint.

**Confirmed architectural facts** (each independently re-verified, not assumed):
1. `pipeline._resolve_question("fractions", None)` → `mode=NEW`, `resolved_question="fractions"`, `retrieval_query="fractions"`.
2. `pipeline._solve("fractions", 4)` → `(None, False)` — the extractor correctly returns `NONE` for a non-computable topic word; this is correct extractor behaviour, not a bug.
3. `scripts.llm.controller.step(state, "ATTEMPT", turn)` for **any** `turn` text, when `state.is_math=False` and `state.computed_answer=None`, deterministically returns `mode=ack_conceptual, terminal=False, attempts=0` — verified directly against the controller for three different inputs ("3/9", "8/10 means i have 8 of the 10 total pieces.", "I have one mango, cut in 2 pieces. I have both pieces."). This is now a standing regression test: `frontend/test_app.py::test_conceptual_episode_never_advances`.
4. `retrieve_with_metadata("fractions", 4)` returns grade-3 chunks from a multiplication table (page 141) and a division worksheet (page 181) — neither topically about fractions. By contrast, `retrieve_with_metadata("what is a fraction of a whole", 4)` returns three chunks from pages 101/102/107, independently confirmed (by a direct corpus grep for `numerator|denominator|equal parts|one-half|one-third|one-fourth|quarter of`) to be the actual NCERT Class 4 "Jugs and Mugs" fractions chapter. Full query-by-query results are recorded in `eval/datasets/retrieval/v1_starter.jsonl` (cases rq-001 through rq-010).

**A/B comparison of the `_d_ack_conceptual` directive wording** (reran the identical 3-turn conversation — "fractions" → "3/9" → the mango explanation — with the original directive text restored via monkeypatch, then with the reworded directive):

- **Original wording:** the tutor's reply to the mango explanation ignored it entirely and introduced a brand-new, unrelated practice example ("8 mangoes shared among 4 friends").
- **Reworded wording:** the tutor's reply to "3/9" opened with an acknowledgement phrase ("I see you're thinking about fractions — great!") that the original wording never produced, but its reply to the mango explanation referenced the **wrong prior turn** ("Nice, you've written 'fractions'" — that was the student's turn-1 message, not the current one) before pivoting to unrelated content about simplifying 3/9.

**Conclusion, stated without overclaiming:** the reworded directive produces a measurable, non-regressive change in surface behaviour (acknowledgement phrasing appears where it did not before) but does **not** reliably fix the underlying problem, and in this run exposed a cross-turn confusion that was not clearly present with the original wording (though a single run cannot establish whether that is directive-induced or incidental LLM variance). This is documented as a **partial, unvalidated mitigation**, not a fix. See `eval/datasets/conceptual/v1_starter.jsonl` (cases co-001, co-002) and `docs/evaluation_paper_alignment.md` for the full gap analysis.

### Data integrity confirmation

- `data/students.json`: touched by every live-LLM test above; `git checkout --` applied after each; final status clean.
- No evaluation dataset files existed before this checkpoint created them (`eval/datasets/**` are new, untracked files as of this entry).
- No research-paper source files (`.tex`, `.bib`, PDF) are present anywhere in this repository — confirmed by direct inspection of the repository tree, not assumed. See `docs/evaluation_paper_alignment.md`.
- No credentials, `.env` contents, or raw API keys appear anywhere in this log, the test files, or the dataset files.

### Known limitations carried forward (unchanged by this checkpoint unless noted)

- "Practice problem" shortcut is disabled (no problem-generation capability exists).
- Enter-to-submit does not currently submit in the Streamlit ask-bar (only the ↑ button does); pre-existing, not a regression, not fixed in this checkpoint.
- `STUDENT_ID = "session_user"` remains a single-user MVP identity.
- Conceptual-topic episodes (no computable trusted answer) cannot reliably progress through answer-based diagnosis — confirmed as a deterministic controller property (`ctl-012`), not a frontend bug.
- Broad/short topic queries can retrieve irrelevant RAG chunks — confirmed empirically (`eval/datasets/retrieval/v1_starter.jsonl`), query-specificity-dependent rather than a wholesale retriever defect.
- The `_d_ack_conceptual` directive reword is a partial, unvalidated mitigation for repetition/non-recognition — see A/B comparison above.
- **New in this checkpoint:** `scripts/llm/*`'s per-stage LLM calls (conversation resolution, expression extraction, intent classification) are not logged via `common.log_run` — only the two final-generation call sites (`tutor-pipeline`, `tutor-turn`) are. `data/llm_runs.jsonl` (331 entries, 2026-07-20 to 2026-10-03) therefore cannot currently support true per-stage latency analysis, and additionally mixes multiple model-pilot architectures (`gpt-oss-120b`, `llama3.3-70b`, `qwen3-32b` alongside `tutor-pipeline`/`tutor-turn`) across a long time span — any latency analysis must filter by `model` and by date/commit before drawing conclusions. See `docs/evaluation_plan.md` §Latency for the proposed (not yet implemented) instrumentation.

---

## Entry: 2026-10-03 — Full-repository audit, parser fix, and evaluation expansion (same day, later session)

Continuation of the entry above, in the same calendar day but a distinct working session. Branch: `final-development`. Starting point: the two commits from the prior entry (`d097af4`, `f596239`), confirmed via `git fetch` + `git rev-list --left-right --count origin/final-development...final-development` → `0 0` (local and remote already in sync at session start — see this session's closing report for discussion of how that push occurred, since this assistant did not run `git push` in the prior session).

### Test reconciliation (independently re-run, not trusted from the prior entry)

| Suite | Result at session start | Result after this session's fixes |
|---|---|---|
| `python -m scripts.llm.test_pipeline` | 38/38 | **60/60** (+19 parser-fallback-tier regression tests, +3 atomic-save regression tests) |
| `python -m eval.controller_walk` | 27/27 | 27/27 (unchanged) |
| `python -m frontend.test_app` | 34/34 | 34/34 (unchanged) |
| `python -m eval.validate_datasets` | 23/23 | 23/23 (unchanged; dataset grew from 90 to 123 total lines across files, still validates) |
| **Aggregate** | 122/122 | **144/144, 0 failed** |

`data/students.json` confirmed untouched (`git status --short data/students.json` empty) after every test run and every live-LLM smoke test in this session, each reverted via `git checkout --` immediately after.

### Priority fix: `response_parser.final_number_str` (Section 5)

Root-caused, fixed, and regression-tested — see `docs/extraction_evaluation.md` for the full writeup. Summary: the old fallback (first number in the whole text) returned "3" instead of "12" for a realistic multi-sentence explanation with no `Answer:` line. A naive "last number instead" fix was explicitly rejected (not implemented) because this tutor's own prompts append follow-up suggestions after the answer (e.g. "...equals 54. Would you like to try 8 x 7 next?"), which a last-number heuristic would misread. Implemented instead: a 3-tier confidence fallback (explicit Answer line → last `=`/`equals` statement → sole number by elimination → ambiguous/None). 7/7 on the extraction dataset (was 5/7), 19 new regression tests covering explicit/prose/multi-equation/fraction/negative/contradictory/malformed/irrelevant-number cases.

**Process note, reported transparently**: the new test function was initially written but not added to `test_pipeline.py::main()`'s call list, so it silently never ran despite the suite reporting "0 failed." Caught by explicitly grepping for the function name in `main()` before trusting the pass count, not by the test run itself. Fixed immediately.

### Second low-risk fix: `student_tracker._save` atomic write

Found during the persistence/privacy review (Section 11): `_save()` wrote directly to `data/students.json` with no atomicity — a crash mid-write could corrupt the file. Fixed with a write-to-temp-file-then-`os.replace()` pattern (atomic on both POSIX and Windows). This does **not** fix concurrent-writer lost-updates (two processes racing a read-modify-write cycle can still overwrite each other's change) — that would need real locking or a move off flat-file JSON, explicitly out of scope and documented as such. One regression test added (`test_student_tracker_atomic_save`, uses a temp path, never touches the real store).

### Extraction evaluation (Section 6) — run live for the first time

`question_to_expression` stage: 6/7 correct standalone; the 1 "failure" (`ex-007`) is a follow-up-resolution case that needs `pipeline.resolve_conversation()` run before `pipeline.compute_trusted_answer()` — re-scored at the correct pipeline stage, it is also correct (38/7, matching expected). **7/7 when each case is evaluated at its intended stage.** Full writeup: `docs/extraction_evaluation.md`.

### Retrieval benchmark expansion (Section 7)

Expanded from 10 to 29 queries (target of ≥50 not reached — reason stated explicitly in `docs/retrieval_evaluation.md`, not padded). Added 9 new topics beyond fractions (multiplication, subtraction/borrowing, shapes, money, time, perimeter, number patterns/parity, place value, measurement/weight, division, number sequence, data handling). Key finding: the earlier fraction-focused 8-query sample's Recall@3=0.625 was **not representative** — the expanded, topic-diverse 24-27-query sample shows Recall@3=0.778–0.875, and the "fractions" bare-word weakness does not generalize to other bare topic words (shapes/money/time/division all retrieve well). Full writeup, including root-cause investigation and newly-found issues (a recurring noise-attractor chunk, a paraphrase-without-keyword miss, a chapter-confusion miss, a curriculum-terminology mismatch): `docs/retrieval_evaluation.md`.

### Conceptual tutoring evaluation (Section 8)

Formal rubric applied to the real "fractions" transcripts; architecture traced component-by-component against the explicit list in the task (resolver, trusted-answer computation, controller diagnosis, prompt construction, retrieval, context assembly, generation, verification/disclosure, tracking). Confirmed: `verifier._close` already treats 3/9 and 1/3 as equal (deterministic check, no LLM) — the actual gap is that a conceptual episode's `controller.diagnose()` never reaches that equality check at all, a more precise statement than "the system can't handle equivalent fractions." Three design options for a structural fix documented (none implemented) with risks/compatibility/required-tests for each; explicit recommendation not to proceed with the two higher-risk options without sign-off. Full writeup: `docs/conceptual_tutoring_evaluation.md`.

### Latency (Section 10)

Real figures computed from `data/llm_runs.jsonl`, filtered to the 314 entries from the actual production call sites (excluding the 17 model-pilot comparison entries): median 1.258s, P90 2.207s, P95 3.273s, 99.0% success rate. Cross-checked against the paper's own reported pilot figures (median 1.28s, one 31.7s outlier) as last seen in conversation — closely consistent, a reassuring independent cross-check, not a formal reproduction. Per-stage latency remains unmeasured; instrumentation gap and a concrete, not-yet-implemented proposal documented in `docs/latency_reliability_evaluation.md`.

### Live smoke tests, this session (real Groq calls)

Two gaps in scenario coverage closed: an ambiguous follow-up ("I dont understand" mid-episode, classified as HINT by the live intent classifier) and repeated hint escalation (3 consecutive hints on one problem, each building on the last without repeating or stating the final answer — one hint showed a minor LLM-generated sentence-repetition glitch, noted as a generation-quality observation, not a system defect).

### Documentation added/updated this session

`docs/current_state_audit.md`, `docs/roadmap_status.md`, `docs/stabilization_audit.md`, `docs/extraction_evaluation.md`, `docs/retrieval_evaluation.md`, `docs/conceptual_tutoring_evaluation.md`, `docs/latency_reliability_evaluation.md` (all new); `docs/evaluation_paper_alignment.md` (addendum appended); `LLM_Math_Tutor_MVP_to_Final_Capstone_Plan.md` and `LLM_Math_Tutor_Paper_First_Execution_Priority.md` (added to the repository for the first time, full original content preserved verbatim, with an additive status-annotation header pointing to `docs/roadmap_status.md`).

### Known limitations, updated

All limitations carried forward from the prior entry remain accurate **except**: the `response_parser` fallback defect is now fixed (removed from the list); the latency instrumentation gap now has real top-level figures alongside the still-missing per-stage breakdown; the conceptual-episode non-progression root cause is now more precisely stated (controller never reaches the equality check, rather than "can't handle equivalent fractions"). A new, low-risk fix (student-tracker atomic write) was added and is not a limitation going forward.
