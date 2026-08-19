# LLM-Based Math Tutor — MVP

A Retrieval-Augmented Generation (RAG) maths tutor for NCERT Classes 1–5. The MVP combines the team's retrieval, model-integration, prompt-engineering, verification, tutoring-control, memory, and Streamlit work into one student-facing application.

## 1. Quick start

### Requirements

- Python **3.10+**
- Internet access for LLM inference
- A Hugging Face token and/or Groq API key
- The five NCERT mathematics PDFs

Install dependencies:

```bash
git clone <repo-url>
cd LLM-Based-Math-Tutor

python -m venv venv
# Windows Git Bash:
source venv/Scripts/activate
# macOS/Linux:
# source venv/bin/activate

pip install -r requirements.txt
```

Create `.env` in the project root:

```env
HF_TOKEN=hf_your_token_here
GROQ_API_KEY=your_groq_key_here
```

At least one of the two keys should be available. The MVP tries Groq first and then Hugging Face Inference Provider fallbacks.

> Never commit `.env` or API keys.

## 2. Get the NCERT data

Download the Class 1–5 NCERT mathematics PDFs:

**NCERT Classes 1–5:**  
https://drive.google.com/drive/folders/1DBPLkxJh6Y6-zJNLeopLxnYEaSN2AV_T?usp=sharing

Place them exactly here:

```text
data/
└── raw_pdfs/
    ├── class1.pdf
    ├── class2.pdf
    ├── class3.pdf
    ├── class4.pdf
    └── class5.pdf
```

These PDFs are not committed to the repository.

## 3. Build the local knowledge base

Run these once from the **repository root**:

```bash
python scripts/parse_ncert.py
python scripts/load_chromadb.py
```

### What happens

```text
NCERT PDFs
   ↓
PyMuPDF / fitz
   ↓
cleaned text
   ↓
~3-sentence chunks + grade/page metadata
   ↓
data/extracted_json/ncert_chunks.json
   ↓
all-MiniLM-L6-v2 embeddings
   ↓
persistent ChromaDB
data/chromadb/
```

`parse_ncert.py` reads `data/raw_pdfs/class1.pdf` through `class5.pdf`, extracts text page-by-page, removes short/page-number-like lines, groups sentences into chunks, and writes the chunk JSON.

`load_chromadb.py` embeds those chunks with `sentence-transformers/all-MiniLM-L6-v2` and rebuilds the `ncert_math` ChromaDB collection in batches.

> Re-run both scripts if the source PDFs or chunking logic changes. The local `data/chromadb/` directory is generated data and is not committed.

## 4. Run the MVP

Make sure you are in the **repository root** and the virtual environment is activated.

### Start the application

```bash
streamlit run frontend/app.py
```

Streamlit will start a local server and print a URL similar to:

```text
Local URL: http://localhost:8501
Network URL: http://192.168.x.x:8501
```

Open the **Local URL** in your browser.

### Complete run sequence

For a fresh setup, the complete sequence is:

```bash
# 1. Clone and enter the repository
git clone <repo-url>
cd LLM-Based-Math-Tutor

# 2. Create and activate virtual environment
python -m venv venv
source venv/Scripts/activate          # Windows Git Bash
# source venv/bin/activate            # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Add API key(s) to .env
# HF_TOKEN=...
# GROQ_API_KEY=...

# 5. Add NCERT PDFs to data/raw_pdfs/

# 6. Build the chunked knowledge base
python scripts/parse_ncert.py

# 7. Build the local ChromaDB index
python scripts/load_chromadb.py

# 8. Optional: test retrieval
python -u scripts/retrieval.py

# 9. Start the application
streamlit run frontend/app.py
```

For subsequent runs, once the knowledge base has already been built, you normally only need:

```bash
cd LLM-Based-Math-Tutor
source venv/Scripts/activate       # Windows Git Bash
streamlit run frontend/app.py
```

If the PDFs or chunking logic change, rebuild the knowledge base:

```bash
python scripts/parse_ncert.py
python scripts/load_chromadb.py
```

To stop the Streamlit server, press:

```text
Ctrl + C
```

`frontend/app.py` is the UI layer. It does not implement retrieval or LLM logic itself; it calls the backend in `scripts/llm/`.

The current frontend has:

```python
MOCK_MODE = False
```

so the real backend is used.

## 5. How the MVP works

### High-level flow

```text
Student
  │
  ▼
Streamlit frontend
frontend/app.py
  │
  ▼
pipeline.prepare()
  │
  ├──────────────► Retrieval
  │                 │
  │                 ├─ BM25
  │                 └─ ChromaDB dense search
  │                       ↓
  │                    RRF fusion
  │                       ↓
  │                    top 3 chunks
  │
  ├──────────────► Compute-first verifier
  │                 │
  │                 └─ safe expression → SymPy
  │
  ▼
Prompt construction
prompt_registry.py
  │
  ├─ retrieved NCERT context
  ├─ question + grade
  ├─ student level
  ├─ trusted computed answer when applicable
  ├─ conversation memory
  └─ controller directive
  │
  ▼
LLM client
llm_client.py
  │
  ├─ Groq direct
  └─ Hugging Face router fallbacks
  │
  ▼
streamed tutor response
  │
  ▼
Streamlit UI
```

## 6. Retrieval

`scripts/retrieval.py` is the retrieval layer used by the MVP.

It combines:

1. **BM25** — lexical retrieval; useful when the student's wording contains textbook terms.
2. **ChromaDB** — dense semantic retrieval; useful when the student's wording differs from the textbook wording.
3. **Reciprocal Rank Fusion (RRF)** — combines both rankings.
4. **Grade filtering** — searches the current grade and one grade below where applicable.

Configuration:

```text
20 BM25 candidates
+ 20 dense candidates
→ RRF (k=60)
→ top 3 chunks
```

The public contract is:

```python
retrieve(question, grade)
# -> list[str] containing the top 3 chunk texts
```

The metadata version is used by the backend when source information is needed.

## 7. Backend orchestration

`scripts/llm/pipeline.py` is the main backend entry point.

### `prepare()`

For a new question it:

1. Resolves the student's level.
2. Retrieves the relevant NCERT chunks.
3. Runs the compute-first verifier.
4. Builds the prompt/messages.
5. Returns a `TutorTurn`.

Generation is deliberately deferred until the turn is streamed.

### Three verifier states

```text
INJECTED
  computable + grade-appropriate result
  → trusted result injected
  → strict post-generation verification

REMAINDER
  mathematical question but decimal-style injection is inappropriate
  → teach the grade-appropriate remainder form
  → skip strict numerical mismatch check

CONCEPTUAL
  not a computable arithmetic expression
  → explain using retrieved context
  → no numerical verification
```

## 8. Prompting + tutoring logic

The MVP uses `scripts/llm/prompt_registry.py`.

The prompt is no longer just a single static instruction. The controller first decides **what the tutor should do**, then the appropriate directive is incorporated into the prompt.

The tutoring controller is in:

```text
scripts/llm/controller.py
```

Typical actions include:

```text
ATTEMPT
HINT
SOLVE / REVEAL
GIVE_UP / CO-SOLVE
NEW_QUESTION
```

This separates:

- **controller** → tutoring policy/state
- **prompt registry** → instructions for the selected action
- **LLM** → natural-language generation

The MVP also passes student level, retrieved context, memory, and—when appropriate—a trusted computed answer into prompt construction.

## 9. Mathematical verification

`scripts/llm/verifier.py` provides the compute-first path.

For supported arithmetic:

```text
Question
  ↓
expression extraction
  ↓
safe validation
  ↓
SymPy computation
  ↓
trusted result
  ↓
LLM explains the result
```

The system does not directly `eval()` arbitrary model output.

When a trusted answer is injected, the generated response can also be checked against that trusted value after generation.

## 10. LLM generation

`scripts/llm/llm_client.py` is the shared streaming client.

The MVP currently defaults to:

```text
openai/gpt-oss-120b
```

The client uses an OpenAI-compatible interface.

Target order:

```text
1. Groq direct
2. Hugging Face router → nscale
3. Hugging Face router → deepinfra
```

Fallback happens **only before the first token**. Once a provider has started streaming, the response stays with that provider so the UI does not receive a partially duplicated/corrupted answer.

Default generation parameters:

```text
temperature = 0.3
top_p       = 0.9
max_tokens  = 1024
frequency_penalty = 0.3
```

## 11. Memory and personalization

### Memory

`scripts/llm/memory.py` separates:

- **active episode memory** — detailed context for the current problem
- **thread memory** — a bounded amount of information from earlier episodes

The history is intentionally bounded to avoid unnecessary prompt growth and noise.

### Student level

`scripts/llm/student_tracker.py` records performance and can classify the student's recent level.

The pipeline maps UI tracks to:

```text
needs_practice → beginner
on_track      → intermediate
ahead         → advanced
```

Once enough recent attempts exist, the tracker can override the UI level using recent performance.

## 12. Intent and hints

`scripts/llm/intent.py` handles conversational intent such as:

```text
ATTEMPT
HINT
SOLVE
GIVE_UP
NEW_QUESTION
```

The system uses a layered approach:

```text
deterministic checks
      ↓ unresolved
LLM classifier
      ↓ failure
keyword fallback
```

`scripts/llm/hints.py` generates progressive hints. Hints can use the retrieved context and, for computable questions, the trusted computed result without immediately revealing the full solution.

## 13. Frontend → backend connection

The important connection in `frontend/app.py` is:

```text
user question
    ↓
ask_tutor()
    ↓
pipeline.prepare()
    ├─ retrieve
    ├─ resolve level
    ├─ compute/verify
    └─ build prompt
    ↓
pipeline.resume()/generation
    ↓
LLM streaming
    ↓
answer returned to Streamlit
```

The frontend is therefore mainly responsible for **interaction and presentation**. Core RAG, verification, prompting, tutoring state, memory, and LLM communication stay in the backend.

## 14. Useful checks

Before launching the UI, retrieval can be smoke-tested:

```bash
python -u scripts/retrieval.py
```

The MVP also contains backend/pipeline tests under:

```text
scripts/llm/test_pipeline.py
```

For a full UI test, ensure the local ChromaDB has been built and at least one valid inference API key is available.

## 15. Dependencies

The MVP `requirements.txt` includes:

- PyMuPDF
- ChromaDB
- sentence-transformers
- rank-bm25
- OpenAI client
- python-dotenv
- SymPy
- Streamlit
- pandas

Install from the branch's existing `requirements.txt`:

```bash
pip install -r requirements.txt
```
