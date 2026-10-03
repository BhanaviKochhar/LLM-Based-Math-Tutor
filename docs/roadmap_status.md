# Roadmap Status — Crosswalk Against the Original Plans

**Source availability:** both original planning documents — `LLM_Math_Tutor_MVP_to_Final_Capstone_Plan.md` and `LLM_Math_Tutor_Paper_First_Execution_Priority.md` — were supplied in full earlier in this conversation and their actual content (not a summary or reconstruction) is used below. Neither file is currently tracked in the `final-development` repository; this document is the authoritative current mapping until/unless those files are added to the repo itself.

Status definitions (as specified for this review):
- **Complete** — implemented and verified against its intended outcome.
- **Implemented, not evaluated** — functionality exists, performance not adequately measured.
- **Partial** — some functionality exists, important behaviour incomplete.
- **Planned** — documented but not yet implemented.
- **Blocked** — requires a missing source, decision, dependency, or capability.
- **Not applicable** — no longer relevant, with explanation.

---

## A. `LLM_Math_Tutor_MVP_to_Final_Capstone_Plan.md`

### §3 — Problems identified in the original audit

| Requirement | Current location | Evidence | Status |
|---|---|---|---|
| 3.1 Controller must be the live tutoring path | `frontend/app.py` (`start_episode`/`advance_episode`/`_apply_action`) | `controller.step()`/`controller.start()` called on every turn; 27 deterministic controller tests + live smoke tests in `docs/development_test_log.md` | **Complete** |
| 3.2 Progressive disclosure must be controller-owned, not frontend-hidden | `frontend/app.py::render_turn` renders strictly by `action.mode`; `pipeline.generate_turn`'s `reveal_modes` gate injection | Verified by code read + `_post_check` only running for `CO_SOLVE`/`REVEAL` | **Complete** |
| 3.3 Student tracking must record every meaningful attempt | `frontend/app.py::_record_outcome` | Fixed this engagement: every `DIAGNOSE_WRONG` now recorded, not just terminal outcomes; `frontend/test_app.py::test_attempt_recording_semantics` | **Complete** |
| 3.4 Replace shared `session_user` identity with per-student identity | `frontend/app.py:19` | `STUDENT_ID = "session_user"` unchanged | **Planned** — explicitly P2/capstone-track per the Execution Priority doc; no multi-user auth/identity work has started |
| 3.5 Move persistence off `students.json` to managed storage | `scripts/llm/student_tracker.py` | File-backed store unchanged | **Planned** — same P2 deferral |
| 3.6 Integrate final verification into the live path | `frontend/app.py::_post_check` | Real `verifier.check()` call on every `CO_SOLVE`/`REVEAL` turn; live-observed agreement in 2 smoke-test scenarios | **Complete** |
| 3.7 Separate expression extraction / computation / generated-answer correctness | `eval/datasets/extraction/v1_starter.jsonl`, `docs/extraction_evaluation.md` | 7/7 extraction cases (live), 7/7 response-parsing cases (deterministic), evaluated as distinct stages | **Partial** — the distinction is now implemented and evaluated at starter scale (n=7 each); not yet at the dataset size the plan's own Phase 4 Evaluation A/B/C sections describe |
| 3.8 Fix fragile answer-parsing fallback | `scripts/llm/response_parser.py::final_number_str` | Fixed this session; confidence-tiered fallback; 19 new regression tests; 7/7 on the extraction `response_to_answer` cases (was 5/7) | **Complete** |
| 3.9 Instrument and reduce excessive LLM calls | — | Not measured: per-stage call count is known qualitatively (up to 3 calls/turn: resolver, extractor, generator) but not logged/counted systematically | **Blocked** — requires the instrumentation proposed in `docs/latency_reliability_evaluation.md`, not yet implemented |
| 3.10 Build a labelled retrieval benchmark, measure independently of generation | `eval/datasets/retrieval/v1_starter.jsonl`, `docs/retrieval_evaluation.md` | 10 queries (8 scorable), real corpus-verified relevance labels, Recall@3=5/8 on this small sample | **Partial** — real evidence exists but at starter scale (n=8), not the ≥50-query benchmark Section 7 of the current task calls for (see `docs/retrieval_evaluation.md` for why that wasn't reached this pass) |
| 3.11 Separate frontend responsibilities (state/rendering/interaction) | `frontend/app.py` | Unchanged — still one file | **Planned** — deliberately deferred; the task's own instruction says not to refactor unrelated modules without evidence of a defect, and no functional defect was found here |
| 3.12 Error handling must not hide backend failures | `frontend/app.py::submit_turn` | Fixed this engagement: `logger.exception` + distinguishable message | **Complete** |
| 3.13 Define logging privacy/retention policy | — | Reviewed, not implemented: see the persistence/privacy findings below | **Planned** |

### §5 Development Roadmap — Phase-by-phase

| Phase | Current status | Evidence |
|---|---|---|
| Phase 0 — Baseline freeze | **Complete** | Baseline commit identified across sessions; architecture documented in `docs/current_state_audit.md` |
| Phase 1 — Controller integration | **Complete** | See §3.1 row above |
| Phase 2 — Learner model / multi-student state | **Partial** | Attempt-recording correctness fixed (§3.3); per-student identity/isolation not started (§3.4) |
| Phase 3 — Login and sign-up | **Not applicable (deferred by design)** | Explicitly P2/capstone-track per the Execution Priority doc's own prioritization; not evidence this session should produce |
| Phase 4 — Verification and answer reliability | **Partial** | Live integration done (§3.6), parser fixed (§3.8); the plan's Evaluation A/B/C each call for a full labelled dataset — only starter-scale evidence exists so far (`docs/extraction_evaluation.md`) |
| Phase 5 — RAG evaluation | **Partial** | See §3.10 row; real diagnostic evidence, not the full benchmark |
| Phase 6 — Conversation resolution evaluation | **Planned** | `conversation_resolver.py` works correctly in every live smoke test run (follow-up resolution, mode routing), but no labelled accuracy dataset (standalone/follow-up/correction/confusion categories) has been built or scored — this is a genuine gap, distinct from the retrieval and extraction datasets that do exist |
| Phase 7 — Tutoring policy / controller evaluation | **Complete** | 27 deterministic scenario tests (`eval/controller_walk.py`) + 7 new ones from this engagement (`frontend/test_app.py`); `eval/datasets/controller/v1_scenarios.json` indexes all 25 |
| Phase 8 — End-to-end system evaluation | **Partial** | 6 multi-turn conversations in `eval/datasets/multi_turn/v1_starter.json`, 4 live-smoke-tested; not the balanced, larger test set the plan describes (arithmetic + conceptual + follow-ups + corrections + confusion + hints + repeated mistakes, systematically) |
| Phase 9 — Latency and performance | **Blocked** | Instrumentation gap — see `docs/latency_reliability_evaluation.md` |
| Phase 10 — Reliability and failure evaluation | **Partial** | Generation-failure rollback is tested (mocked); the plan's full failure-mode table (retrieval failure, DB failure, invalid input, session interruption) has not been systematically tested |
| Phase 11 — Live deployment | **Not applicable (deferred by design)** | Explicitly out of scope for the paper-first track |
| Phase 12 — Final system acceptance test | **Not applicable** | Depends on Phase 11 |

---

## B. `LLM_Math_Tutor_Paper_First_Execution_Priority.md`

### Phases A–I

| Phase | Status | Evidence |
|---|---|---|
| Phase A — Stabilize the research baseline | **Complete** | Baseline commit, architecture, known-limitations list all recorded across this engagement (`docs/current_state_audit.md`, `docs/stabilization_audit.md`) |
| Phase B — B1 Controller integration | **Complete** | See §3.1 above |
| Phase B — B2 Progressive disclosure | **Complete** | See §3.2 above |
| Phase B — B3 Hint routing | **Complete** | `pipeline.generate_turn`'s `MODE_HINT` branch calls `get_hint()`; exercised live in smoke tests |
| Phase B — B4 Multi-turn state | **Complete** | `episode["state"]` persists across turns in `chat["episode"]`; `active_turns` passed to every generation call |
| Phase C — C1 Attempt recording | **Complete** | Fixed this engagement, see §3.3 |
| Phase C — C2 Learner adaptation | **Implemented, not evaluated** | `student_tracker.classify()` is deterministic and unit-testable in principle, but no dedicated evaluation (the plan's own Phase 2 "learner-level transition table" exercise) has been run |
| Phase C — C3 Live verification | **Complete** | See §3.6 |
| Phase C — C4 Answer parser | **Complete** | Fixed this session, see §3.8 |
| Phase C — C5 Expression extraction separation | **Partial** | See §3.7 — implemented and evaluated, but at starter scale |
| Phase D — Evaluation datasets (D1–D6) | **Partial, uneven across sub-items** | D1 arithmetic: starter + existing 36q preliminary (**Partial**, not yet "expanded beyond 36 with full coverage"). D2 extraction: **Complete at starter scale** (7/7 evaluated this session). D3 retrieval: **Partial** (10 queries vs. the implied larger scope). D4 conversation benchmark: **Planned** (no dedicated labelled dataset exists — see Phase 6 row above). D5 controller scenarios: **Complete** (25-scenario catalog). D6 end-to-end: **Partial** (6 scenarios vs. a fuller systematic set) |
| Phase E — Component evaluations (E1–E6) | **Partial, uneven** | E1 arithmetic: preliminary evidence exists (36q), labelled **preliminary** per the plan's own instruction, not re-run at scale this session. E2 extraction: **Complete at starter scale**, this session. E3 computation/verifier: **Implemented and tested** (unit level, `test_pipeline.py`'s verifier tests), not a dedicated coverage-rate measurement across many expressions. E4 retrieval: **Partial**, starter scale. E5 conversation resolution: **Planned** (no accuracy dataset). E6 controller: **Complete** |
| Phase F — Full-system evaluation | **Partial** | See Phase 8 row above |
| Phase G — Performance, reliability, error analysis | **Blocked / Planned** | Latency instrumentation gap (G1); reliability failure-mode table not built (G2); error-category analysis not systematic (G3) — see `docs/latency_reliability_evaluation.md` |
| Phase H — Freeze the paper evidence | **Not started** | No frozen experimental configuration + `eval/results/` snapshot exists; this is intentional — the plan itself says to freeze only once the prior phases are more complete, and this session explicitly avoided fabricating `eval/results/` content |
| Phase I — Paper assembly | **Blocked on Phase H** | — |

### §15 Capstone deployment (post-paper-evidence track)

All of C1 (authentication), C2 (persistent production storage), C3 (deployment), C4 (live acceptance test), C5 (faculty-facing polish) remain **Not applicable (deferred by design)** — explicitly P2/capstone-only priority per the plan's own §2 strategic decision ("do not make cloud deployment the critical path for the paper"), and no work in this engagement has touched this track, correctly.

---

## C. Overall project status

The project is in the middle of **Phase D/E** of the paper-first plan: the core architecture integration (Phases A–C of both plans) is now genuinely complete and verified, not merely claimed — this is the single biggest change this engagement and the prior one in this conversation made to the project's actual status. What remains before "paper-ready" (per the Execution Priority doc's own §14 checklist) is almost entirely **evaluation scale**, not missing functionality: the datasets and protocols exist in starter form for arithmetic, extraction, retrieval, and controller behaviour, but conversation-resolution accuracy has no dataset at all yet, and every existing starter dataset is explicitly sized for diagnostic/methodology purposes rather than statistically powered claims. No work in this engagement should be read as closing Phase H (freezing paper evidence) or Phase I (paper assembly) — both remain correctly blocked on the evaluation-scale work above.
