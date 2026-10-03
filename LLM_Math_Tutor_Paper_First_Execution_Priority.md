> **Status annotation — added 2026-10-03, during the `final-development` controller-stabilization and evaluation-framework review.**
> This file was not previously tracked in this repository; it is added here now with its full original content preserved verbatim below. For the current, section-by-section implementation/evaluation status of every requirement in this plan, see **`docs/roadmap_status.md`** — that document is the live, evidence-based status tracker and should be treated as more current than any status implied by the original text below. This header is purely additive; nothing in the original plan text that follows has been edited, reordered, or removed.
>
> Headline status against this plan's own Phases A–I (see `docs/roadmap_status.md` §B for full detail):
> - **Complete**: Phase A (baseline), Phase B (B1–B4: controller integration, progressive disclosure, hint routing, multi-turn state), C1 (attempt recording), C3 (live verification), C4 (answer parser).
> - **Partial (starter-scale evidence)**: C5 (expression-extraction separation), D1–D3/D5/D6, E1–E4/E6.
> - **Not yet evaluated**: C2 (learner adaptation), E5 (conversation resolution) — no dedicated dataset exists for conversation-resolution accuracy yet; this is the most significant gap identified in this review's evaluation-framework work.
> - **Blocked / not started**: Phase G (latency instrumentation — the gap and a concrete proposal are documented, not yet implemented), Phase H (freezing paper evidence — correctly not yet attempted, since the prior evaluation phases are not complete enough to freeze), Phase I (blocked on H).
> - The §15 capstone-deployment track remains entirely untouched, correctly, per this plan's own prioritization.
>
> Criteria for "ready to move toward Phase H" (freezing evidence for the paper), based on this review's findings, in priority order: (1) build and run a labelled conversation-resolution accuracy dataset (E5 — currently the single largest gap with zero existing evidence), (2) expand the retrieval benchmark from the current 29 queries toward the originally-envisioned scale with the same per-query verification rigor used so far, (3) decide and either implement or explicitly defer the conceptual-tutoring design options documented in `docs/conceptual_tutoring_evaluation.md` §5, (4) implement the proposed latency instrumentation and get one real measurement pass. None of these are started as of this annotation.

---

# LLM-Based Math Tutor — Execution Priority & Paper-First Delivery Plan

## 1. Purpose

This document is a **supporting execution plan** for `LLM_Math_Tutor_MVP_to_Final_Capstone_Plan.md`.

The main plan describes the complete journey from MVP to final capstone. This document answers a different question:

> **What should be done first, what can wait, and what is actually required before the research paper can be sent for publication?**

The project has two deliverables built from the same system:

1. **Research paper** — priority is reproducible implementation and evaluation evidence.
2. **Capstone project** — priority includes a polished live application that faculty can access and test.

Because the paper is time-sensitive, development should be **paper-first, deployment-second**, while keeping the architecture clean enough that the final system can later be deployed without a rewrite.

---

# 2. Strategic Decision

## Recommended strategy

Do **not** make cloud deployment the critical path for the paper.

The research system can be evaluated locally as long as the repository provides:

- a reproducible environment,
- configuration instructions,
- required datasets/resources,
- evaluation scripts,
- recorded experiment configuration,
- raw/structured results,
- a fixed Git commit corresponding to the reported results.

The live deployment is primarily a **capstone demonstration layer**.

### Therefore

```text
                 ONE FINAL SYSTEM
                       │
          ┌────────────┴────────────┐
          │                         │
          ▼                         ▼
   RESEARCH TRACK              CAPSTONE TRACK
          │                         │
          ▼                         ▼
 Local/reproducible            Live deployment
 evaluation                    Login/signup
          │                     Persistent DB
          ▼                     Public URL
 Paper results                 Faculty demo
```

The two tracks should share the same core tutoring implementation.

---

# 3. Priority Classes

Use the following priority definitions throughout development.

### P0 — Paper blocker

A task is P0 when the paper cannot credibly report the relevant objective/evaluation without it.

Examples:

- controller integration,
- live verification,
- evaluation dataset construction,
- component evaluation,
- end-to-end evaluation,
- reproducibility.

### P1 — Important research/system quality

Needed for a strong paper or technically complete system, but can sometimes follow the core evaluation work.

Examples:

- latency instrumentation,
- failure analysis,
- deeper conversation evaluation,
- code cleanup,
- additional robustness tests.

### P2 — Capstone/deployment enhancement

Useful for panel evaluation but not required to generate the core research evidence.

Examples:

- cloud hosting,
- login/signup,
- production database,
- deployment polish.

### P3 — Future product work

Do not allow these to delay the paper.

Examples:

- production-scale infrastructure,
- advanced authentication,
- extensive observability,
- sophisticated analytics,
- large-scale user study infrastructure.

---

# 4. Immediate Execution Order

The recommended order is:

```text
PHASE A — Stabilise the research system
        ↓
PHASE B — Integrate the actual tutoring architecture
        ↓
PHASE C — Make verification + learner model research-ready
        ↓
PHASE D — Build evaluation datasets
        ↓
PHASE E — Run component evaluations
        ↓
PHASE F — Run full-system evaluation
        ↓
PHASE G — Analyse results + freeze evidence
        ↓
PHASE H — Write/finalise paper
        ↓
PHASE I — Deploy capstone
```

This order intentionally puts deployment after the main research evidence.

---

# 5. Phase A — Stabilise the Research Baseline

## Objective

Create a clean, reproducible starting point before changing the system.

### Tasks

- Work only on `final-development`.
- Keep `main` untouched.
- Record the current baseline commit.
- Preserve the existing 36-question evaluation.
- Record current test status.
- Record current architecture.
- Record known limitations.
- Confirm which paper claims are currently unsupported.

### Deliverables

```text
baseline commit
baseline evaluation JSON
baseline test results
architecture diagram
known-issues list
```

### Exit criterion

A researcher can identify exactly which implementation version produced the current baseline evidence.

---

# 6. Phase B — Fix the Actual Tutoring Architecture

## Objective

Make the implemented architecture match the architecture claimed in the research.

### Priority order

### B1. Controller integration — P0

Connect:

```text
Streamlit
    ↓
Conversation/intent resolution
    ↓
Controller
    ↓
Tutoring policy
    ↓
Pipeline
```

Do not build new tutoring logic until this is integrated.

### B2. Progressive disclosure — P0

Make the controller enforce:

```text
Teach → Diagnose → Hint → Co-solve → Reveal
```

rather than relying primarily on frontend hiding.

### B3. Hint routing — P0

Ensure hints are generated/selected according to controller state.

### B4. Multi-turn state — P0

Ensure the relevant tutoring state persists across turns.

### Exit criterion

A real frontend conversation follows the controller states and produces the expected behaviour.

---

# 7. Phase C — Make Reliability and Learner Modelling Research-Ready

## C1. Attempt recording — P0

Every meaningful attempt should be recorded.

```text
student
question
attempt
correctness
topic
level
timestamp
```

## C2. Learner adaptation — P0/P1

Verify that recorded history can affect the learner model as intended.

## C3. Live verification — P0

Integrate:

```text
question
   ↓
trusted computation
   ↓
LLM response
   ↓
answer extraction
   ↓
verification
```

## C4. Answer parser — P0

Fix ambiguous fallback behaviour.

## C5. Expression extraction separation — P0

Treat these as separate evaluations:

```text
Question → expression
Expression → mathematical answer
Generated response → stated answer
```

### Exit criterion

The system's mathematical reliability path is both integrated and independently testable.

---

# 8. Phase D — Build the Evaluation Assets

Do this **before repeatedly modifying the system based on ad-hoc examples**.

The evaluation sets should be versioned.

## D1. Arithmetic benchmark — P0

Expand beyond the preliminary 36-question test.

Include:

- single-step,
- large-number,
- multi-step,
- distractors,
- fractions,
- remainders,
- varied wording.

Record ground truth explicitly.

## D2. Expression extraction benchmark — P0

Natural-language questions with labelled expected expressions.

Include:

- multi-step operations,
- distractors,
- fractions,
- remainders,
- units,
- wording variations.

## D3. Retrieval benchmark — P0

Each query should have labelled relevant NCERT chunk(s).

## D4. Conversation benchmark — P1

Include:

- standalone,
- follow-up,
- correction,
- confusion,
- fragment,
- conceptual follow-up,
- modified question.

## D5. Controller scenario set — P0

Create deterministic interaction traces covering:

- correct,
- wrong,
- repeated wrong,
- hint,
- second hint,
- give-up,
- reveal,
- new question,
- follow-up.

## D6. End-to-end benchmark — P0

Create complete multi-turn scenarios that exercise multiple components together.

---

# 9. Phase E — Component Evaluations

Run component evaluations before the final full-system experiment.

## E1. Arithmetic correctness — P0

Compare appropriate baseline/system configurations.

Report:

- correct,
- incorrect,
- unverifiable,
- accuracy.

The existing 36-question result should be labelled as **preliminary**, not replaced silently.

## E2. Expression extraction — P0

Measure:

- exact expression accuracy,
- parse success,
- invalid/unsafe expression rate,
- error categories.

## E3. Computation/verifier — P0

Measure:

- exact arithmetic correctness,
- fraction handling,
- remainder handling,
- unsafe-input rejection.

## E4. Retrieval — P0

Measure:

- Recall@1,
- Recall@3,
- Recall@5,
- MRR where appropriate.

If comparing retrieval methods, keep the benchmark and evaluation protocol identical.

## E5. Conversation resolution — P1

Measure:

- resolution accuracy,
- mode/intent accuracy,
- incorrect-context rate.

## E6. Controller — P0

Measure:

- expected state-transition accuracy,
- policy violations,
- premature-answer rate,
- hint-policy compliance.

---

# 10. Phase F — Full-System Evaluation

This is the main research evidence that the components work together.

## F1. End-to-end task evaluation

For each scenario record:

```text
scenario_id
initial question
student turn sequence
expected behaviour
controller state(s)
retrieved context
generated response
trusted answer
stated answer
verification result
pass/fail
```

## F2. Multi-turn tutoring

Evaluate complete interaction traces rather than isolated prompts.

Measure:

- task success,
- mathematical correctness,
- context retention,
- appropriate hinting,
- progressive disclosure,
- correction handling,
- follow-up handling.

## F3. Learner adaptation

Use controlled learner histories and verify expected adaptation.

Do not claim improved real-world learning outcomes unless an actual student study is conducted.

---

# 11. Phase G — Performance, Reliability, and Error Analysis

## G1. Latency — P1

Instrument:

```text
resolver
retrieval
expression extraction
verification
LLM generation
total response
time-to-first-token
```

Report:

- mean,
- median,
- P95,
- number of LLM calls.

## G2. Reliability — P1

Test:

- LLM timeout,
- LLM failure,
- malformed output,
- retrieval failure,
- verifier failure,
- database failure,
- invalid input.

## G3. Error analysis — P0

For every important experiment, categorise failures.

Examples:

```text
retrieval miss
expression extraction error
arithmetic error
answer parsing error
controller error
context-resolution error
LLM generation error
infrastructure error
```

This is important for the discussion section of the paper.

---

# 12. Phase H — Freeze the Paper Evidence

Before writing the final quantitative results, freeze the experimental configuration.

Record:

```text
Git commit
model/provider
model parameters
prompt version
dataset version
retrieval settings
verifier settings
evaluation script version
environment
date
```

Then run the final experiments from that configuration.

## Required outputs

```text
eval/results/
    arithmetic.json
    extraction.json
    retrieval.json
    conversation.json
    controller.json
    latency.json
    end_to_end.json
```

Keep raw outputs as well as summary metrics.

---

# 13. Phase I — Paper Assembly

The paper should be updated only after the final experimental results exist.

## Methodology

Describe:

- final architecture,
- datasets,
- retrieval pipeline,
- controller,
- verification,
- learner model,
- experimental protocol.

## Results

Report only measurements actually obtained.

## Discussion

Discuss:

- successful behaviours,
- failure modes,
- trade-offs,
- latency,
- limitations.

## Claims audit

For every major sentence in the paper, ask:

> What experiment or source supports this statement?

If there is no evidence, either:

1. conduct the required evaluation, or
2. weaken/reframe the claim.

---

# 14. Paper-Ready Definition

The research paper is ready for submission when:

- [ ] Final architecture is implemented.
- [ ] Controller is part of the live execution path.
- [ ] Progressive disclosure is tested.
- [ ] Verification is integrated.
- [ ] Answer parsing is reliable.
- [ ] Learner-state behaviour is testable.
- [ ] Evaluation datasets are versioned.
- [ ] Arithmetic evaluation is complete.
- [ ] Expression extraction evaluation is complete.
- [ ] Retrieval evaluation is complete.
- [ ] Controller evaluation is complete.
- [ ] Full-system evaluation is complete.
- [ ] Latency has been measured or explicitly scoped as future work.
- [ ] Failure/error analysis is complete.
- [ ] Raw experimental results are retained.
- [ ] Final results map directly to the paper tables.
- [ ] Every quantitative claim is traceable to evidence.
- [ ] The paper no longer presents proposed/fictitious experiments as completed work.
- [ ] A clean commit reproduces the reported system/results.
- [ ] Repository setup and evaluation instructions are documented.

---

# 15. Capstone Deployment After Paper Evidence

Once the paper evidence is frozen, deployment becomes a separate engineering track.

## Capstone-only priority

### C1. Authentication

Implement:

- sign-up,
- login,
- logout,
- student identity.

### C2. Persistent production storage

Move from local student persistence to managed PostgreSQL.

### C3. Deployment

Recommended:

```text
GitHub
   ↓
Streamlit Community Cloud
   ↓
Tutor
   ↓
Supabase PostgreSQL
   ↓
LLM provider
```

No complex CI/CD pipeline is required for the capstone.

### C4. Live acceptance test

Demonstrate:

```text
Student A
    ↓
account A
    ↓
history A

Student B
    ↓
account B
    ↓
history B
```

with no state leakage.

### C5. Faculty-facing polish

- Clear landing page.
- Login/signup.
- Clean tutor interface.
- Progress/history.
- Stable public URL.
- Short deployment/demo documentation.

---

# 16. What Not to Do Before the Paper

Do **not** allow these to become blockers:

- Kubernetes.
- Complex CI/CD.
- Microservices.
- Separate frontend/backend deployment.
- Production-scale observability.
- Redis/Celery-style distributed infrastructure.
- Large-scale authentication infrastructure.
- Production load testing.
- Cloud stress testing.
- Advanced analytics dashboards.

These may be appropriate for a future product, but they do not directly create the core research evidence.

---

# 17. Recommended Work Allocation

If time is very limited, use approximately:

| Workstream | Priority before paper |
|---|---|
| Core tutoring architecture | Very high |
| Verification | Very high |
| Evaluation datasets | Very high |
| Component evaluations | Very high |
| Full-system evaluation | Very high |
| Error analysis | Very high |
| Reproducibility | Very high |
| Latency | Medium-high |
| Reliability | Medium |
| Login/signup | Low for paper |
| Production database | Low for paper |
| Cloud deployment | Low for paper |
| UI polish | Low for paper |

---

# 18. Final Combined Timeline

```text
                 CURRENT MVP
                      │
                      ▼
              Baseline freeze
                      │
                      ▼
           Controller integration
                      │
                      ▼
       Progressive disclosure + hints
                      │
                      ▼
        Learner state + verification
                      │
                      ▼
           Evaluation datasets
                      │
          ┌───────────┼────────────┐
          ▼           ▼            ▼
      Arithmetic    RAG       Controller/
      Extraction            Conversation
          │           │            │
          └───────────┼────────────┘
                      ▼
             Full-system eval
                      │
                      ▼
            Latency + failures
                      │
                      ▼
             Error analysis
                      │
                      ▼
          Final reproducible runs
                      │
                      ▼
                PAPER READY
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
     Submit paper           Capstone deployment
                                  │
                                  ▼
                          Login + signup
                                  │
                                  ▼
                             PostgreSQL
                                  │
                                  ▼
                           Streamlit Cloud
                                  │
                                  ▼
                          Faculty live demo
```

---

# 19. Key Principle

The project should be treated as **one system with two delivery surfaces**.

The research paper asks:

> **Does the proposed system work, and can we demonstrate that with reproducible evidence?**

The capstone asks:

> **Can we demonstrate the completed system as a usable application?**

Therefore:

> **Build and evaluate the system first. Deploy it second.**

This avoids spending research-critical time on infrastructure while still producing a strong live capstone demonstration.

---

# 20. Final Priority Rule

When deciding whether to work on a task, ask:

### Question 1

> Does this task enable one of the stated research objectives to be implemented or evaluated?

If **yes → do it before the paper**.

### Question 2

> Does this task generate evidence needed for a paper claim?

If **yes → do it before the paper**.

### Question 3

> Is this primarily needed so a faculty member can open the application and try it?

If **yes → schedule it after the paper-critical work unless it affects the underlying system architecture**.

### Question 4

> Is this mainly production engineering that neither the objectives nor evaluation require?

If **yes → defer it**.

The goal is not to build the most elaborate deployment architecture. The goal is to produce a **technically coherent, experimentally evaluated tutor**, then wrap that same system in a lightweight live deployment for the capstone.
