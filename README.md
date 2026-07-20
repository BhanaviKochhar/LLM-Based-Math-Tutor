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
│  Hybrid retrieval   │────▶│  Prompt assembly    │
│  BM25 + ChromaDB    │     │  system + context +  │
│  (top-3 chunks)     │     │  question            │
└─────────────────────┘     └──────────┬───────────┘
                                       ▼
                            ┌──────────────────────┐
                            │  LLM generation      │
                            │  (gpt-oss-120b /     │
                            │   llama3.3-70b /     │
                            │   qwen3-32b via HF   │
                            │   Inference Providers)│
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
    common.py               # shared API client, provider fallback, logging
    prompt.py               # prompt templates (versioned)
    gpt_oss.py              # model file: gpt-oss-120b
    llama33.py              # model file: Llama-3.3-70B-Instruct
    qwen3.py                # model file: Qwen3-32B
    run_test.py             # end-to-end RAG test across all models
test_integration.py         # verifies retrieve() matches the team contract
requirements.txt
.env                        # your API tokens (never commit)
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
HF_TOKEN=hf_your_token_here
```

- Get a token at https://huggingface.co/settings/tokens (read access is enough).
- No quotes, no spaces around `=`.
- `.env` is gitignored. Never commit tokens.

---

## 3. Data ingestion pipeline

### 3.1 Download the textbook PDFs

Download the NCERT mathematics PDFs for Classes 1–5: [NCERT Classes 1-5](https://drive.google.com/drive/folders/1DBPLkxJh6Y6-zJNLeopLxnYEaSN2AV_T?usp=sharing)

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

### 5.1 Models

| Registry name | Model | Providers (fallback order) |
|---|---|---|
| `gpt-oss-120b` | openai/gpt-oss-120b | groq → nscale → deepinfra |
| `llama3.3-70b` | meta-llama/Llama-3.3-70B-Instruct | groq → novita → featherless-ai → scaleway |
| `qwen3-32b` | Qwen/Qwen3-32B | groq → nscale → deepinfra |

All are reached through the **Hugging Face Inference Providers router**
(`https://router.huggingface.co/v1`), which speaks the OpenAI
chat-completions format. One token, one client, many providers.

### 5.2 Architecture (`scripts/llm/`)

- **`common.py`** — creates the OpenAI-compatible client, tries each
  provider in order with retries, returns a structured result dict
  (text, provider used, latency, token counts, error), and appends every
  run to `data/llm_runs.jsonl`.
- **`prompt.py`** — builds the messages list from
  `(question, grade, chunks)`. The system prompt instructs the model to
  act as a friendly tutor, use ONLY the provided context, explain step by
  step at the student's level, and refuse gracefully when the context is
  insufficient. `PROMPT_VERSION` is logged with every run — bump it when
  the wording changes.
- **One file per model** (`gpt_oss.py`, `llama33.py`, `qwen3.py`) — each
  defines its `MODEL_ID`, `PROVIDERS`, `PARAMS` and exposes the same
  interface:

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
built and `HF_TOKEN` set):

```bash
python -m scripts.llm.run_test
```

### 5.5 Run logs

Every generation appends one self-contained JSON line to
`data/llm_runs.jsonl`: timestamp, model, question, grade, the exact
chunks and rendered messages, parameters, provider actually used,
output text, latency, and token counts. This makes every experiment
reproducible and comparable.

Inspect with pandas:

```python
import pandas as pd
df = pd.read_json("data/llm_runs.jsonl", lines=True)
```

---

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Set the HF_TOKEN environment variable` | `.env` missing/misnamed, or variable not named `HF_TOKEN` exactly. |
| ChromaDB `collection not found` | Run `python scripts/load_chromadb.py` to build the local index. |
| `402 ... depleted your monthly included credits` | HF free inference credits exhausted for the month. Use a direct provider key (e.g. Groq free tier) or wait for the monthly reset. |
| Provider errors for one model only | Check the `PROVIDERS` list in that model's file; provider slugs must match HF's router. |
| Llama 403 / gated error | Accept the Llama license on the model's Hugging Face page with the same account as the token. |
| Import errors when running scripts | Run module-style from the project root: `python -m scripts.llm.run_test`. |

---

## 7. Project status & roadmap

- [x] PDF parsing and chunking (fitz)
- [x] ChromaDB + BM25 hybrid retrieval with grade filtering
- [x] Retrieval evaluation (keyword-based)
- [x] LLM integration: 3 models, provider fallback, full run logging
- [ ] Docling parsing comparison (in progress, `docling_experiment` branch)
- [ ] Prompt engineering with real prompt versions (v2, v3, …)
- [ ] Parameter tuning per model
- [ ] Model comparison experiments and final selection
- [ ] Student-facing interface (Streamlit)
