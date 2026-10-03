> **Status annotation — added 2026-10-03, during the `final-development` controller-stabilization and evaluation-framework review.**
> This file was not previously tracked in this repository; it is added here now with its full original content preserved verbatim below. For the current, section-by-section implementation/evaluation status of every requirement in this plan, see **`docs/roadmap_status.md`** — that document is the live, evidence-based status tracker and should be treated as more current than any status implied by the original text below. This header is purely additive; nothing in the original plan text that follows has been edited, reordered, or removed.
>
> Headline status (see `docs/roadmap_status.md` for full detail, evidence, and per-item citations):
> - **Complete and verified**: controller integration (§3.1, Phase 1), progressive disclosure (§3.2), post-generation verification integration (§3.6), attempt-recording correctness (§3.3), the fragile answer-parser fallback (§3.8), error handling not hiding failures (§3.12).
> - **Partial, starter-scale evidence only**: expression/computation/answer-correctness separation (§3.7, Phase 4), RAG evaluation (§3.10, Phase 5), end-to-end system evaluation (Phase 8).
> - **Planned / not started**: multi-student identity and persistence (§3.4, §3.5, Phase 2-3), conversation-resolution accuracy evaluation (Phase 6), latency instrumentation (§3.9, Phase 9), the broader reliability failure-mode table (Phase 10).
> - **Deliberately deferred, not evaluated or started in this track**: login/sign-up, production database, live deployment, acceptance testing (Phases 3, 11, 12) — out of scope for the paper-first priority this project is currently following (see `LLM_Math_Tutor_Paper_First_Execution_Priority.md`), not overlooked.
>
> Do not read any "Required correction" or "Tasks" list below as still-outstanding without checking `docs/roadmap_status.md` first — several have been completed since this plan was originally written.

---

# LLM-Based Math Tutor — MVP to Final Capstone Development & Evaluation Plan

## 1. Purpose

This document defines the development path from the current MVP to a **final capstone-ready, deployable, multi-student AI mathematics tutor**.

It separates:
- functionality already implemented,
- work still required,
- evaluations that must actually be conducted,
- evidence that should be retained for the final report/paper.

The proposed evaluation strategy in the paper must **not** be treated as existing experimental evidence. The currently available experimental evidence is the preliminary 36-question arithmetic comparison described below.

---

# 2. Current MVP Status

The project already contains:

- Streamlit interactive tutor interface.
- LLM-based response generation.
- NCERT-based retrieval.
- Hybrid BM25 + dense retrieval with Reciprocal Rank Fusion.
- Chroma vector retrieval.
- Conversation resolution for follow-ups, corrections, confusion, and fragments.
- LLM-assisted expression extraction and SymPy-based arithmetic verification.
- Hint generation.
- Student-performance tracking.
- Adaptive level classification.
- A tutoring controller/state-machine implementation.
- Preliminary arithmetic evaluation.
- Unit/subsystem tests for several backend components.

The main issue is not the absence of components. It is the gap between some of those components and the **actual live execution path**, together with missing production-style persistence, authentication, integrated evaluation, and deployment hardening.

---

# 3. Current Problems Identified in the Audit

## 3.1 Controller is not the live tutoring path

The repository contains a controller with states for teaching/invitation, diagnosis, hints, co-solving, revealing answers, cold-solve redirection, giving up, new questions, and attempt thresholds.

However, the live Streamlit path primarily follows:

```text
frontend/app.py
    ↓
ask_tutor()
    ↓
pipeline.prepare()
    ↓
conversation resolver + retrieval + verifier + prompt
    ↓
LLM
    ↓
Streamed response
```

The controller exists separately but is not currently the central path used by the live frontend.

### Required correction

Make the controller authoritative:

```text
Student message
      ↓
Conversation / intent resolution
      ↓
Controller
      ↓
Tutoring state + response policy
      ↓
Retrieval / verifier / LLM
      ↓
Student
```

---

## 3.2 Progressive disclosure is partly presentation-level

The pipeline can compute the answer before generation and make it available to the prompt. The frontend then hides part of the generated response.

That means the current behaviour can hide an already-generated solution rather than guarantee, at the controller/policy level, that the answer is not prematurely generated or revealed.

### Required correction

Use controller-owned disclosure policies:

- `TEACH_INVITE`: no final answer.
- `DIAGNOSE_WRONG`: answer remains private.
- `HINT`: controlled hint only.
- `CO_SOLVE`: guided solution.
- `REVEAL`: trusted answer may be provided.

---

## 3.3 Student tracking is incomplete

The student tracker supports attempts, correctness, weak topics, and recent outcomes, but the frontend does not consistently record every meaningful attempt, particularly incorrect attempts.

### Required correction

Record:

```text
question
attempt
correct / incorrect
topic
difficulty / level
timestamp
```

and use this data for adaptation.

---

## 3.4 Single shared student identity

The MVP uses a shared identity similar to:

```python
STUDENT_ID = "session_user"
```

This is suitable for a single-user prototype but not for a live multi-student tutor.

### Required correction

Implement:

- Login.
- Sign-up.
- Authenticated student identity.
- Independent student state.
- Independent progress/history.
- No cross-student leakage.

---

## 3.5 File-based persistence is not sufficient for deployment

`students.json` is suitable for an MVP/local prototype but is not a robust multi-user persistence layer because of concurrency, persistence, and deployment concerns.

### Required correction

Move persistent student data to managed PostgreSQL, such as Supabase PostgreSQL.

---

## 3.6 Post-generation verification is not fully integrated

A verification/finalization path exists, but the normal frontend path currently uses preparation/streaming without consistently invoking final verification.

Therefore, the existence of a verifier in the repository does not prove that every live generated response is post-generation verified.

### Required correction

Integrate final verification into the live path and record:

- trusted/computed answer,
- extracted answer,
- verification result,
- verification failure/refusal,
- response ID,
- timestamp.

---

## 3.7 Arithmetic verifier depends on expression extraction

The verifier safely evaluates expressions using SymPy, but the natural-language question must first be converted into an expression.

Therefore:

```text
Natural-language interpretation correctness
        ≠
Arithmetic evaluation correctness
```

An incorrect expression can still be mathematically valid.

### Required correction

Evaluate separately:

1. Expression extraction correctness.
2. Arithmetic computation correctness.
3. Generated-answer correctness.

---

## 3.8 Answer parsing fallback is fragile

The parser prioritizes an explicit `Answer:` line but can fall back to the first numerical token in the response.

This can incorrectly extract an intermediate number.

### Required correction

Use a hierarchy:

```text
1. Explicit final Answer field
2. Final equation/result
3. Final numerical statement
4. Ambiguous → unverifiable
```

---

## 3.9 Potentially excessive LLM calls

A single interaction can involve:

- conversation-resolution LLM call,
- expression-extraction LLM call,
- generation LLM call,
- additional generation for hints.

This can increase latency, cost, and rate-limit pressure.

### Required correction

Instrument every component and identify calls that can safely be skipped.

---

## 3.10 RAG architecture is reasonable but insufficiently evaluated

The current retrieval architecture combines lexical and dense retrieval using RRF.

There is not yet a sufficiently developed labelled retrieval benchmark for:

- Recall@1,
- Recall@3,
- Recall@5,
- MRR,
- grade-filtering behaviour.

### Required correction

Build a labelled retrieval evaluation set and measure retrieval independently from generation.

---

## 3.11 Frontend responsibilities are concentrated

`frontend/app.py` contains many responsibilities including UI configuration, state, navigation, backend calls, answer checking, hints, progress, rendering, and fallback handling.

### Required correction

Eventually separate concerns, for example:

```text
frontend/
    app.py
    state.py
    rendering.py
    interaction.py
```

This is lower priority than controller integration.

---

## 3.12 Error handling can hide backend failures

Broad exception handling provides a friendly fallback but can hide technical failures.

### Required correction

Use:

```text
User-facing friendly message
        +
Structured technical error log
        +
Request/session identifier
```

---

## 3.13 Logging requires privacy/retention consideration

LLM logs can contain questions, retrieved chunks, prompts/messages, and outputs.

The final system should define:

- what is logged,
- retention period,
- whether personal information is logged,
- who can access logs.

---

# 4. Existing Preliminary Evaluation

The repository contains a preliminary arithmetic comparison using a **36-question evaluation set**.

Stored result:

| System | Correct | Wrong | No-number | Accuracy |
|---|---:|---:|---:|---:|
| Baseline | 35 | 1 | 0 | 97.2% |
| System | 36 | 0 | 0 | 100% |

The stored baseline error is associated with:

```text
3/4 - 1/4
```

where the baseline produced `1` while the expected result was `1/2`.

This should be described as:

> **Preliminary arithmetic correctness comparison on a 36-question test set.**

It should **not** be presented as evidence that the complete tutor reduces hallucinations, improves pedagogy, improves retrieval, or improves learning outcomes.

---

# 5. Development Roadmap

## Phase 0 — Baseline and Audit Freeze

### Goal

Establish a reproducible baseline before major changes.

### Tasks

- Record current repository state.
- Record architecture.
- Preserve preliminary evaluation.
- Run existing tests where the environment permits.
- Record known limitations.
- Work only on `final-development`; keep `main` untouched.

### Evidence

```text
architecture diagram
existing test results
preliminary evaluation JSON
known-problem list
baseline commit SHA
```

---

## Phase 1 — Integrate the Tutoring Controller

### Goal

Make the controller the actual decision-making layer.

### Tasks

1. Connect Streamlit interaction to the controller.
2. Route each student turn through controller logic.
3. Integrate intent/conversation resolution.
4. Map controller states to response policies.
5. Route hints through the controller.
6. Preserve controller state across relevant turns.
7. Implement transitions for:
   - new question,
   - student attempt,
   - correct response,
   - incorrect response,
   - confusion,
   - hint request,
   - repeated failure,
   - give-up,
   - answer reveal.

### Evaluation

#### Component

Controller state-transition tests:

- correct transition,
- incorrect transition,
- repeated incorrect attempts,
- hint escalation,
- give-up,
- reveal,
- new question,
- cold solve.

#### Integration

Run complete traces such as:

```text
Question
→ student attempt
→ wrong
→ hint
→ second attempt
→ correct
```

and verify that the real frontend follows the expected controller states.

### Evidence

- state-transition table,
- controller test results,
- representative interaction traces,
- controller state diagram.

---

# Phase 2 — Learner Model and Multi-Student State

### Goal

Create independent persistent learner profiles.

### Tasks

1. Record every meaningful attempt.
2. Persist correctness.
3. Persist weak topics.
4. Persist recent performance.
5. Persist adaptive level.
6. Replace shared `session_user`.
7. Introduce student-specific storage.
8. Ensure one student's state cannot be accessed by another.

### Evaluation

Create two or more independent students and verify:

- separate histories,
- separate correctness,
- separate weak topics,
- separate levels,
- no cross-student leakage.

Test learner-level transitions for:

- fewer than 3 attempts,
- low accuracy,
- medium accuracy,
- high accuracy,
- mixed recent performance.

### Evidence

- database schema,
- student-isolation tests,
- example independent profiles,
- learner-level transition table.

---

# Phase 3 — Login and Sign-Up

### Goal

Turn the tutor into a genuine multi-student application.

### Sign-up

```text
Name
Email
Password
Confirm Password
Grade/Class
```

### Login

```text
Email
Password
```

Then:

```text
authenticated user
        ↓
student_id
        ↓
student profile
        ↓
tutor
```

### Security requirements

- Never store plain-text passwords.
- Keep credentials/API keys out of Git.
- Use managed authentication where practical.
- Store only required student information.
- Separate authentication identity from learning data.

### Evaluation

Test:

- valid registration,
- duplicate registration,
- invalid credentials,
- login/logout,
- session persistence,
- account isolation,
- invalid input,
- unauthorized access to another student's data.

### Evidence

Capture:

- login UI,
- signup UI,
- authenticated tutor UI,
- multi-user demonstration,
- authentication test results.

---

# Phase 4 — Verification and Answer Reliability

### Goal

Make mathematical correctness measurable and enforceable.

### Tasks

1. Integrate final verification into the live response path.
2. Improve answer parsing.
3. Separate expression extraction, computation, and generated-response correctness.
4. Keep trusted answers private until disclosure is permitted.
5. Ensure answer disclosure follows controller policy.

### Evaluation A — Expression Extraction

Build a labelled set containing:

- single-step arithmetic,
- multi-step arithmetic,
- fractions,
- remainders,
- distractors,
- varied natural-language wording,
- units,
- implicit operations,
- follow-up questions.

Measure:

```text
Exact Expression Accuracy
Expression Parse Success Rate
Invalid/Unsafe Expression Rate
```

### Evaluation B — Arithmetic Computation

Test the computation layer independently with known expressions.

Measure:

```text
Exact correctness
Failure rate
Unsafe-input rejection
Fraction handling
Remainder handling
```

### Evaluation C — Generated Answer

Compare generated final answers with trusted ground truth.

Measure:

```text
Correct
Incorrect
Unverifiable
```

### Evidence

- aggregate metrics,
- error categories,
- example failures,
- verifier logs,
- parser failure analysis.

---

# Phase 5 — RAG Evaluation

### Goal

Measure whether the retrieval system finds appropriate NCERT material.

### Dataset

Build a labelled retrieval benchmark across:

- grades,
- topics,
- chapters,
- conceptual questions,
- arithmetic questions,
- multi-step questions.

For each query, identify relevant source chunks.

### Metrics

Measure:

```text
Recall@1
Recall@3
Recall@5
MRR
```

where appropriate.

### Additional analysis

Where practical compare:

```text
BM25
Dense retrieval
Hybrid RRF
```

Also record:

- wrong-grade retrieval,
- irrelevant retrieval,
- missing retrieval,
- retrieval latency.

### Evidence

- retrieval benchmark,
- metric table,
- successful retrieval examples,
- failure examples,
- latency measurements.

---

# Phase 6 — Conversation Resolution Evaluation

### Goal

Measure whether contextual follow-ups are resolved correctly.

### Categories

Include:

```text
Standalone question
Follow-up
Elliptical follow-up
Correction
Confusion
Fragment
Conceptual follow-up
Question modification
```

Example:

```text
Original:
What is 26 + 15?

Follow-up:
What if it were 5 instead of 1?
```

### Metrics

Measure:

```text
Resolution accuracy
Intent/mode accuracy
Correct reference to previous turn
Incorrect-context rate
Abstention/uncertainty rate
```

### Evidence

Store:

- labelled examples,
- predicted modes,
- expected modes,
- resolved questions,
- failure categories.

---

# Phase 7 — Tutoring Policy / Controller Evaluation

### Goal

Evaluate the pedagogical behaviour encoded in the controller.

### Scenarios

1. New question.
2. Student immediately asks for the answer.
3. Student gives correct answer.
4. Student gives wrong answer.
5. Student gives repeated wrong answers.
6. Student asks for a hint.
7. Student asks for another hint.
8. Student is confused.
9. Student gives up.
10. Student requests a new question.
11. Student asks a conceptual follow-up.
12. Student changes part of the original problem.

### Metrics

```text
Expected state-transition accuracy
Policy violation count
Premature-answer rate
Hint-policy compliance
Correct-reveal rate
```

A key metric is:

> **Premature final-answer disclosure rate.**

This should ideally be zero on the controlled evaluation set.

### Evidence

- controller state traces,
- state-transition accuracy,
- policy violation examples,
- representative conversations.

---

# Phase 8 — End-to-End System Evaluation

### Goal

Evaluate the actual tutor rather than isolated components.

Build a balanced test set containing:

- arithmetic,
- multi-step problems,
- fractions,
- remainders,
- distractors,
- conceptual questions,
- follow-ups,
- corrections,
- confusion,
- hints,
- repeated mistakes.

Do not restrict the final system evaluation to arithmetic.

## 8.1 End-to-end task record

For every task record:

```text
Question
Student input sequence
Expected behaviour
Expected answer
Controller state
Generated response
Final answer
Verification result
Pass/fail
```

### Metrics

```text
Task success rate
Mathematical correctness
Response validity
Premature-answer rate
Verification agreement
```

## 8.2 Multi-turn tutoring evaluation

Evaluate complete conversations:

```text
Tutor asks question
       ↓
Student attempts
       ↓
Tutor diagnoses
       ↓
Student asks for hint
       ↓
Tutor gives hint
       ↓
Student retries
       ↓
Tutor evaluates
       ↓
Tutor adapts
```

Check whether the tutor:

- retains context,
- avoids leaking answers,
- gives appropriate hints,
- recognizes correctness,
- handles repeated errors,
- resolves follow-ups.

---

# Phase 9 — Latency and Performance Evaluation

### Goal

Identify where time and LLM calls are spent.

Instrument:

```text
request start
↓
conversation resolution
↓
retrieval
↓
expression extraction
↓
verification/computation
↓
LLM generation
↓
streaming start
↓
response complete
```

### Metrics

Measure:

```text
Total latency
Time to first token
Retrieval latency
Verifier latency
Resolver latency
LLM latency
Number of LLM calls
```

Report:

```text
Mean
Median
P95
```

where sample size permits.

### Analysis

Identify:

- unnecessary LLM calls,
- slow retrieval,
- repeated computation,
- slow generation,
- rate-limit failures.

---

# Phase 10 — Reliability and Failure Evaluation

### Goal

Evaluate behaviour when dependencies fail.

Test:

- LLM timeout,
- LLM API failure,
- invalid model response,
- malformed expression,
- retrieval failure,
- empty retrieval result,
- verifier failure,
- database failure,
- invalid student input,
- session interruption.

### Expected behaviour

```text
fail safely
+
give a useful user-facing message
+
record technical failure
+
avoid corrupting learner state
```

### Evidence

Create a failure-mode table:

| Failure | Expected behaviour | Actual behaviour | Pass |
|---|---|---|---|
| LLM timeout | Graceful handling | Record | |
| Retrieval failure | Safe fallback | Record | |
| Verifier failure | Do not claim verification | Record | |
| DB failure | Safe state handling | Record | |
| Invalid input | Friendly validation | Record | |

---

# Phase 11 — Live Deployment

## Target architecture

The capstone does not require a complicated CI/CD stack.

Recommended:

```text
GitHub
   │
   ▼
Streamlit Community Cloud
   │
   ├── Streamlit frontend
   ├── Tutor controller
   ├── RAG
   ├── Verification
   └── LLM client
          │
          ▼
     LLM Provider

Streamlit
   │
   ▼
Supabase PostgreSQL
   │
   ├── Users
   ├── Student profiles
   ├── Attempts
   └── Learning history
```

### Deployment requirements

- Production secrets stored outside Git.
- Persistent database.
- Authenticated students.
- Independent student state.
- Prepared RAG resources.
- Deployment-safe initialization.
- Error logging.
- Reasonable startup time.
- No dependence on local filesystem persistence for student data.

### Deployment test

Use multiple accounts simultaneously:

```text
Student A ── session A
Student B ── session B
Student C ── session C
```

Verify independent:

- login,
- conversations,
- attempts,
- levels,
- progress,
- history.

---

# Phase 12 — Final System Acceptance Test

Before declaring the project capstone-ready, conduct one complete acceptance run against the deployed application.

## Authentication

- [ ] Sign-up works.
- [ ] Login works.
- [ ] Logout works.
- [ ] Invalid credentials handled.
- [ ] Student data isolated.

## Tutor

- [ ] New question works.
- [ ] Correct response works.
- [ ] Wrong response works.
- [ ] Hints work.
- [ ] Repeated mistakes work.
- [ ] Give-up works.
- [ ] Answer reveal works.
- [ ] Follow-ups work.
- [ ] Corrections work.
- [ ] Conceptual questions work.

## RAG

- [ ] Relevant NCERT content retrieved.
- [ ] Grade filtering works.
- [ ] Retrieval failures handled.

## Verification

- [ ] Mathematical answer computed.
- [ ] Generated response verified.
- [ ] Parser handles final answers correctly.
- [ ] Ambiguous answers are not silently accepted.

## Learner model

- [ ] Attempts recorded.
- [ ] Correctness recorded.
- [ ] Weak topics updated.
- [ ] Level adaptation works.
- [ ] Student state persists.

## Deployment

- [ ] Public URL works.
- [ ] Multiple users can access it.
- [ ] Secrets are not exposed.
- [ ] Restart does not erase student data.
- [ ] Application handles expected failures.

---

# 6. Final Evaluation Matrix

| Evaluation | Level | Primary metric/evidence |
|---|---|---|
| Existing 36-question arithmetic test | Preliminary/component | Accuracy |
| Expression extraction | Component | Exact expression accuracy |
| Arithmetic computation | Component | Exact correctness |
| Response parsing | Component | Correct extraction / unverifiable rate |
| Retrieval | Component | Recall@K, MRR |
| Conversation resolver | Component | Resolution/mode accuracy |
| Controller | Component | State-transition accuracy |
| Hint policy | Component | Policy compliance |
| Learner model | Component | Correct state updates |
| Authentication | Infrastructure/system | Account/isolation tests |
| Multi-student state | Infrastructure/system | Isolation/persistence |
| End-to-end correctness | Full system | Task success/correctness |
| Multi-turn tutoring | Full system | Behavioural success |
| Progressive disclosure | Full system | Premature-answer rate |
| Verification | Full system | Agreement with trusted computation |
| Latency | Full system | Median/P95 |
| Reliability | Full system | Failure-handling pass rate |
| Deployment | Full system | Live acceptance tests |

---

# 7. Evidence to Record for the Paper

For every experiment, retain raw results rather than only the final percentage.

Recommended experiment record:

```text
experiment_id
date
git_commit
branch
model
model_parameters
dataset_version
dataset_size
system_configuration
retrieval_configuration
verification_configuration
results
errors
notes
```

This makes each paper result traceable to a specific implementation.

---

# 8. Recommended Paper Figures

## Figure 1 — Final system architecture

```text
Student
  ↓
Authentication
  ↓
Streamlit
  ↓
Conversation Resolver
  ↓
Controller
  ├── Tutor policy
  ├── Hint policy
  └── Disclosure policy
  ↓
Pipeline
  ├── RAG
  ├── Verifier
  └── LLM
  ↓
Response
  ↓
Learner Model / Database
```

## Figure 2 — End-to-end tutoring sequence

UML sequence diagram showing:

```text
Student
Streamlit
Resolver
Controller
Retriever
Verifier
LLM
Database
```

## Figure 3 — Controller state machine

Show the main tutoring states and transitions.

## Figure 4 — RAG pipeline

```text
NCERT
→ parsing
→ chunking
→ embeddings/BM25
→ hybrid retrieval
→ RRF
→ top-k context
```

## Figure 5 — Verification pipeline

```text
Question
→ expression extraction
→ safe computation
→ trusted answer
→ generation
→ answer extraction
→ verification
```

## Figure 6 — Multi-student deployment architecture

```text
Multiple browsers
      ↓
Streamlit Cloud
      ↓
Tutor backend
      ↓
Supabase
      ↓
LLM provider
```

---

# 9. Recommended Paper Tables

## Development stages

| Stage | Main capability | Status |
|---|---|---|
| MVP | Basic tutor | Existing |
| Architecture integration | Controller-led tutoring | To implement |
| Learner model | Persistent adaptation | To complete |
| Authentication | Login/sign-up | To implement |
| Verification | Live response verification | To integrate |
| Evaluation | Component benchmarks | To conduct |
| System evaluation | End-to-end benchmark | To conduct |
| Deployment | Multi-student live system | To implement |

## Component evaluation

Report:

```text
Component
Dataset size
Metric
Result
Failure cases
```

## Full-system evaluation

Report:

```text
Scenario
Expected behaviour
Observed behaviour
Pass rate
Failure category
```

## Latency

Report:

```text
Component
Mean
Median
P95
LLM calls
```

---

# 10. Claims That Must Wait for Evidence

Until corresponding experiments are actually conducted, do not state that the system has demonstrated:

- improved learning outcomes,
- superiority over teachers,
- statistically significant learning gains,
- large-scale student performance,
- 200-question evaluation results,
- retrieval metrics that have not been measured,
- Cohen's kappa or other agreement statistics that have not been computed,
- Wilcoxon or other statistical tests that have not been run,
- successful user studies that have not occurred,
- production-scale reliability,
- complete post-generation verification if it is not integrated into the live path.

These may be described as planned evaluation methods, but not as completed experiments.

---

# 11. Definition of "Final Capstone Ready"

The project is capstone-ready when the following three dimensions are satisfied.

## Functional

- Controller is part of the real execution path.
- Progressive disclosure is enforced.
- RAG works.
- Mathematical verification works.
- Hints work.
- Conversation follow-ups work.
- Learner adaptation works.

## Multi-student

- Students can sign up.
- Students can log in.
- Student state is isolated.
- Learning history persists.
- Multiple students can use the system independently.

## Evaluated

- Arithmetic correctness evaluated.
- Expression extraction evaluated.
- Retrieval evaluated.
- Conversation resolution evaluated.
- Controller evaluated.
- End-to-end tutoring evaluated.
- Latency measured.
- Failure handling tested.

## Deployable

- Public application URL.
- Secrets protected.
- Persistent database.
- Deployment survives restart.
- Basic observability/logging.
- No manual local setup required for the evaluator.

---

# 12. Recommended Final Development Order

```text
1. Freeze MVP baseline
        ↓
2. Integrate controller into frontend
        ↓
3. Enforce tutoring/disclosure policy
        ↓
4. Complete learner-state recording
        ↓
5. Introduce persistent student storage
        ↓
6. Add login/sign-up
        ↓
7. Integrate live verification
        ↓
8. Improve answer parsing
        ↓
9. Harden RAG initialization
        ↓
10. Add latency/error instrumentation
        ↓
11. Build evaluation datasets
        ↓
12. Run component evaluations
        ↓
13. Run integrated system evaluations
        ↓
14. Fix evaluation-discovered issues
        ↓
15. Re-run final evaluations
        ↓
16. Deploy
        ↓
17. Run live acceptance tests
        ↓
18. Freeze final experimental results
        ↓
19. Update paper/report with measured results
```

The key principle is:

> **Do not evaluate only the final number produced by the LLM. Evaluate the complete tutoring system: retrieval, reasoning/expression extraction, verification, conversation handling, controller behaviour, learner adaptation, latency, reliability, and finally the end-to-end student interaction.**

---

# 13. Suggested Evaluation Repository Structure

At the end of development, the repository should contain a reproducible evaluation record similar to:

```text
eval/
├── datasets/
│   ├── arithmetic/
│   ├── expression_extraction/
│   ├── retrieval/
│   ├── conversation/
│   └── end_to_end/
│
├── results/
│   ├── arithmetic.json
│   ├── extraction.json
│   ├── retrieval.json
│   ├── conversation.json
│   ├── controller.json
│   ├── latency.json
│   └── end_to_end.json
│
├── controller_walk.py
├── run_arithmetic_eval.py
├── run_retrieval_eval.py
├── run_conversation_eval.py
└── run_end_to_end_eval.py
```

The paper should draw quantitative claims from these recorded results rather than from planned/proposed evaluation methodology.

---

# 14. Final Target Architecture

```text
                    ┌───────────────────┐
                    │   Student Sign Up │
                    │     / Login       │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │  Student Profile  │
                    │  + Learning State │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │   Streamlit Tutor │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │ Conversation /    │
                    │ Intent Resolution │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │     Controller    │
                    │                   │
                    │ Teach / Diagnose  │
                    │ Hint / Co-solve   │
                    │ Reveal / New Q    │
                    └──────┬─────┬──────┘
                           │     │
                    ┌──────▼─┐ ┌─▼────────┐
                    │   RAG  │ │ Verifier │
                    └────┬───┘ └────┬────┘
                         │           │
                         └─────┬─────┘
                               ▼
                         ┌───────────┐
                         │    LLM    │
                         └─────┬─────┘
                               │
                               ▼
                    ┌───────────────────┐
                    │ Verified Tutor    │
                    │ Response          │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │ Student Learning  │
                    │ History / DB      │
                    └───────────────────┘
```

This is the target scope for moving from the existing MVP to a **working, authenticated, multi-student, evaluated, publicly deployable capstone project**.
