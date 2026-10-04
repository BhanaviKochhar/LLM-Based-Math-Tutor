# External Benchmark Assessment

**Date:** 2026-10-04
**Purpose:** assess whether an established external math word-problem benchmark should complement the project's custom curriculum benchmark, per the task's instruction to investigate GSM8K, SVAMP, ASDiv, and MAWPS.

**Method:** this is a desk assessment based on this assistant's trained knowledge of these four well-known, widely-cited benchmarks. **No live web search or license-text verification was performed in this pass.** Before any external data is actually imported or redistributed, the project team must independently re-confirm current license terms directly from each dataset's own repository/release page — the summary below should be treated as a starting orientation, not a cleared-for-use determination.

**No data from any of these benchmarks has been imported, copied, or committed in this pass.** This document is assessment only.

## Summary table

| Benchmark | Typical content | Grade/difficulty alignment to Class 1-5 | License (as generally known; re-verify before use) | Novel word problems? | Comparison suitability |
|---|---|---|---|---|---|
| **GSM8K** (OpenAI, 2021) | ~8,500 grade-school math word problems requiring 2-8 reasoning steps, created by human writers | Partial overlap -- GSM8K is pitched at roughly upper-primary/early-middle-school (grades 5-8 equivalent) and frequently requires multi-step chained reasoning harder than most Class 1-5 content; some simpler items could map to Class 4-5 | MIT License (permissive; generally known to allow redistribution with attribution) | Yes -- human-authored, not template-generated | Best fit of the four for a "harder, multi-step" comparison slice, but likely skews above the intended Class 1-5 ceiling for most items |
| **SVAMP** (2021) | A challenge set built by applying structural variations (word reordering, irrelevant-information insertion, question reordering) to existing simple arithmetic word problems, specifically to test robustness | Strong alignment -- SVAMP's base problems are simple one-to-two-step elementary arithmetic, close to Class 1-4 difficulty, and its explicit focus on structural/distractor robustness mirrors this project's own "distractor numbers" and "paraphrased" question types | Released for research use (MIT-style, commonly cited as open); re-verify exact terms | Yes -- explicitly designed as structural variants of existing problems, which is close to this project's own "paraphrased/novel formulation" question type | Strong candidate -- most directly relevant of the four to this project's robustness concerns (distractor numbers, paraphrasing) |
| **ASDiv** (Academic/Arithmetic Sentence-level Dataset, 2020) | ~2,300+ English math word problems spanning a wide difficulty range from simple one-step to multi-step, annotated with problem type and grade-level tags | Good partial alignment -- ASDiv explicitly tags problems by grade level, so a filtered subset at its lowest difficulty tiers could map reasonably well to Class 1-5 | Released for research use; license terms vary by source aggregation, re-verify | Mixed -- many items are drawn/adapted from existing textbook-style sources rather than fully novel | Moderate candidate -- the grade tagging is useful, but would require careful filtering to the easiest tier before any Class 1-5 comparison, and its exact license needs re-confirmation given it aggregates from multiple sources |
| **MAWPS** (Math Word Problem Solver corpus, 2016) | An aggregation/unification of several earlier elementary word-problem datasets (AI2, IL, CC, etc.) into a common format | Good alignment for its elementary-level constituent subsets, but MAWPS is itself an aggregator, so quality/difficulty is uneven across its sources | Varies by constituent sub-dataset since it aggregates multiple sources with their own original licenses; this is the least straightforward of the four to clear for redistribution | Largely templated/earlier-generation; less "novel phrasing" diversity than SVAMP or GSM8K | Weakest candidate of the four for direct import, specifically because of its aggregated, mixed-provenance licensing -- would need per-sub-source clearance, not a single blanket license check |

## Recommendation

**Do not import any of these benchmarks wholesale, and do not import anything in this pass.** Per the task's own instructions and this project's research-integrity standards (no fabricated provenance, no unclear-license redistribution), the right sequence is:

1. **Custom benchmark remains the primary result.** The curriculum-aligned benchmark built in this pass (`eval/datasets/curriculum_benchmark/`) is purpose-built for the actual Class 1-5, NCERT-aligned scope this tutor targets, with provenance this project fully controls. External benchmarks target different (generally harder, or source-mixed) distributions and would not be a fair substitute.

2. **If an external comparison is pursued later, SVAMP is the strongest candidate** given its closest difficulty alignment and its explicit focus on the same robustness concern (structural/distractor variation) this project already cares about. A small, hand-picked, clearly-labeled subset (not the full dataset) would be the appropriate scope, with:
   - A documented manifest (which specific items, by their original IDs) rather than a full re-publication.
   - Explicit provenance noting the original source and its license, re-verified directly from the SVAMP repository at the time of use, not from this document's summary.
   - A clear mapping of which SVAMP items actually fall within Class 1-5 scope (most are simple enough; some may still exceed it) and explicit exclusion of any that don't.
   - A note that SVAMP's items are NOT curriculum-aligned to NCERT specifically (they are general elementary arithmetic, largely US/English-curriculum-flavored), so results on them would speak to general robustness, not NCERT curriculum fidelity.

3. **GSM8K is a plausible "harder comparison" slice** for future work (e.g. testing where the tutor's multi-step handling breaks down beyond Class 5 difficulty) but is likely too advanced for most items to serve as a direct Class 1-5 evaluation; it would need deliberate filtering to its simplest subset first, and this filtering has not been attempted in this pass.

4. **ASDiv's grade-tagging is useful as a reference structure** (it shows one existing precedent for grade-tagging elementary word problems) but importing it wasn't attempted here given the unresolved per-source licensing question.

5. **MAWPS is not recommended for import** given its aggregated, mixed-provenance licensing — clearing it would require checking each constituent sub-dataset's original license individually, which is disproportionate effort relative to the benefit over just using SVAMP.

**What was NOT done in this pass, and would need explicit approval before being done:** downloading any of these datasets, verifying their current exact license text from their own repositories, selecting and justifying a specific comparison subset, or running the tutor against any external items. This document is a recommendation for that future work, not a completed external validation.
