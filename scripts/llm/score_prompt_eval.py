"""Summarize prompt-eval results per version.

Run:  python -m scripts.llm.score_prompt_eval
"""
import pandas as pd

df = pd.read_json("data/prompt_eval_results.jsonl", lines=True)
df = df[df["ok"] == True]                      # drop failed API calls

df["refusal_correct"] = df["refused"] == df["expect_refusal"]
df["hallucinated"] = df["expect_refusal"] & ~df["refused"]
df["over_refused"] = ~df["expect_refusal"] & df["refused"]
df["word_count"] = df["output"].str.split().str.len()

summary = df.groupby("prompt_version").agg(
    n=("question", "count"),
    hallucination_rate=("hallucinated", "mean"),
    over_refusal_rate=("over_refused", "mean"),
    format_compliance=("has_answer_line", "mean"),
    avg_words=("word_count", "mean")
).round(3)

print(summary.to_string())
print("\n--- Hallucinated (answered a trap question) ---")
for _, r in df[df["hallucinated"]].iterrows():
    print(f"[{r.prompt_version}] g{r.grade}: {r.question}")
print("\n--- Over-refused (refused an answerable question) ---")
for _, r in df[df["over_refused"]].iterrows():
    print(f"[{r.prompt_version}] g{r.grade}: {r.question}")