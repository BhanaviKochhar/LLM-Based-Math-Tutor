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
