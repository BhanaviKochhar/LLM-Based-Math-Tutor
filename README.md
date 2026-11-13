# TinyThinker — A Retrieval-Grounded, Verifier-Gated LLM Tutor for NCERT Primary Mathematics

A Streamlit tutoring app for NCERT Class 1–5 mathematics. The design principle behind every
component below is the same one: **anything that needs to be reliable is kept outside the
language model.** Curriculum facts come from retrieval, numerical truth comes from SymPy, and
the choice of tutoring move (teach / hint / diagnose / co-solve / reveal) comes from a
deterministic state machine. The LLM's only job is to supply the words.


---

## 1. Quick start

### Requirements

- Python **3.10+**
- A Groq API key and/or a Hugging Face token (at least one)
- The five NCERT *Math-Magic* PDFs (Classes 1–5) — not committed to the repo, download from
  [NCERT Classes 1-5](https://drive.google.com/drive/folders/1DBPLkxJh6Y6-zJNLeopLxnYEaSN2AV_T?usp=sharing)

```bash
git clone <repo-url>
cd LLM-Based-Math-Tutor

python -m venv venv
source venv/Scripts/activate      # Windows Git Bash
# source venv/bin/activate        # macOS/Linux

pip install -r requirements.txt
```

Create `.env` in the project root:

```env
GROQ_API_KEY=your_groq_key_here
HF_TOKEN=hf_your_token_here
```

Never commit `.env`.

### Build the local knowledge base (one-time, or whenever the PDFs/chunking change)

Download the PDFs from the link above and place them at `data/raw_pdfs/class1.pdf` …
`class5.pdf`, then from the repo root:

```bash
python scripts/parse_ncert.py     # PDFs -> data/extracted_json/ncert_chunks.json
python scripts/load_chromadb.py   # chunks -> embeddings -> data/chromadb/
```

Both `data/raw_pdfs/` and `data/chromadb/` are gitignored — they're either user-supplied source
material or fully regenerable from `ncert_chunks.json` (which *is* committed).

### Run it

```bash
streamlit run frontend/app.py
```

### Sanity-check retrieval alone (no LLM call, no UI)

```bash
python -u scripts/retrieval.py
```

### Run the test suites

```bash
python -m frontend.test_app            # 176 tests — UI/state logic
python -m scripts.llm.test_pipeline    # 266 tests — verifier/pipeline/prompt logic
python -m eval.controller_walk         # 127 checks — controller state-machine scenarios
python -m eval.validate_datasets       # 57 checks — eval dataset schema/integrity
python -m scripts.test_retrieval       # 16 checks — retrieval behavior
python -m scripts.llm.test_scope       # 95 checks — the syllabus scope gate
python -m eval.test_answer_extraction  # 46 checks — the evaluation's final-answer scorer
```

All seven are offline (no network, no API keys). `eval.controller_walk` has a known 0–2 flaky
failures from timing; rerun before treating a failure as real.

---

## 2. Architecture at a glance

```
Student types a message
        │
        ▼
frontend/views/main_page.py  (ask-bar form)
        │  queue_pending_turn()  — stores it, shows the question bubble immediately
        ▼  (next Streamlit rerun)
frontend/episode.py  process_pending_turn() -> submit_turn()
        │
        ├─ 1. safety.check_input()            deterministic, runs BEFORE any LLM call
        ├─ 2. scope.check()                   deterministic syllabus-scope word rules
        ├─ 3. conversation_resolver.resolve_question()   NEW / FOLLOWUP / CONFUSION / ...
        │     (a chat's first message: classify_opener() — NEW / CLARIFY / ADVANCED,
        │      one small-model call, gpt-oss-20b)
        ├─ 3b. scope.needs_beyond_primary()   small-model scope check (gpt-oss-20b), only
        │                                      where a new problem starts
        ├─ 4. scripts.retrieval.retrieve_with_metadata() hybrid BM25 + ChromaDB, RRF, top 3
        ├─ 5. verifier.solve_with_type()       compute-first: numeric -> quotient/remainder
        │                                      -> named functions -> categorical
        ├─ 6. intent.classify_intent()         ATTEMPT / HINT / SOLVE / GIVE_UP / ...
        ├─ 7. controller.start() / .step()     the tutoring state machine decides the Action
        ├─ 8. prompt_registry.build_messages() assembles the final prompt
        ├─ 9. llm_client.stream()              Groq -> HF/nscale -> HF/deepinfra fallback
        ├─ 10. response_parser                 strip stray LaTeX, collapse blank-line runs
        ├─ 11. _post_check() -> verifier.check()   only for REVEAL/CO_SOLVE: does the
        │                                          model's own stated number match truth?
        ├─ 12. student_tracker.record()        ONLY for genuine graded attempts
        └─ 13. common.log_run() / telemetry.log_interaction()   two separate logs
        ▼
frontend/views/main_page.py renders the reply, verify-tag, citation, badges/progress
```

Every one of those steps is a real, separately-testable module — not a single monolithic
prompt. The rest of this document walks through each one, then traces a complete turn
end-to-end through them in order.

---

## 3. The frontend (`frontend/`)

| File | Role |
|---|---|
| `app.py` | Entry point. Sets Streamlit page config, re-exports names from the modules below (so tests/eval scripts can still `from frontend import app`), and routes between the two screens based on `ss.page`. |
| `config.py` | One flag: `MOCK_MODE`. When `True`, the UI runs against canned responses with zero backend/API calls — used by the test suite, not live use. |
| `state.py` | `st.session_state` setup and the identity/personalization bridge. `_student_id()` is a per-browser-session opaque UUID (not the child's name, not a shared constant) — the bounded fix that keeps today's single-session identity separate from tutoring logic so a real auth layer can replace it later without touching `episode.py`/`pipeline.py`. Also home to `change_grade()` (invalidates every chat's *open* episode on a grade switch, never past messages — an in-progress episode's trusted answer and hints were computed for the old grade's taught form) and `clear_chat()`/`reset_learning_progress()` (deliberately two separate actions: clearing a chat window must never silently erase the persistent learner profile). |
| `episode.py` | The orchestration layer — see §6, the longest and most central module in the frontend. |
| `markdown_utils.py` | A tiny `**bold**`/`` `code` `` renderer for replies — not full Markdown, just the two constructs the tutor's prompts actually use. |
| `styles/global_css.py`, `main_css.py`, `scene_css.py` | All CSS. `main_css.py` (893 lines) carries the chat page's design tokens, the three-panel layout, the scallop-free card styling, and the `overscroll-behavior` fixes for the empty-chat scroll bug. `scene_css.py` is the onboarding page's illustrated world. |
| `views/name_page.py` | Screen 1: name + class, the Pandi mascot (animated `.webm`, base64-embedded as a `<video>` — not `<img>`, which renders the SVG pack's poses with an opaque white box), the illustrated scene. |
| `views/main_page.py` | Screen 2: the actual chat — history/progress side panels, the ask-bar form, badge/progress computation, and `render_turn()`/`render_chat_reply()` which decide what a given stored message renders as (a graded turn with a verify-tag, or a plain conceptual chat reply). |
| `assets/onboarding_scene.py` | Hand-authored inline SVGs for the onboarding page's illustrated world (sun, clouds, hills, forest critters) — built from one shared "critter" template so the whole cast reads as one coherent design. |
| `assets/pandi.webm` | The current onboarding mascot animation. |
| `test_app.py` | 169 tests covering UI/state logic (safety redaction, button gating, progress math, episode lifecycle) with the backend mocked — no network. |

---

## 4. The backend (`scripts/llm/`)

### 4.1 `controller.py` — the tutoring state machine (794 lines)

The single most important file for *why this isn't just a chatbot*. A `TutorState` dataclass
tracks one open problem: `question`, `grade`, `level`, `computed_answer`, `is_math`,
`answer_type`, `attempts`, `hints_given`, `phase`. `step()` takes the current state + the
student's classified intent and returns a new state + an `Action` (a `mode`, a `directive`
string the prompt will expand, which `buttons` to show, and whether the turn is `terminal`).

Modes: `teach_invite` (fresh problem, answer withheld) → `hint` (up to `MAX_HINTS=3`) →
`diagnose_correct` / `diagnose_wrong` → `co_solve` (triggered after `_COSOLVE_AFTER` wrong
attempts — 2 for beginner/intermediate, 3 for advanced, so a strong student gets one more
independent try before the system co-solves) → `reveal`. Side branches handle `confusion_help`
(re-explain, don't restart the hint ladder), `correction_repair`, `clarify`, and
`ack_conceptual` (a broad "teach me fractions" question with nothing computable to protect).

`diagnose()` grades an attempt against `computed_answer`, branching on `answer_type`:
`numeric` (SymPy exact comparison), `categorical`/`time`/`list`/`quotient_remainder` each use
their own conservative matcher (`_categorical_match`, `_time_match`, `_list_match`,
`_qr_match`) that can only return "correct" or "engaged" — never a false "wrong," since each is
a best-effort pattern read of free text, not an unambiguous single-value comparison.

`_invite_buttons()` is the rule that "Give me a hint"/"Show me how" only ever appear when
`state.is_math and state.computed_answer is not None` — a broad conceptual reply has nothing
hidden to hint toward, so those buttons used to appear even when meaningless; every call site
that offers them now goes through this one gate.

### 4.2 `verifier.py` — compute-first ground truth (785 lines)

Never calls the model to check its own arithmetic. Given a question, an LLM-based extractor
(few-shot, temperature 0) proposes a plain arithmetic expression from an allow-listed grammar
(`^[0-9+\-*/.()\s]+$` — no letters, no functions, nothing `eval()`-dangerous); `_safe_eval()`
parses it with `sympy.sympify(..., rational=True)` for exact (not floating-point) results.

`solve_with_type()` is the live controller's entry point, trying four paths in order and
stopping at the first that applies:
1. **Numeric** — the allow-listed grammar above. `_grade_appropriate_answer()` withholds a bare
   non-exact `int/int` division (taught as quotient+remainder at this level, not a decimal) —
   *unless* the question's own wording signals a genuine fraction/decimal-conversion intent
   (`_looks_like_fraction_conversion`), which `_FRACTION_CONVERSION_RE` detects from phrases
   like "as a decimal" or "what fraction."
2. **Quotient/remainder** — when (1) withheld a bare division, `_quotient_remainder()` still
   computes and grades the `"q remainder r"` form directly, instead of leaving it ungraded.
3. **Named functions** — a small fixed registry (`_FUNCTION_REGISTRY`): `lcm`, `hcf`/`gcd`,
   `is_prime`, `factors`, `angle_type`, `time_add`. A second extractor recognizes calls like
   `lcm(4, 6)` from the question; every argument is independently run back through
   `_safe_eval`, so only plain numeric sub-expressions can ever reach a real function call.
4. **Categorical** — a third extractor for short, non-arithmetic factual answers (a day name, a
   shape name, yes/no) that don't fit any of the above.

`check()`/`check_self_consistency()` run *after* generation: the former compares the model's
own stated final number against the trusted value (only for modes that actually inject one);
the latter is a bounded guardrail for every other mode — did the model's own worked example
actually add up, independent of any trusted value.

### 4.3 `scope.py` — the syllabus boundary (430 lines)

Before this module existed, "refuse topics beyond primary school" was pure prose inside the
main tutoring prompt, with zero code-level backstop — confirmed live to fail (a request to
*solve* an integral got a full worked walkthrough instead of a refusal). `scope.check()` runs a
regex deny-list (`BEYOND_PRIMARY_TOPICS` for advanced math topics, `NON_MATH_SUBJECTS` for
non-maths subjects entirely) against the message *before* any LLM call. Three outcomes: in
scope (continue normally), a bare "what is X" definition request for an out-of-syllabus math
topic (`allow_gloss=True`, routed to `generate_gloss()` — a small, single-purpose LLM call, not
the big multi-instruction tutoring prompt, which was found not to reliably hold "no formula, no
worked example" when competing with everything else in that prompt), or a hard refuse with zero
LLM call at all (`REFUSAL_TEXT = "Let's ask your teacher about this one!"`). Non-math subjects
never get the gloss exception — a maths tutor shouldn't teach photosynthesis even briefly.

Word rules only catch phrasings someone listed (on 40 fresh disguised questions they stopped 4),
so `needs_beyond_primary()` adds a concept-level check by a small model (`gpt-oss-20b`,
temperature 0, medium reasoning effort, its own rate-limit pool): does answering this properly
need maths beyond Class 5, even when asked in plain words? It runs only where a new problem
starts (an opener, a new question, a changed problem) — never on attempts, hints or give-ups —
skips bare arithmetic, and any failure leaves the message in scope. Its prompt is written from
the Class 1–5 topic list and the beyond-primary list, never from test questions.

### 4.4 `intent.py` + `conversation_resolver.py` — understanding the turn

Two different jobs, both cascade (cheap-first) classifiers:

- **`intent.py`** labels *what the student wants to do next* about the problem already on the
  table: `ATTEMPT`, `HINT`, `CONFUSION`, `SOLVE`, `GIVE_UP`, `CORRECTION`, `MATH_FOLLOWUP`,
  `CLARIFY`, `NEW_QUESTION`. A deterministic prefilter catches a bare number/expression as
  `ATTEMPT` and a bare "no"/"that's wrong" as `CORRECTION` for free; otherwise a few-shot LLM
  call; if that returns nothing (rate limit), a keyword fallback guess rather than a crash.
  UI button clicks bypass all of this and emit the label directly — the classifier only ever
  sees typed free text.
- **`conversation_resolver.py`** decides *what the message actually refers to*, generically —
  `NEW` / `MATH_FOLLOWUP` / `CONCEPT_FOLLOWUP` / `CONFUSION` / `CORRECTION` / `FRAGMENT` — and
  for a follow-up, resolves it into a self-contained question (e.g. "what if it were 5 instead"
  after "what is 3/7 + 1" resolves to "what is 3/7 + 5"). A tiny deterministic regex handles the
  unambiguous "X instead of Y" grammar without an LLM call; a low-confidence LLM resolution
  (`confidence < 0.70`) is downgraded to `FRAGMENT` rather than trusted, since an unsafe rewrite
  is worse than asking the child to clarify.
- **`classify_opener()`** handles a chat's *first* message. A message with a quantity in it is a
  real problem (no call); anything else gets one small-model call (`gpt-oss-20b`) answering
  `NEW` (start teaching), `CLARIFY` (too vague — "Which is the bigger one?" — so ask what the
  child means and open no problem) or `ADVANCED` (needs maths beyond Class 5 — refuse). Any
  failure means `NEW`.

### 4.5 `prompt_registry.py` — final message assembly (311 lines)

`build_messages()` is where everything upstream converges into the actual LLM call. The system
prompt (`TUTOR_SYSTEM`, persona "Ganita Didi") carries the always-vs-refuse rule, the
"child can only read your words, never reference a picture" rule, and the no-LaTeX formatting
rule. `PERSONALIZED_SYSTEM` appends the resolved level's `LEVEL_STYLE` block (beginner:
define every term, show the method behind every sub-step, up to 6 steps; intermediate: 3-4
steps; advanced: 2-3 tight steps, answer still always shown — personalization adjusts *depth*,
never whether the student eventually sees the answer). If a trusted value was computed,
`_INJECTED_ANSWER_BLOCK` tells the model the answer and that every step must lead to it. If
there's conversation history, `memory.thread_summary()` + the continuity rule are appended so
the model doesn't repeat itself across turns. The controller's own `directive` string is
appended last, as the freshest instruction the model sees.

### 4.6 `memory.py` — two bounded layers (96 lines)

**Active session**: the full prior turns of the *current* episode, passed through verbatim so
the controller can diagnose attempts without re-teaching. **Thread**: a capped list
(`MAX_THREAD_NOTES=5`) of one-line templated summaries of *earlier finished* episodes this
session (`build_thread_note` — "asked 'what is 3/7+1' · solved it · 1 attempt"), giving the
tutor continuity across topics without dragging whole explanations along. The model judges
concept similarity itself from the raw question text in each note; nothing here labels a topic.
This is fully wired: `episode.py` reads/writes `chat["thread_notes"]` on every episode
completion via `memory.add_note()`.

### 4.7 `student_tracker.py` — rule-based personalization (111 lines)

`classify()` is pure, auditable logic: look at the last `WINDOW=5` graded attempts for this
student; with fewer than `MIN_ATTEMPTS=3`, stay at the neutral default (`intermediate`);
otherwise `accuracy < 0.4` → `beginner`, `< 0.75` → `intermediate`, else `advanced`. Because
it's a sliding window over *recent* attempts (not a cumulative high-water mark), the level
genuinely moves back down after a run of wrong answers, not just up — confirmed live in this
engagement with a 7-question journey that went beginner → advanced → intermediate → beginner as
performance actually changed. `record()` is called only for genuine graded attempts (never
hints, never a cold reveal with zero attempts) — see `episode._record_outcome()`.

### 4.8 `topics.py` — canonical weak-topic names (68 lines)

A flat, 14-topic, grade-independent keyword classifier grounded in
`docs/verified_ncert_class_1_5_topics.md`, used *only* for aggregating weak-topic tracking (so
"how do I add 56 and 27" and "56+27 explain" count as the same topic instead of two unrelated
30-character-truncated strings) — never for scope gating, which is `scope.py`'s separate job on
a separate axis.

### 4.9 `llm_client.py` — the shared streaming client (461 lines)

One `stream()` generator tried against an ordered list of `Target`s: `groq-direct` first, then
the Hugging Face router through `nscale`, then through `deepinfra` — deliberately never routing
back to Groq *through* HF, since that gains nothing if Groq itself is down. Fallback is
strictly pre-first-token: once any text has streamed from a target, the response commits to
that target even if it later errors, so the UI never receives an answer spliced from two
providers. A missing API key silently disables its target rather than raising. `chat()` is the
non-streaming convenience built on the same generator.

### 4.10 `response_parser.py` — cleaning model text (261 lines)

`strip_latex()` deterministically rewrites stray `\frac{1}{4}` → `1/4`, `\sqrt{9}` → `sqrt(9)`,
drops any other backslash command, and runs unconditionally on every turn (not a
regenerate-on-detection loop — a prompt instruction alone didn't hold 100% of the time, and an
unstripped leak would have broken this app's own number-parsing too, not just readability).
`collapse_excess_blank_lines()` fixes a `white-space: pre-wrap` CSS interaction where a model's
long runs of blank lines between worked-example steps rendered as a wall of dead vertical
space. `final_number_str()` reads the model's stated final value with a confidence-tiered
fallback (an explicit "Answer:" line, then the last "= value" statement, then — only if
unambiguous — the sole numeric token in the text) rather than ever guessing between
first-number-in-text and last-number-in-text, both of which are wrong for different reasons
documented in the module's own docstring.

### 4.11 `safety.py` — deterministic child-safety gate (116 lines)

Bounded keyword/pattern matching (self-harm, violence, profanity, personal info) — explicitly
not an LLM call, because the entire point is to run *before* any LLM-based routing sees the
text at all, so an unsafe message is never forwarded to a model. `check_output()` is a
symmetric defense-in-depth pass on what the model itself generated. Never mentions which
category matched in the child-facing fallback text.

### 4.12 `hints.py` — one short call per hint level (144 lines)

Hints escalate generically (gentle nudge → concrete partial step → "one small thing left") by
*position in the budget*, not by a real per-problem step count — the module's own docstring is
explicit that no component here counts a specific problem's actual solution steps. Grounded in
the same retrieved chunks as the eventual answer plus the true computed value (never spoken),
and told what earlier hints already said so levels build on each other instead of repeating.

### 4.13 `pipeline.py` — routing + legacy surface (545 lines)

`resolve_level()` is the single source of truth the whole app uses for "what level is this
student" — prefers `student_tracker`'s live classification once there are ≥3 recent attempts,
else falls back to whatever the UI shows. `compute_trusted_answer()` wraps
`verifier.solve_with_type()` for the live controller path specifically (never raises — any
verifier exception degrades to "not computable" rather than crashing a turn).
`record_feedback()`/`reset_student()` are the bridge `frontend/state.py` calls into. The file
also still carries an older `TutorTurn`/`prepare()`/`resume()` single-shot surface predating the
controller-driven episode flow — not what `frontend/episode.py` calls today, kept only for
backward compatibility with scripts that import it directly.

### 4.14 Logging: `common.py` vs `telemetry.py`

Two deliberately separate logs. `common.log_run()` writes one record per actual *generation*
call to `data/llm_runs.jsonl` — full prompt messages, raw params, raw provider result; this is
the source of the pilot interaction figures and the early three-model pilot. `telemetry.log_interaction()` writes one compact, structured record per *student
turn* to `data/interaction_events.jsonl` — what was decided (mode, terminal, outcome), not the
raw prompt — reconstructable turn-by-turn without wading through full message payloads. Neither
can raise in a way that breaks a tutoring turn.

---

## 5. Retrieval (`scripts/retrieval.py`)

```
question + grade
       │
       ├─ BM25 (lexical, rank-bm25)  ──┐
       │   top 20 candidates          │
       │                              ├─ Reciprocal Rank Fusion (k=60)
       └─ ChromaDB (dense, cosine) ────┘        │
           top 20 candidates                    ▼
                                          top 3 chunks
```

Both retrievers search only `G(grade) = {grade-1, grade}` (clamped at 1) — a Class 3 query also
searches Class 2 for prerequisite material. Both also exclude two structural noise sources
found live: **front matter** (`page <= 4` — copyright pages, NCF preface, committee lists;
exactly 48 chunks corpus-wide, independently confirmed against the corpus statistics) and
**answer-blank chunks** (a page of fill-in-the-blank underscores with no teaching content; 15
chunks, 13 of them in the Class 1 book).

A real correctness bug this engagement found and fixed: duplicate chunk text (the same NCF
preface paragraph appears verbatim on page 3 of *all five* grade books) used to be
reverse-looked-up by matching text against the full corpus, which silently resolved to
whichever duplicate loaded last — confirmed live, citing a child's Class 1 retrieval as if it
were from Class 5. Both retrievers now rank and return stable chunk **indices**, never text, so
`retrieve_with_metadata()` indexes directly off the fused ranking with no reverse lookup.
`_canonicalize()` pools duplicate-text chunks onto one representative *within the requested
grade window* — but deliberately does **not** de-duplicate a single retriever's own ranked list,
since letting both retrievers' independent votes for the same canonical passage sum together in
RRF reproduced the old "both retrievers agree" boost; an earlier attempt that dropped the second
occurrence measurably hurt Recall@3.

Public contract: `retrieve(question, grade) -> list[str]` (3 chunk texts) and
`retrieve_with_metadata(...) -> list[dict]` (full `{text, grade, page, source}` records, used
when the UI needs to show a citation).

---

## 6. `frontend/episode.py` — tying it all together (808 lines)

This is where every backend module above actually gets called, in order, for a real turn.

- **`queue_pending_turn()` / `process_pending_turn()`** — a turn is split across two Streamlit
  reruns on purpose: the first stores the question and shows it immediately as a chat bubble;
  the second (triggered by the rerun that follows) actually does the LLM work, so the "thinking…"
  indicator has something real to show against instead of the whole UI freezing silently.
- **`submit_turn()`** — the real entry point. Runs `safety.check_input()` first (zero LLM calls
  if blocked), then `scope.check()` (zero LLM calls if hard-refused), then routes into either
  `start_episode()` (a brand new question) or `advance_episode()` (continuing one).
- **`start_episode()`** — resolves the conversation, retrieves, computes a trusted answer via
  `pipeline.compute_trusted_answer()`, resolves the student's level, and calls
  `controller.start()` to get the opening `teach_invite` action.
- **`advance_episode()`** — classifies intent (button label or `intent.classify_intent()`),
  calls `controller.step()`, and for a conceptual episode that's still looping
  (`MODE_ACK_CONCEPTUAL`), tries `controller.graduate_if_computable()` against the *tutor's own
  reply* — if the tutor just posed a concrete computable exercise unprompted
  ("pick a fraction like 2/3 and multiply both parts by 3 — what do you get?"), the episode
  graduates to a real trusted answer so the child's next reply is actually graded instead of
  looping forever.
- **`_apply_action()` → `_run_generation()`** — builds the prompt via `prompt_registry`, streams
  from `llm_client`, cleans the text via `response_parser`.
- **`_post_check()`** — runs `verifier.check()` only for `REVEAL`/`CO_SOLVE` (where a trusted
  value exists and disclosure is happening) and `check_self_consistency()` for every other mode
  as a bounded guardrail.
- **`_record_outcome()`** — the exact rule for what counts as a graded attempt: every
  `DIAGNOSE_WRONG`, the terminal `DIAGNOSE_CORRECT`, a `CO_SOLVE` reached *by exhausting the
  attempt threshold* (not by giving up — `outcome == "shown"`, not `"gave_up"`), and a `REVEAL`
  honored after at least one real attempt. Asking to be shown the solution with zero attempts is
  a request for help, not a wrong answer, and must never be recorded as one.

---

## 7. Data flow — one complete turn, start to finish

A child on Class 3, mid-conversation, types **"what if it was 5 instead of 3?"** after
previously asking "What is 12 times 3?":

1. `main_page.py`'s form submit → `queue_pending_turn()` stores the raw text, shows the bubble.
2. Next rerun → `process_pending_turn()` → `submit_turn()`.
3. `safety.check_input()` — no unsafe pattern, continues.
4. `scope.check()` — plain Class 3 multiplication, in scope, continues.
5. `conversation_resolver.resolve_question()` — the deterministic "X instead of Y" rule fires
   with zero LLM call, resolving to "what is 5 times 3?", `mode=MATH_FOLLOWUP`.
6. `scripts.retrieval.retrieve_with_metadata("what is 5 times 3?", grade=3)` — hybrid
   BM25+ChromaDB, grade window {2,3}, top 3 multiplication-topic chunks.
7. `pipeline.compute_trusted_answer()` → `verifier.solve_with_type()` — the numeric path parses
   `5*3`, SymPy evaluates to `15` exactly, grade-appropriate (an integer, always injected).
8. `episode._advance_math_followup()` recognizes this as a *new* sub-problem derived from the
   previous one and calls `controller.start_followup()`, which opens a fresh `TutorState`
   (its own attempt/hint budget) but with a directive that explicitly names the connection to
   the previous problem, instead of silently pretending nothing came before.
9. `prompt_registry.build_messages()` assembles: `PERSONALIZED_SYSTEM` + this student's
   `LEVEL_STYLE` (say, `intermediate`, from `pipeline.resolve_level()`) +
   `memory.thread_summary()` if any earlier episodes exist this session + the prior turns of
   *this* episode + the controller's directive appended to the final user message. Note what's
   *not* here: `pipeline.generate_turn()` only passes `computed_answer` into the prompt for
   `MODE_CO_SOLVE`/`MODE_REVEAL` — for this `teach_invite` turn the model is never told the
   trusted value "15" at all, not even with an instruction to keep it secret. `state.computed_answer`
   exists purely for the *controller's* own grading of the child's next reply; genuine withholding,
   not a polite request the model could slip up on.
10. `llm_client.stream()` tries Groq first; it responds, so HF is never touched. Text streams to
    the UI live.
11. `response_parser.strip_latex()` + `collapse_excess_blank_lines()` clean the raw text before
    it's stored or displayed.
12. This is a `teach_invite` turn (answer withheld), so `_post_check()` only runs the bounded
    self-consistency guardrail, not a strict numeric check — nothing to check the model's
    *stated* answer against yet, since it hasn't been asked to state one.
13. The child replies "15". `controller.step()` with intent `ATTEMPT` calls `diagnose()`,
    compares `15` against the trusted `15`, mode becomes `diagnose_correct`, terminal, outcome
    `solved`.
14. `_record_outcome()` calls `record_feedback()` → `student_tracker.record(student_id,
    topic="Multiplication", correct=True)` — written to `data/students.json`, updating the
    rolling 5-attempt window `pipeline.resolve_level()` will read on this student's *next* turn.
15. `common.log_run()` appends the full generation record to `data/llm_runs.jsonl`;
    `telemetry.log_interaction()` appends the compact per-turn record to
    `data/interaction_events.jsonl`.
16. `memory.add_note()` appends a one-line thread note ("asked 'what is 5 times 3?' · solved it
    · 0 hints") to this session's thread, capped at the 5 most recent.
17. `main_page.py` renders the reply with a green verify-tag, the NCERT citation, updates the
    badge/progress panel, and — since this was a genuine graded attempt — the "Questions
    Answered"/"Stars" counters.

---

## 8. `data/` — what's there and why

| Path | Tracked? | Contents |
|---|---|---|
| `extracted_json/ncert_chunks.json` | **Yes** | The full corpus — 2,329 chunks, `{text, grade, page, source}`. Everything retrieval runs against. Rebuild with `parse_ncert.py` if the source PDFs change. |
| `eval_baseline_vs_system.json` | **Yes** | A 36-item baseline-vs-system comparison from an early evaluation pass, kept for traceability. Superseded by the full evaluation in §9. |
| `raw_pdfs/` | No (gitignored) | The five source PDFs — not unique to any machine, download from [NCERT Classes 1-5](https://drive.google.com/drive/folders/1DBPLkxJh6Y6-zJNLeopLxnYEaSN2AV_T?usp=sharing). |
| `chromadb/` | No (gitignored) | The persistent vector index — fully regenerable from `ncert_chunks.json` via `load_chromadb.py`. |
| `llm_runs.jsonl` | No (gitignored) | Every generation call ever made locally, growing continuously. The pilot latency figures (§9) come from a fixed date window of this file (20 July – 22 August 2026, 266 tutoring calls). |
| `interaction_events.jsonl` | No (gitignored) | Per-turn structured telemetry — useful as live ground truth when debugging (distinguishes "the app did X" from "the test harness thinks it did X"), not meant to be shared via git. |
| `students.json` | No (gitignored) | Per-student personalization state (`student_tracker`'s store) — real runtime data, not source material; was tracked early on but untracked once established it was perpetually-dirty local state, not a feature artifact. |

---

## 9. Evaluation (`eval/`)

### 9.1 Design

The evaluation compares two tutors on the same items, paired item by item, with the **same
model and sampling settings** (`openai/gpt-oss-120b` on Groq, temperature 0.3), so differences
come from the architecture, not the model:

- **Baseline** (`eval/baseline_runner.py`, tag `paper-eval-v1`): one plain tutor instruction plus
  the conversation — no retrieval, verifier, controller or scope gate.
- **TinyThinker** (`eval/system_runner.py`, tag `paper-eval-v2`): the app's own turn function,
  `frontend.episode.submit_turn`, unchanged.

On single-turn items TinyThinker's first reply teaches and invites an attempt, so the harness
sends a fixed give-up message as a second turn and scores its final answer there; the baseline
answers once. First-reply measures use each side's first reply.

| Set (`eval/datasets/`) | Items | Tests |
|---|---|---|
| `curriculum_benchmark_class1..5` | 935 (577 with one checkable answer) | correctness and teaching across 9 question types |
| `out_of_scope` | 277 | the Class 1–5 boundary in both directions |
| `multi_turn` | 206 conversations, 666 scored turns | the controller over whole conversations |
| `held_out_*` | 30 openers, 20 ambiguous/everyday, 50 out-of-scope | unseen phrasing, written after the system was frozen |
| `svamp` | items 1–500 of 1,000 | external word problems |
| `mathdial_sample` | 100 | the reply to a child's wrong working |
| `retrieval` | 100 queries (88 with labelled pages) | retrieval quality |

**Raters.** An LLM judge (`qwen/qwen3.8-27b`, a different model family, blind to condition) and
two members of the team, who rated a 150-row blind sheet and a 50-row MathDial sheet. The judge
is trusted only where it agreed with the team members (correctness, grade fit, MathDial mistake
identification); its clarity, restraint and guidance scores are exploratory and its
hallucination flags are not used.

**Answer scoring** (`eval/answer_extraction.py`, `eval/score_transcripts.py`,
`eval/paper_metrics.final_correct`). Correctness is decided in code against each item's
re-verified ground truth, from the answer the reply commits to (an "Answer:" line, a concluding
sentence, or the last bold phrase), reading the model's raw text with LaTeX converted. Where the
rules find no answer or a wrong one, the judge's separate reading of the committed answer is also
checked against the ground truth — for both conditions alike. Yes/no misconception questions
carry an `expected_yes_no` label and are scored on it.

**Statistics.** Wilson intervals; exact McNemar tests and Newcombe paired intervals; discordant
odds ratios and Cohen's g; Wilcoxon signed-rank tests with Holm correction and rank-biserial
effect sizes; Cohen's κ, Gwet's AC1 and Krippendorff's α for agreement.

### 9.2 Results (baseline vs TinyThinker)

| Measure | Baseline | TinyThinker | p |
|---|---|---|---|
| Curriculum final answers correct (577) | 99.0% | 99.5% | 0.375 |
| SVAMP final answers correct (500) | 95.4% | 94.8% | 0.581 |
| Out-of-scope questions handled correctly (277) | 22.0% | 98.2% | < 0.001 |
| In-scope questions wrongly refused (1,495) | 0.0% | 0.9% | — |
| First reply gives the answer away | 97.2% | 4.0% | — |
| First reply invites the child to try | 6.2% | 85.2% | — |
| MathDial: hands over the answer | 81% | 11% | < 0.001 |
| MathDial: names the mistake outright | 90% | 14% | < 0.001 |
| Grade fit, two team members (1–5) | 3.99 | 4.77 | < 0.001 |
| Hallucination flagged by both team members | 2.7% | 4.0% | 1.000 |

Correctness is the same in both conditions. What changes is the tutoring: TinyThinker keeps to
the Class 1–5 syllabus, withholds the answer and invites the child to try, and its replies fit
the child's class better. On a child's own wrong working the two show different styles — the
baseline names the error but hands over the answer; TinyThinker re-teaches and withholds but
rarely points at the slip. There is no measurable difference in hallucination.

Components: retrieval Hit@3 0.92, nDCG@3 0.71, no cross-class leakage (without the class filter
nDCG@3 falls to 0.48); the verifier gives a trusted value on 88.5% of checkable curriculum
questions and is right 99.2% of the time; the controller takes the expected action on 84.2% of
turns (macro-F1 0.73); median reply 2.3 s vs 1.0 s on SVAMP (1.28 s in the pilot interaction
log). Main limitations: no learners took part, the human raters are the builders, one generator
model, and in-house datasets.

### 9.3 Reproducing the numbers

```bash
python -m eval.paper_metrics          # headline metrics -> eval/results/paper_metrics_*.json/.md
python -m eval.extra_metrics          # standard extra measures -> eval/results/extra_metrics_*
python -m eval.retrieval_ablation     # retrieval measures and variants (local only)
python -m eval.make_paper_outputs     # paper/tables/*.tex, paper/figures/*
python -m eval.make_extra_outputs     # paper/tables/extra/*, paper/figures/extra/*
```

None of these makes an API call; they read the saved transcripts (`eval/results/baseline_runs/`,
`eval/results/system_runs_v2/`), judge verdicts (`eval/results/judge_runs/`) and ratings
(`eval/blind_ratings/`). `paper/README.md` maps every table and figure to the file it reads;
every result file name carries the commit it was built from.

### 9.4 Other evaluation code

`eval/controller_walk.py` and `eval/validate_datasets.py` are part of the standard test run above.
An earlier framework (`eval/component_eval/*`, `eval/run_eval.py`, `eval/eval_set.py`) predates the
controller-driven generation path; its retrieval, arithmetic, controller and personalization
checks still feed the components table, and the rest is kept for traceability.
`eval/reference_v1_vs_v2.py` compares the system's development run with the frozen system for the
team's reference only; no paper table or figure uses it.

The evaluation datasets were generated with AI assistance (Claude) and every item was reviewed
by hand by the project team.

Class 5 percentages are treated as in scope even though the NCERT textbooks don't cover them
(see "Additions beyond the NCERT textbooks" in `docs/verified_ncert_class_1_5_topics.md`), so
the eight percentage items in `eval/datasets/out_of_scope.jsonl` (oos-092 to oos-099) are
in-scope probes that must be answered, not refused. They were relabelled after the
`paper-eval-v1` run; baseline and system are scored against the same labels.

---

## 10. Dependencies

```
PyMuPDF            PDF text extraction (parse_ncert.py)
chromadb           persistent vector store
sentence-transformers   all-MiniLM-L6-v2 embeddings
rank-bm25          lexical retrieval
openai             OpenAI-compatible client, used for both Groq and the HF router
python-dotenv      loads GROQ_API_KEY / HF_TOKEN from .env
sympy              exact-rational arithmetic verification
streamlit          the student-facing app
pandas             analysis/eval tooling
```

```bash
pip install -r requirements.txt
```
