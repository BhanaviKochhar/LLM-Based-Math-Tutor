# Conceptual Tutoring Evaluation

Evaluates the behaviour observed in the user-supplied "fractions" conversation against the rubric in `docs/evaluation_plan.md` §3, traces the actual execution path component-by-component, confirms (not assumes) the architectural root cause, and — per explicit instruction — proposes rather than implements any structural fix.

## 1. Reproduction

The conversation was reproduced directly against the live application flow (`frontend.app.submit_turn`, real LLM calls, not mocked) in the prior session of this engagement, and the controller-level root cause was re-confirmed as a deterministic fact in this session (`frontend/test_app.py::test_conceptual_episode_never_advances`, passing). This section treats the originally observed screenshots as real behavioural evidence (as instructed), not as proof of one specific root cause in advance of verification — the verification below is what confirms the cause.

## 2. Component-by-component trace

| Component | Role in this conversation | Finding |
|---|---|---|
| Frontend history (`frontend/app.py`) | Starts the episode from the literal text `"fractions"` | Confirmed: this is exactly what the student typed; the frontend passes it through unmodified |
| Conversation resolver (`conversation_resolver.py`) | Resolves `"fractions"` with no prior turns | `mode=NEW`, `resolved_question="fractions"`, `retrieval_query="fractions"` — correct, deterministic behaviour for a standalone first message; **not a resolver defect** |
| Controller state (`controller.py`) | `controller.start("fractions", grade, level, computed_answer=None, is_math=False)` | Opens with `TEACH_INVITE`, correct per design |
| Action selection (`controller.step`) | Every subsequent `ATTEMPT` (regardless of content: `"3/9"`, the mango explanation, etc.) | **Deterministically returns `MODE_ACK_CONCEPTUAL`, non-terminal, `attempts` never increments** — confirmed directly against the real state machine, no mocking, for three different inputs. This is the mechanical root cause of the lack of progression: `controller.diagnose()` can only return `"correct"`/`"wrong"`/`"unclear"` when `is_math=True` and `computed_answer is not None`; otherwise it always returns `"engaged"`. |
| Prompt construction (`prompt_registry.py`) | Builds messages for `MODE_ACK_CONCEPTUAL` via `_d_ack_conceptual`'s directive | Directive reworded this engagement (prior session) to ask for acknowledgment of the student's specific wording — **a prompt-level mitigation attempt, not a controller-level fix** |
| Retrieval results (`scripts/retrieval.py`) | Retrieves for the query `"fractions"` | **Confirmed defective for this specific query**: returns a multiplication-table chunk and a division-worksheet chunk, neither about fractions (`eval/datasets/retrieval/v1_starter.jsonl` rq-001). This directly explains the unrelated "34 students / 68 toffees / 8/10" example that appeared in the live transcript — it is retrieved context, not a model invention. See `docs/retrieval_evaluation.md` for the root-cause investigation of *why* this specific query retrieves poorly (appears term-specific to "fractions," not a general short-query defect). |
| Context assembly / `active_turns` | Full conversation history passed to every generation call | Confirmed present and correctly ordered (via `build_active_turns`); the cross-turn misattribution observed in the A/B comparison (below) therefore is **not** explained by missing history — the history was available to the model and it still referenced the wrong turn |
| Model response | Generated via `llm_client.stream()` | See rubric scoring below |
| Verification/disclosure | `verifier.check()` / controller disclosure gating | Not exercised in this conversation — `MODE_ACK_CONCEPTUAL` is not a reveal/co-solve mode, so no trusted answer exists to check or leak; **no disclosure-safety issue observed** |
| Student tracking | `_record_outcome` | Not triggered — `MODE_ACK_CONCEPTUAL` is correctly excluded from attempt recording (confirmed by `frontend/test_app.py::test_attempt_recording_semantics`), so this conversation does not pollute the learner model with false "engaged" data points |

**Conclusion on cause:** the non-progression and generic/repetitive responses are **not** attributable to any single component in isolation. They are the combined effect of (a) a controller design property that is *correct by design* (it will not fabricate a grade for an ungradable question) but has no path toward making the question gradable, and (b) a genuinely poor retrieval result for this specific query feeding the wrong textbook context into generation. Both are independently confirmed, not assumed.

## 3. Rubric evaluation

Scored against `docs/evaluation_plan.md` §3's 1/3/5 rubric, using the actual live transcripts (reworded-directive version, this engagement's prior session; see `docs/development_test_log.md` for full text). This is a **single rater's assessment of a single conversation** — not inter-rater-validated, and explicitly not presented as proof of general tutoring quality.

| Case | Dimension | Score | Justification |
|---|---|---|---|
| co-002 (mango reasoning: "I have one mango, cut in 2 pieces. I have both pieces.") | `relevance_to_latest_input` | **1** | Response ("Nice, you've written 'fractions'...") does not engage with the mango content at all |
| co-002 | `recognition_of_demonstrated_reasoning` | **1** | The correct reasoning (2/2 = 1 whole) is neither named nor built on |
| co-002 | `context_preservation` | **1** | Response explicitly misattributes content to turn 1 ("you've written 'fractions'") when the actual current turn was about the mango — this is the rubric's own worked example of a score-1 case |
| co-002 | `avoidance_of_unnecessary_repetition` | **3** | Some overlap with earlier fraction-simplification content, but not a verbatim repeat |
| co-002 | `appropriate_progression` | **1** | No forward movement; still stuck at the same conceptual acknowledgment after 3+ turns |
| co-001 (`"3/9"` in response to "one-third of nine toffees") | `mathematical_correctness` | **3** | No false claim is made (states 3/9 can be reduced, which is true), but does not address the quantity-vs-proportion distinction the case calls for |
| co-001 | `recognition_of_demonstrated_reasoning` | **2** | Acknowledges the student is "thinking about fractions" (a genuine, new-this-session improvement over the original directive, which gave zero acknowledgment) but does not engage with the *specific* value 3/9 or its relationship to the question asked |

**Overall assessment:** the current implementation does **not** meet the rubric for this conversation on the dimensions that matter most for conceptual tutoring (relevance, reasoning recognition, context preservation, progression). The one measured improvement from this engagement's prompt reword (generic acknowledgment phrases appearing where they didn't before) is real but minor relative to the gaps that remain.

## 4. Is the "no numeric trusted answer → stuck in engaged" behaviour still true?

**Confirmed, yes**, as a deterministic property of the current controller (§2 above; regression-tested). This review did **not** force numeric diagnosis onto this conceptual question — that would require inventing a trusted answer for an inherently non-numeric exchange, which `verifier.solve()` correctly declines to do for `"fractions"`.

## 5. Proposed design discussion (not implemented — requires your decision)

### Root cause (restated)
`controller.diagnose()` has exactly three branches: `is_math=False` → `"engaged"` (always), or `is_math=True` with a computed answer → `"correct"`/`"wrong"`/`"unclear"`. There is no path for a conceptual episode to acquire a concrete, gradable sub-question over the course of the conversation.

### Current behaviour
Every turn in a conceptual episode routes to the same `MODE_ACK_CONCEPTUAL` action, indefinitely, with no state change (`attempts` frozen at 0, `phase` frozen at `AWAITING`).

### Option A — "graduate" a conceptual episode into a math episode
When the model, during an `ACK_CONCEPTUAL` turn, poses a concrete follow-up exercise (as it already tends to do unprompted — e.g. "one-third of nine toffees"), have the controller capture that posed sub-question, run it through `verifier.solve()`, and if computable, transition the episode's `is_math`/`computed_answer` to the new values so the *next* turn can be genuinely diagnosed.
- **Risk**: requires a new, reliable way to extract "the question the tutor just posed" from generated text — itself an extraction problem, with its own failure modes (the same class of ambiguity this review already found in `response_parser`).
- **Compatibility**: additive to the state machine (a new transition), should not require changing any existing arithmetic-path transition; `eval/controller_walk.py`'s 27 scenarios should remain valid without modification if implemented as a new branch.
- **Tests required**: new controller scenarios (conceptual → graduated-to-math → diagnosed), extraction tests for "question posed by the tutor," and multi-turn tests confirming no regression to the existing 11 controller_walk.py scenarios.

### Option B — looser, rubric-based "informal correctness" signal for conceptual turns
Instead of binary correct/wrong, use an LLM-judged or rule-based partial signal (e.g. "does the student's text contain the key terms/values expected for this concept") to let the controller at least distinguish "engaged with relevant content" from "off-topic," without claiming full arithmetic verification.
- **Risk**: reintroduces exactly the kind of unverified LLM judgment the project's whole design philosophy (compute-first, deterministic controller) was built to avoid — a significant philosophical tension with "everything that needs to be reliable is kept outside the language model" from the paper's own framework.
- **Compatibility**: would need its own new controller mode and disclosure policy.

### Option C — do not change the controller; instead improve retrieval for conceptual queries and leave the ACK_CONCEPTUAL loop as a "teach, then redirect to a concrete question" pattern, more explicitly
Smallest change: strengthen `_d_ack_conceptual`'s directive further to explicitly instruct the model to, within 1-2 turns, propose ONE specific numeric exercise and hand off to the student trying it (effectively manually triggering what Option A would automate) — relying on prompt compliance rather than new controller logic.
- **Risk**: prompt-compliance-only fixes have already shown limited reliability in this review's own A/B test.
- **Compatibility**: zero controller/architecture risk — purely a prompt wording change, same class of edit as this engagement's existing `_d_ack_conceptual` reword.

**Recommendation (not implemented):** Option C is the only one of the three low-risk enough to attempt without a design-review conversation first; Options A and B both touch the controller's core state machine and should not proceed without your explicit sign-off given their blast radius on a component the whole project's reliability argument depends on.

## 6. What was and was not done in this pass

- **Done**: reproduction, rubric scoring, root-cause confirmation via direct code inspection and a regression test, architecture trace across all 10 named components.
- **Not done (by design, pending your decision)**: any change to `controller.py`'s state machine or diagnosis logic for conceptual episodes.
