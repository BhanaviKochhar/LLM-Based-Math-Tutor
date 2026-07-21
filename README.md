# LLM-Based Math Tutor (NCERT Classes 1–5)

A Retrieval-Augmented Generation (RAG) tutoring system. A student asks a
mathematics question, the system retrieves relevant passages from NCERT
Class 1–5 textbooks, and an LLM generates a grade-appropriate, step-by-step
answer grounded in that retrieved content.

```
Student question + grade
        │
        ▼
┌─────────────────────┐     ┌──────────────────────┐
│  Hybrid retrieval   │────▶│  Prompt assembly     │
│  BM25 + ChromaDB    │     │  system + context +  │
│  (top-3 chunks)     │     │  question            │
└─────────────────────┘     └──────────┬───────────┘
                                       ▼
                            ┌──────────────────────┐
                            │  LLM generation      │
                            │  (gpt-oss-120b /     │
                            │   llama3.3-70b /     │
                            │   qwen3-32b via      │
                            │   Groq direct + HF   │
                            │   router fallback)   │
                            └──────────┬───────────┘
                                       ▼
                            Tutor answer + JSONL run log
```

---

## 1. Repository layout

```
data/
  raw_pdfs/                 # NCERT textbook PDFs (not in git — see §3)
  extracted_json/
    ncert_chunks.json       # parsed chunks (output of parse_ncert.py)
  chromadb/                 # persistent vector store (not in git; built locally)
  eval_report.json          # retrieval evaluation output
  llm_runs.jsonl            # generation logs (not in git)
scripts/
  parse_ncert.py            # PDF → text chunks
  load_chromadb.py          # chunks → embeddings → ChromaDB
  retrieval.py              # hybrid retrieval (the team contract)
  eval_retrieval.py         # keyword-based retrieval evaluation
  llm/
    common.py               # shared client, backend fallback, logging
    prompt.py               # prompt templates (versioned)
    gpt_oss.py              # model file: gpt-oss-120b
    llama33.py              # model file: Llama-3.3-70B-Instruct
    qwen3.py                # model file: Qwen3-32B
    run_test.py             # end-to-end RAG test across all models
test_integration.py         # verifies retrieve() matches the team contract
requirements.txt
.env                        # your API keys (never commit)
.gitignore
```

---

## 2. Setup

Requires Python 3.10+.

```bash
git clone <repo-url>
cd LLM-Based-Math-Tutor
python -m venv venv
source venv/bin/activate          # Windows Git Bash: source venv/Scripts/activate
pip install -r requirements.txt
```

Create a `.env` file at the project root:

```
GROQ_API_KEY=gsk_your_key_here
HF_TOKEN=hf_your_token_here
```

- Groq key: https://console.groq.com → API Keys (free tier with daily limits).
- HF token: https://huggingface.co/settings/tokens (read access is enough).
- No quotes, no spaces around `=`. `.env` is gitignored. Never commit keys.
- You need at least one of the two; backends whose key is missing are
  skipped automatically.

---

## 3. Data ingestion pipeline

### 3.1 Download the textbook PDFs

Download the NCERT mathematics PDFs for Classes 1–5:
[NCERT Classes 1-5](https://drive.google.com/drive/folders/1DBPLkxJh6Y6-zJNLeopLxnYEaSN2AV_T?usp=sharing)

Place them as:

```
data/raw_pdfs/class1.pdf
data/raw_pdfs/class2.pdf
data/raw_pdfs/class3.pdf
data/raw_pdfs/class4.pdf
data/raw_pdfs/class5.pdf
```

### 3.2 Parse PDFs into chunks

```bash
python scripts/parse_ncert.py
```

What it does:
- Opens each `classN.pdf` with PyMuPDF (`fitz`).
- Extracts text page by page, dropping page numbers and very short lines.
- Splits text into sentences and groups them **3 sentences per chunk**
  (minimum 50 characters), preserving `grade` and `page` metadata.
- Writes all chunks to `data/extracted_json/ncert_chunks.json`.

Output format (one entry per chunk):

```json
{"text": "...", "grade": 3, "page": 42, "source": "NCERT"}
```

Current corpus: ~2,329 chunks across the five books.

### 3.3 Build the vector store

```bash
python scripts/load_chromadb.py
```

What it does:
- Loads `ncert_chunks.json`.
- Deletes any existing `ncert_math` collection (safe full rebuild).
- Embeds every chunk with `sentence-transformers/all-MiniLM-L6-v2`
  (384-dim embeddings, runs on CPU).
- Inserts documents + embeddings + metadata into a **persistent ChromaDB**
  store at `data/chromadb/` in batches of 100.

Note: `data/chromadb/` is gitignored, so **every machine builds its own
index** by running this script once. Rerun it whenever
`ncert_chunks.json` changes.

---

## 4. Retrieval

### 4.1 How it works (`scripts/retrieval.py`)

Hybrid retrieval combining two complementary signals:

1. **BM25 (lexical)** via `rank_bm25` — exact word matching, good for
   terms like "perimeter" or "borrowing".
2. **Dense semantic search** via ChromaDB — meaning-based matching, good
   when the student's wording differs from the textbook's.

Both retrievers fetch 20 candidates each, restricted to a **grade window**
of `{grade-1, grade}` (a Class 3 question may also use Class 2 content as
prerequisite knowledge). The two rankings are merged with **Reciprocal
Rank Fusion** (k=60) and the top 3 chunks are returned.

### 4.2 The team contract

```python
from scripts.retrieval import retrieve

chunks = retrieve("How do I subtract with borrowing?", grade=3)
# -> list of exactly 3 chunk strings
```

`retrieve_with_metadata(...)` returns the same ranking as full dicts
(grade/page/topic/type) for debugging and evaluation.

### 4.3 Verify retrieval

```bash
python -u scripts/retrieval.py        # smoke test, 3 sample questions
python test_integration.py            # contract check (3 non-empty strings)
python -u scripts/eval_retrieval.py   # keyword-based eval, 20 questions
```

The evaluation reports a keyword hit-rate per class and a grade-filter
accuracy (must be 100%), and writes `data/eval_report.json` with any weak
retrievals to fix.

---

## 5. LLM generation

### 5.1 Models and backends

Every API used here speaks the **OpenAI chat-completions format**, so one
client library covers all of them. Each model declares a list of
**backends** (endpoint + key + model id) tried in order until one succeeds:

| Model file | Model | Backend order |
|---|---|---|
| `gpt_oss.py` | gpt-oss-120b | Groq direct → HF router (groq) → HF router (nscale) |
| `llama33.py` | Llama-3.3-70B-Instruct | Groq direct¹ → HF router (groq) → HF router (novita) |
| `qwen3.py` | Qwen3-32B | Groq direct¹ → HF router (nscale) → HF router (deepinfra) |

¹ **Deprecation notice (June 2026):** Groq has deprecated
`llama-3.3-70b-versatile` and `qwen/qwen3-32b` on free/developer tiers —
these entries may stop working; the code then falls back to the HF router
automatically. Check https://console.groq.com/docs/deprecations for
shutdown dates. Only `openai/gpt-oss-120b` is a long-term Groq resident.

Endpoints:
- **Groq direct** — `https://api.groq.com/openai/v1`, key `GROQ_API_KEY`.
  Free tier with per-model daily limits (e.g. gpt-oss-120b: 1K requests /
  200K tokens per day).
- **HF Inference Providers router** — `https://router.huggingface.co/v1`,
  key `HF_TOKEN`, model strings like `Qwen/Qwen3-32B:nscale`. Free monthly
  credits are very small and exhaust quickly.

### 5.2 Architecture (`scripts/llm/`)

- **`common.py`** — cached OpenAI-compatible clients per endpoint, walks
  each model's `BACKENDS` list with retries, returns a structured result
  dict (text, backend used, latency, token counts, error), and appends
  every run to `data/llm_runs.jsonl`. Backends with missing keys are
  skipped, never crash.
- **`prompt.py`** — builds the messages list from
  `(question, grade, chunks)`. The system prompt instructs the model to
  act as a friendly tutor, use ONLY the provided context, explain step by
  step at the student's level, and refuse gracefully when the context is
  insufficient. `PROMPT_VERSION` is logged with every run — bump it when
  the wording changes.
- **One file per model** — each defines `MODEL_NAME`, `PARAMS`,
  `BACKENDS` and exposes the same interface:

```python
generate(question: str, grade: int, chunks: list[str]) -> str
```

  So the full pipeline is one line:

```python
answer = gpt_oss.generate(q, g, retrieve(q, g))
```

  `qwen3.py` additionally disables Qwen's thinking mode (`/no_think`) and
  strips any `<think>...</think>` block from the output.

### 5.3 Generation parameters

All models currently use standard RAG-tutoring values:
`temperature=0.3`, `top_p=0.9`, `max_tokens=1024`. Parameter tuning is a
later phase; edit `PARAMS` in the individual model file to experiment.

### 5.4 Run the models

Quick single-model check (hand-made chunk, no retrieval needed):

```bash
python -c "
from scripts.llm import gpt_oss
print(gpt_oss.generate('What is 2 + 3?', 1, ['Adding means putting together. 2 and 3 make 5.']))
"
```

Full RAG round-trip through all three models (needs `data/chromadb`
built and at least one API key set):

```bash
python -m scripts.llm.run_test
```

### 5.5 Run logs

Every generation appends one self-contained JSON line to
`data/llm_runs.jsonl`: timestamp, model, question, grade, the exact
chunks and rendered messages, parameters, backend actually used,
output text, latency, and token counts. This makes every experiment
reproducible and comparable.

Inspect with pandas:

```python
import pandas as pd
df = pd.read_json("data/llm_runs.jsonl", lines=True)
```

---

## 6. Integrating a new model or backend

The generation layer is designed so that adding a model touches **one new
file**, and adding a backend to an existing model touches **one list**.

### 6.1 Adding a new backend to an existing model

Use this when a model becomes available on another service (e.g. Cerebras,
OpenRouter, a local vLLM/Ollama server).

1. **Confirm the service is OpenAI-compatible** — it must expose a
   `/chat/completions` endpoint. Almost all inference services do
   (Groq, Cerebras, OpenRouter, Together, DeepInfra, vLLM, Ollama).
2. **Find the exact model id in the provider's own console/docs.** Ids
   differ per provider for the same model (HF: `Qwen/Qwen3-32B`; Groq:
   `qwen/qwen3-32b`; others differ again). Never guess.
3. **Add the base URL as a constant in `common.py`**, e.g.
   `CEREBRAS_URL = "https://api.cerebras.ai/v1"`.
4. **Add the key to `.env`**, e.g. `CEREBRAS_API_KEY=...`.
5. **Append a dict to the model file's `BACKENDS` list** at the desired
   priority position:

```python
{"name": "cerebras", "base_url": common.CEREBRAS_URL,
 "key_env": "CEREBRAS_API_KEY", "model": "llama-3.3-70b"},
```

6. **Verify** with the cheap single call from §5.4 and confirm the log
   record shows `"backend": "cerebras"`.

### 6.2 Adding a completely new model

1. **Screen it first** against the project's research criteria
   (open access, hosted API with a usable free route, math capability,
   instruction following, sufficient context window, suitable license).
2. **Copy the closest existing model file** (`gpt_oss.py` for a plain
   model, `qwen3.py` for a thinking/reasoning model) to a new file,
   e.g. `scripts/llm/mistral_small.py`.
3. **Edit the four things**: `MODEL_NAME` (your registry name, used in
   logs), `PARAMS`, `BACKENDS` (per §6.1), and any model-specific
   post-processing.
4. **Handle quirks explicitly.** Common ones:
   - *Thinking/reasoning models* — may emit `<think>...</think>` or
     similar. Strip it (see `qwen3.py`) or disable via the model's
     documented switch; a child must never see raw reasoning.
   - *Gated models* — accept the license on the model's HF page with the
     same account as your token, or the API returns 403.
   - *Chat-template sensitivity* — some models need the system prompt
     merged into the user turn; test with the §5.4 cheap call first.
5. **Register it in `run_test.py`** by importing it and adding it to the
   `MODELS` list.
6. **Run the ladder**: cheap call → full `run_test` → inspect the JSONL
   log for latency, token counts, and output quality.
7. Keep `generate(question, grade, chunks) -> str` as the signature —
   that is the contract the rest of the pipeline (and future UI) relies on.

### 6.3 Limitations of the current integration layer

Know these before integrating something exotic:

- **OpenAI-compatible chat endpoints only.** Services with proprietary
  request formats (e.g. some cloud vendors' native APIs) need either
  their OpenAI-compat shim or a custom code path in `common.py`.
- **No streaming.** Responses arrive complete; fine for logging and
  evaluation, but a future UI wanting token-by-token display will need a
  streaming variant of `chat()`.
- **Text in, text out.** No image/audio inputs, no tool calling, no
  structured-output enforcement (JSON mode) — not needed for the tutor
  yet, and not wired up.
- **Sequential fallback.** Backends are tried one after another with
  retries and linear backoff; a fully-down first backend adds a few
  seconds of latency before the fallback answers. Reorder `BACKENDS` if
  a backend is known-dead.
- **Fallback changes the model string, not the model.** All backends in
  one file must point at the *same underlying model*, otherwise your
  logs silently mix models and comparisons become invalid.
- **Free tiers are volatile.** Provider model lineups, ids, quotas, and
  deprecations change monthly (see the Groq note in §5.1). Verify in the
  provider console on the day you integrate, and record the date.
- **Rate limits are not handled specially.** A 429 is retried like any
  error and then falls through to the next backend. Batch experiments
  should stay within the smallest daily quota among the backends used.
- **Logs store full prompts and outputs.** Useful for research; mind the
  file size over many runs, and keep `llm_runs.jsonl` out of git.

---

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `skipped (GROQ_API_KEY not set)` in error | Key missing from `.env`, or `.env` not at project root / misnamed. |
| ChromaDB `collection not found` | Run `python scripts/load_chromadb.py` to build the local index. |
| `402 ... depleted your monthly included credits` | HF free credits exhausted for the month. Groq-direct backends still work; or wait for reset. |
| `model_decommissioned` / deprecated-model error | The provider retired that model id (see §5.1). Remove or reorder that backend entry. |
| Errors for one model only | Check the `BACKENDS` model ids in that model's file against the provider console. |
| Llama 403 / gated error on HF | Accept the Llama license on the model's HF page with the same account as the token. |
| Import errors when running scripts | Run module-style from the project root: `python -m scripts.llm.run_test`. |

---

## 8. Project status & roadmap

- [x] PDF parsing and chunking (fitz)
- [x] ChromaDB + BM25 hybrid retrieval with grade filtering
- [x] Retrieval evaluation (keyword-based)
- [x] LLM integration: 3 models, multi-backend fallback, full run logging
- [ ] Docling parsing comparison (in progress, `docling_experiment` branch)
- [ ] Prompt engineering with real prompt versions (v2, v3, …)
- [ ] Parameter tuning per model
- [ ] Model comparison experiments and final selection
- [ ] Student-facing interface (Streamlit)