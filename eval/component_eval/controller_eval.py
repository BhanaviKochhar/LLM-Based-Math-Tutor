"""eval/component_eval/controller_eval.py — C3: controller state-machine
evaluation.

Design note (why this doesn't reimplement controller logic): the project
already has two real, reviewed deterministic test suites that exercise the
controller directly against scripts.llm.controller --
eval/controller_walk.py (pure state-machine scenarios) and specific
functions in frontend/test_app.py (mocked-integration scenarios). This
evaluator does NOT duplicate that logic in a third place (which would risk
"test code that makes the benchmark pass artificially" by construction,
since a reimplementation could silently diverge from the real assertions).
Instead it RUNS those real suites and cross-references their actual
pass/fail output against eval/datasets/controller/v1_scenarios.json's
25-scenario index, by scenario_id -- giving a genuine per-scenario result
traced to real execution, not a restatement.

Scenarios NOT run here, by category (never silently dropped -- each is an
explicit exclusion with a reason):
  - ctl-019..023: evidence_type "real provider call" -- requires live LLM,
    not run in this pass; status reported as excluded_live_llm_required.
  - ctl-024, ctl-025: test_reference "none (proposed future work)" -- no
    implementation exists yet; status reported as excluded_not_implemented.

Run:
    python -m eval.component_eval.controller_eval
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from . import results

ROOT = results.ROOT
SCENARIOS_PATH = ROOT / "eval" / "datasets" / "controller" / "v1_scenarios.json"

_SCENARIO_HEADER_RE = re.compile(r"^(\d+)\.\s")
_CHECK_LINE_RE = re.compile(r"^\s*(ok|FAIL)\s+(.*)$")


def _run_controller_walk() -> dict[int, list[tuple[str, bool]]]:
    """Runs the REAL eval/controller_walk.py as a subprocess and parses its
    stdout into {scenario_number: [(check_name, passed), ...]}, grouped by
    the 'N. <title>' headers the script itself prints (scenario() calls)."""
    proc = subprocess.run(
        [sys.executable, "-m", "eval.controller_walk"],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    by_scenario: dict[int, list[tuple[str, bool]]] = {}
    current = None
    for line in proc.stdout.splitlines():
        header = _SCENARIO_HEADER_RE.match(line.strip())
        if header:
            current = int(header.group(1))
            by_scenario.setdefault(current, [])
            continue
        m = _CHECK_LINE_RE.match(line)
        if m and current is not None:
            status, name = m.groups()
            by_scenario[current].append((name, status == "ok"))
    return by_scenario


def _run_test_app_function(func_name: str) -> list[tuple[str, bool]]:
    """Calls ONE named function in frontend/test_app.py directly, with its
    module-level check() monkeypatched to record (name, passed) tuples
    scoped exactly to that call, instead of parsing printed output."""
    import importlib

    test_app = importlib.import_module("frontend.test_app")
    recorded: list[tuple[str, bool]] = []
    orig_check = test_app.check

    def _recording_check(name: str, cond: bool) -> None:
        recorded.append((name, bool(cond)))
        orig_check(name, cond)

    test_app.check = _recording_check
    try:
        getattr(test_app, func_name)()
    finally:
        test_app.check = orig_check
    return recorded


def run() -> dict:
    with open(SCENARIOS_PATH, encoding="utf-8") as f:
        scenarios_doc = json.load(f)
    scenarios = scenarios_doc["scenarios"]

    walk_results = None
    per_example = []
    exclusions = []
    n_pass = n_fail = n_excluded_live = n_excluded_not_impl = 0

    _walk_ref_re = re.compile(r"eval/controller_walk\.py:\s*scenario\s*(\d+)")
    _app_ref_re = re.compile(r"frontend/test_app\.py:\s*(\w+)")

    for sc in scenarios:
        sid = sc["scenario_id"]
        ref = sc.get("test_reference", "")
        evidence = sc.get("evidence_type", "")

        if ref.startswith("none") or "proposed future work" in ref:
            n_excluded_not_impl += 1
            exclusions.append({"scenario_id": sid, "reason": "no implementation exists yet (test_reference: 'none')"})
            per_example.append({"scenario_id": sid, "outcome": "excluded_not_implemented"})
            continue

        if "real provider call" in evidence:
            n_excluded_live += 1
            exclusions.append({"scenario_id": sid, "reason": "requires a live LLM provider call; not run in this pass"})
            per_example.append({"scenario_id": sid, "outcome": "excluded_live_llm_required"})
            continue

        m = _walk_ref_re.search(ref)
        if m:
            if walk_results is None:
                walk_results = _run_controller_walk()
            scenario_num = int(m.group(1))
            checks = walk_results.get(scenario_num, [])
            if not checks:
                n_fail += 1
                per_example.append({"scenario_id": sid, "outcome": "fail",
                                    "reason": f"controller_walk scenario {scenario_num} produced no "
                                    "recorded checks -- the scenario_id's own reference may be stale"})
                continue
            passed = all(ok for _, ok in checks)
            if passed:
                n_pass += 1
            else:
                n_fail += 1
            per_example.append({
                "scenario_id": sid, "outcome": "pass" if passed else "fail",
                "source": f"eval/controller_walk.py scenario {scenario_num}",
                "checks": [{"name": n, "passed": ok} for n, ok in checks],
                "reason": None if passed else [n for n, ok in checks if not ok],
            })
            continue

        m = _app_ref_re.search(ref)
        if m:
            func_name = m.group(1)
            try:
                checks = _run_test_app_function(func_name)
            except Exception as e:
                n_fail += 1
                per_example.append({"scenario_id": sid, "outcome": "error", "detail": repr(e)})
                continue
            passed = bool(checks) and all(ok for _, ok in checks)
            if passed:
                n_pass += 1
            else:
                n_fail += 1
            per_example.append({
                "scenario_id": sid, "outcome": "pass" if passed else "fail",
                "source": f"frontend/test_app.py::{func_name}",
                "checks": [{"name": n, "passed": ok} for n, ok in checks],
                "reason": None if passed else [n for n, ok in checks if not ok],
            })
            continue

        # Unrecognised reference format -- do not silently skip.
        exclusions.append({"scenario_id": sid, "reason": f"unrecognised test_reference format: {ref!r}"})
        per_example.append({"scenario_id": sid, "outcome": "excluded_unrecognised_reference"})

    aggregate = {
        "total_scenarios": len(scenarios),
        "pass": n_pass,
        "fail": n_fail,
        "excluded_live_llm_required": n_excluded_live,
        "excluded_not_implemented": n_excluded_not_impl,
        "deterministic_pass_rate": {
            "numerator": n_pass, "denominator": n_pass + n_fail,
            "rate": round(n_pass / (n_pass + n_fail), 4) if (n_pass + n_fail) else None,
        },
    }

    path = results.write_result(
        "controller_eval",
        dataset_sources=[{"path": str(SCENARIOS_PATH.relative_to(ROOT)),
                          "version": scenarios_doc.get("schema_version"),
                          "item_count": len(scenarios)}],
        config={"method": "cross-references eval/datasets/controller/v1_scenarios.json "
               "scenario_ids against REAL execution of eval/controller_walk.py "
               "(subprocess, output parsed by scenario header) and named "
               "functions in frontend/test_app.py (direct call, instrumented "
               "check()) -- does not reimplement controller assertions",
               "live_llm_used": False},
        per_example_results=per_example,
        aggregate_metrics=aggregate,
        exclusions=exclusions,
        notes=("This scores DETERMINISTIC controller/state-machine correctness "
              "only (mode/phase/transition correctness), never the quality of "
              "generated prose -- scenarios whose evidence_type is a real "
              "provider call are excluded, not scored as pass or fail."),
    )
    summary = [
        f"# controller_eval — {path.name}",
        "",
        f"Deterministic scenarios: {n_pass} pass, {n_fail} fail "
        f"(of {n_pass + n_fail} actually run)",
        f"Excluded (live LLM required): {n_excluded_live}",
        f"Excluded (not yet implemented): {n_excluded_not_impl}",
    ]
    results.write_summary_markdown(path, summary)
    return {"result_path": str(path), "aggregate": aggregate}


if __name__ == "__main__":
    out = run()
    print(json.dumps(out["aggregate"], indent=2))
    print(f"\nWrote {out['result_path']}")
