# LLM-Based Math Tutor

Phase 1 prototype for a retrieval-augmented math tutor using NCERT Class 3 math textbook PDFs.

The project extracts textbook text, cleans and chunks it, generates local sentence-transformer embeddings, builds a FAISS vector index, retrieves relevant context for a student question, and formats that context into a tutoring prompt.

## Project Structure

```text
data/
  raw/                 Source NCERT ZIP files
  extracted/           Extracted Class 3 NCERT PDFs
  interim/             Raw extracted text JSON
  processed/           Chunks and embedding JSON files
indexes/               Generated FAISS index and retrieval metadata
src/
  data_loader.py       Extract PDF text
  preprocessing.py     Clean text and create chunks
  embedding.py         Generate sentence-transformer embeddings
  vector_store.py      Build FAISS index
  retrieval.py         Retrieve relevant chunks for a query
  prompt_builder.py    Build the final tutor prompt
```

## Setup

Create and activate a virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Optional: create a `.env` file if you want to run API experiments such as `api_test.py`.

```text
HF_API_KEY=your_huggingface_token_here
```

## Run the Pipeline

Run each stage from the repository root.

1. Extract text from PDFs:

```powershell
python -m src.data_loader
```

Writes:

```text
data/interim/raw_documents.json
```

2. Clean and chunk extracted text:

```powershell
python -m src.preprocessing
```

Writes:

```text
data/processed/chunks.json
```

3. Generate embeddings:

```powershell
python -m src.embedding
```

Writes:

```text
data/processed/embeddings.json
```

4. Build the FAISS vector store:

```powershell
python -m src.vector_store
```

Writes:

```text
indexes/faiss.index
indexes/metadata.json
```

5. Test retrieval:

```powershell
python -m src.retrieval --query "What is half?" --top-k 3
```

## Prompt Building

`src.prompt_builder` converts retrieval results into a structured Grade 3 tutor prompt with:

- final answer
- step-by-step explanation
- hint
- confidence field

Run the built-in prompt formatting examples:

```powershell
python -m src.prompt_builder
```

## Notes

- Embeddings use `all-MiniLM-L6-v2` from `sentence-transformers`.
- FAISS uses normalized vectors with inner-product search for cosine-style similarity.
- Generated folders such as `indexes/`, `logs/`, `outputs/`, `.env`, and `venv/` are ignored by Git.
- `src/main.py`, `src/model_api.py`, `src/tutor_pipeline.py`, and `src/validation.py` are currently placeholders for later integration work.
