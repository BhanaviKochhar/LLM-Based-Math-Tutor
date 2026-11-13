"""eval/component_eval — reproducible component-level evaluation runners.

Each module here scores ONE component (arithmetic/trusted-computation,
extraction, retrieval, controller, personalization) against the real
current implementation and writes a timestamped, never-overwritten result
artifact via results.write_result(). These are evaluation RUNNERS, not
pytest-style pass/fail test suites -- see docs/component_evaluation.md for
the distinction from eval/controller_walk.py, eval/validate_datasets.py,
and scripts/llm/test_pipeline.py (deterministic regression tests), and from
eval/run_eval.py (full-system baseline comparison, a later project stage).
"""
