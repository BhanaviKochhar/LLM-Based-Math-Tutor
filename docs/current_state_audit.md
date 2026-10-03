# Current State Audit

Snapshot of the `final-development` branch as independently verified in this session (not assumed from prior reports). Commit at time of writing: see `git log -1` — this document describes the state as of commit `f596239` plus the additional work landed in this same engagement (parser fix, new evaluation docs) prior to the final commit recorded in the session's closing report.

## Git state (verified)

- Branch: `final-development`.
- Remote tracking: `origin/final-development`, confirmed via `git fetch` + `git rev-list --left-right --count origin/final-development...final-development` → `0 0` (local and remote identical) at the start of this session.
- `main`: confirmed identical to `origin/main`, both at `696af96`, untouched by any work in this or the prior engagement.
- Working tree: clean at session start; this session added a parser fix (`scripts/llm/response_parser.py`, `scripts/llm/test_pipeline.py`) and several new `docs/*` files (committed separately — see the session's closing report for exact SHAs).

## Architecture and execution flow (verified by reading the current code, not inferred)

```
Streamlit UI (frontend/app.py)
    -> submit_turn()
        -> advance_episode() / start_episode()
            -> pipeline.resolve_conversation()   [conversation_resolver.py, LLM call for ambiguous cases]
            -> scripts.retrieval.retrieve_with_metadata()   [BM25 + dense + RRF, grade-filtered]
            -> pipeline.compute_trusted_answer()   [verifier.solve -> compute -> LLM extractor + SymPy]
            -> controller.start() / controller.step()   [pure state machine, no LLM]
            -> pipeline.generate_turn()
                -> prompt_registry.build_messages()
                -> llm_client.stream()   [Groq primary, HF-router fallback]
            -> _post_check()   [verifier.check(), real post-generation verification]
            -> _record_outcome()   [student_tracker.record(), gated on controller mode/outcome]
    -> render_turn()   [controller mode-driven rendering, shortcut buttons = controller.Action.buttons]
```

This is the result of the controller-integration work completed across this and the prior engagement in this conversation: the controller (`scripts/llm/controller.py`) is now the live decision-maker for every turn, not a disconnected, offline-tested-only module. Confirmed by reading `frontend/app.py` end to end and by the live smoke tests in `docs/development_test_log.md`.

## Main implementation components (verified present and current)

| Component | File | Verified role |
|---|---|---|
| Frontend / orchestration | `frontend/app.py` | Streamlit UI + controller-driven episode orchestration (`start_episode`, `advance_episode`, `submit_turn`, `_apply_action`, `_record_outcome`, `_post_check`) |
| Tutoring state machine | `scripts/llm/controller.py` | Pure, no-LLM state machine: `TEACH_INVITE -> DIAGNOSE_WRONG/CORRECT -> HINT -> CO_SOLVE -> REVEAL`, level-tuned thresholds |
| Conversation resolver | `scripts/llm/conversation_resolver.py` | Classifies NEW / MATH_FOLLOWUP / CONCEPT_FOLLOWUP / CONFUSION / CORRECTION / FRAGMENT; one deterministic regex shortcut, otherwise an LLM call |
| Intent classifier | `scripts/llm/intent.py` | ATTEMPT / HINT / SOLVE / GIVE_UP / NEW_QUESTION; deterministic prefilter for bare numbers, LLM for free text, keyword fallback on LLM failure |
| Retrieval | `scripts/retrieval.py` | Hybrid BM25 + dense (ChromaDB, all-MiniLM-L6-v2) with Reciprocal Rank Fusion, grade-windowed (`G(g) = {g, g-1}`) |
| Prompt assembly | `scripts/llm/prompt_registry.py` | Versioned prompts (v1-v5), level-styled, directive-injected, conversation-history-aware |
| Generation / provider | `scripts/llm/llm_client.py` | Groq primary (`openai/gpt-oss-120b`), HF-router fallback, streaming with fallback-before-first-token |
| Expression extraction | `scripts/llm/verifier.py` | `compute()` (LLM extractor + SymPy evaluation, allow-listed syntax), `solve()` (grade-aware injection gate), `check()` (post-generation verification) |
| Response parsing | `scripts/llm/response_parser.py` | **Fixed in this session**: `final_number_str()` now uses a confidence-tiered fallback (Answer line -> last equation -> sole number -> ambiguous) instead of "first number in text" |
| Student tracking | `scripts/llm/student_tracker.py` | Recent-window (last 5 attempts) rule-based level classification; file-backed at `data/students.json` |
| Hints | `scripts/llm/hints.py` | Step-scaled guidance (`_GUIDANCE_FIRST/MIDDLE/LAST/SINGLE`) |

## Test and evaluation infrastructure (verified by running, not trusted from reports)

| Suite | Command | Result (this session) | Nature |
|---|---|---|---|
| Pipeline/parser/verifier/client/hints | `python -m scripts.llm.test_pipeline` | 57/57 (was 38/38 before this session's parser-fix regression tests) | Deterministic, no network |
| Controller state machine | `python -m eval.controller_walk` | 27/27 | Deterministic, no network |
| Frontend orchestration | `python -m frontend.test_app` | 34/34 | Mocked generation, no network |
| Dataset structural validation | `python -m eval.validate_datasets` | 23/23 | Structural only, cross-references real corpus |
| **Aggregate** | — | **141/141, 0 failed** | — |

Evaluation datasets (new in the prior engagement, extended in this one): `eval/datasets/{arithmetic,extraction,retrieval,controller,conceptual,multi_turn}/`. Existing, pre-dating this work: `eval/eval_set.py` (36-question preliminary arithmetic comparison), `eval/run_eval.py`, `eval/controller_walk.py`, `eval/intent_spike.py`.

## Verified stabilization changes (this and prior engagement)

See `docs/stabilization_audit.md` for the full 12-point verification. Summary: controller-commit-on-success rollback, corrected attempt-recording semantics, public API wrappers, distinguishable error handling with logging, the "Practice problem" shortcut disabled (no backing capability exists), and the `response_parser` fallback fix (this session).

## Known issues (confirmed present, not fixed in this audit unless noted)

1. Conceptual (non-computable) episodes cannot progress past `ACK_CONCEPTUAL` — deterministic controller property, confirmed via `frontend/test_app.py::test_conceptual_episode_never_advances` and live reproduction (`docs/development_test_log.md`).
2. Short/bare-topic retrieval queries return irrelevant chunks — confirmed empirically against the real corpus and retriever (`eval/datasets/retrieval/v1_starter.jsonl`); see `docs/retrieval_evaluation.md`.
3. Cross-turn attribution: in one live A/B comparison, a reworded controller directive caused the model to reference the wrong prior turn — single-run observation, not yet systematically characterized.
4. `thread_notes` (cross-episode memory) is implemented in `pipeline.py`/`memory.py` but never populated by the frontend — pre-existing, not a regression.
5. Per-stage LLM call latency (resolver, extractor, intent classifier) is not logged — only the two final-generation call sites are (`common.log_run`). See `docs/latency_reliability_evaluation.md`.
6. `STUDENT_ID = "session_user"` is a shared, hardcoded identity — single-user MVP assumption, not production multi-user persistence.
7. Enter-to-submit does not reliably submit in the Streamlit ask-bar (pre-existing UI quirk, not investigated further in this pass).

## Missing or outdated documentation (as of session start)

- No `docs/` directory existed before the prior engagement in this conversation.
- The two original planning Markdown files (`LLM_Math_Tutor_MVP_to_Final_Capstone_Plan.md`, `LLM_Math_Tutor_Paper_First_Execution_Priority.md`) and the paper source are not tracked in this repository at all — see `docs/roadmap_status.md` and `docs/evaluation_paper_alignment.md` for how this session obtained and used their actual content (supplied directly in conversation, not reconstructed).

## Dependencies and blockers

- `GROQ_API_KEY` and `HF_TOKEN` are present in `.env` (confirmed set, values not read/logged) and required for any live-LLM evaluation (extraction stage-1 cases, live smoke tests, conceptual-tutoring reproduction).
- ChromaDB index (`data/chromadb/`) and the extracted corpus (`data/extracted_json/ncert_chunks.json`, 2,329 chunks) are present and were used directly for retrieval verification in this session.
- No blockers currently prevent running any of the existing or new test/evaluation suites in this environment.
