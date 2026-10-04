"""eval/component_eval/results.py — shared result-artifact writer.

Every component evaluator calls write_result() exactly once, at the end of
its run, so that every result file captures the same reproducibility
envelope (git commit, branch, dataset versions, timestamp, config) around
whatever evaluation-specific payload the caller supplies. This follows the
record shape already specified in docs/evaluation_plan.md's reproducibility
section, extended with versioned filenames so a later run never overwrites
an earlier one (docs/evaluation_plan.md's own convention of a fixed
`eval/results/<dimension>.json` name did not yet guard against that).
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = ROOT / "eval" / "results"


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def environment_info() -> dict:
    return {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
    }


def git_info() -> dict:
    return {
        "commit": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": _git("status", "--porcelain") not in (None, ""),
    }


def write_result(
    evaluator_name: str,
    *,
    dataset_sources: list[dict],
    config: dict,
    per_example_results: list[dict],
    aggregate_metrics: dict,
    exclusions: list[dict] | None = None,
    execution_errors: list[dict] | None = None,
    notes: str = "",
    results_dir: Path | None = None,
) -> Path:
    """Write one reproducible result artifact and return its path.

    `dataset_sources`: list of {"path": "...", "version": "...", "item_count": N}
        -- every dataset file this run actually read, so a result can be
        traced back to exact dataset content later.
    `config`: run configuration (model/provider if applicable, retrieval
        config if applicable, prompt/extract_fn mode, any flags).
    `per_example_results`: raw per-item outcomes -- never aggregated away.
    `aggregate_metrics`: computed summary metrics (component-specific; see
        docs/metric_definitions.md for what each evaluator reports here).
    `exclusions`: items deliberately not scored, each with a reason -- never
        silently dropped.
    `execution_errors`: runtime errors distinct from scored failures.

    Never overwrites a prior result: the filename embeds a UTC timestamp and
    short commit hash, and this function refuses to write if that exact path
    already exists (collision is only possible if called twice within the
    same second at the same commit, in which case the caller should retry).
    """
    out_dir = results_dir if results_dir is not None else RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    git = git_info()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short_commit = (git["commit"] or "nogit")[:10]
    filename = f"{evaluator_name}_{ts}_{short_commit}.json"
    path = out_dir / filename

    if path.exists():
        raise FileExistsError(
            f"Refusing to overwrite an existing result artifact: {path}. "
            "This should not happen in normal use (the filename embeds a "
            "unique UTC timestamp); if it does, wait a second and retry."
        )

    record = {
        "evaluator_name": evaluator_name,
        "run_timestamp_utc": ts,
        "git": git,
        "environment": environment_info(),
        "dataset_sources": dataset_sources,
        "config": config,
        "aggregate_metrics": aggregate_metrics,
        "exclusions": exclusions or [],
        "execution_errors": execution_errors or [],
        "notes": notes,
        "per_example_results": per_example_results,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False, default=str)
    return path


def write_summary_markdown(result_path: Path, summary_lines: list[str]) -> Path:
    """Write a concise human-readable .md summary alongside a .json result,
    same stem, so both the machine-readable and human-readable forms of one
    run are trivially pairable on disk."""
    md_path = result_path.with_suffix(".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(summary_lines) + "\n")
    return md_path
