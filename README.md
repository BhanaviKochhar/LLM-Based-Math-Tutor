# Tiny Thinker — Math Tutor (Streamlit)

Pure-Python web frontend for the NCERT Class 1–5 Math Tutor. Same idea as
the React version, but single-process so it plugs straight into your
retrieval code — no separate frontend/backend needed.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Opens at `http://localhost:8501`.

## Wiring up your retrieval + LLM pipeline

Everything lives in one function, `ask_tutor()` near the top of `app.py`.
It currently runs in `MOCK_MODE`, returning canned answers so the UI works
standalone today.

To connect it to your real pipeline:

```python
MOCK_MODE = False

def ask_tutor(question, grade):
    from retrieval import hybrid_retrieve   # your BM25 + ChromaDB code
    from llm import generate_answer

    chunks = hybrid_retrieve(question, grade=grade, top_k=5)
    answer = generate_answer(question, chunks)
    return {"answer": answer, "source": chunks[0]["source"]}
```

That's the entire integration surface — the UI, chat history, and grade
filter don't need to change.

## Notes

- Chat history is kept in `st.session_state`, cleared with the sidebar button.
- The grade radio button in the sidebar is passed into every `ask_tutor()`
  call so retrieval can be filtered by class.
- Styling is plain CSS injected via `st.markdown`, matching the notebook /
  graph-paper theme from the React version, if you're running both.
