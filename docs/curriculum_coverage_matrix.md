# Curriculum Coverage Matrix (Phase B)

**Date:** 2026-10-04
**Branch / commit:** `final-development` @ `6d7879c` (Phase A closure)
**Curriculum taxonomy:** `docs/verified_ncert_class_1_5_topics.md` — user-verified and authoritative. Nothing in this document adds, removes, or reinterprets a topic from that file; this file only maps *existing repository evidence* onto it.

## How to read this matrix

Four things are tracked **separately** per topic, because they are not the same claim:

1. **Dataset coverage** — does any item in `eval/datasets/` (or its Phase B extensions) exercise this topic at all, and with how many items / what question types?
2. **Corpus support** — does the actual retrieval corpus (`data/extracted_json/ncert_chunks.json`, 2,329 chunks) contain material for this topic, *independently checked in this pass* (keyword search against the real corpus, not assumed)? This is marked **Confirmed**, **Not confirmed** (searched, found nothing or inconclusive), or **Not checked** (not probed in this pass).
3. **Known gaps** — what's missing.
4. **Recommended next action** — concrete, not aspirational.

A topic having *any* dataset item does not mean it is adequately covered — item counts and question types are stated explicitly so this isn't implied.

**Question types referenced below:** Direct numerical (D), Word problem (W), Conceptual (C), Real-life application (R), Multi-step (M), Misconception (X), Ambiguous/incomplete student response (A).

---

## Class 1

| Topic | Dataset coverage | Item count | Question types | Corpus support | Known gaps | Recommended next action |
|---|---|---|---|---|---|---|
| Shapes & Spatial Understanding | None | 0 | — | **Confirmed** (grade-1 chunks match "circle/square/triangle/rectangle", e.g. p.53) | No evaluation item of any kind | Add 2-3 direct/conceptual items once Phase C scoring exists |
| Numbers 1 to 9 | Retrieval only (`rq-027` "what comes after 99" — note: this query is actually about numbers beyond 9, not 1-9; mislabeled relative to its own class tag) | 0 graded, 1 retrieval (mislabeled) | — | Not checked | No graded item for the actual 1-9 range; the one retrieval query present doesn't match this topic | Add a small set of grade-1 single-digit counting/ordering items |
| Addition & Subtraction (1 to 9) | `arithmetic/v1_starter.jsonl` | 1 (`ar-001`, addition only) + **2 new** (`v2_phaseB_extension`: `ar-016` add, `ar-017` subtract) | D (all three) | **Confirmed** (grade-1 "Picture Addition"/counting pages exist per corpus; not individually page-matched here) | No word-problem or misconception item at this grade | Add 1-2 word-problem items once corpus page references are confirmed |
| Numbers 10 to 20 | None | 0 | — | Not checked | No evaluation item of any kind | Defer — low priority vs. other gaps |
| Patterns | Retrieval only (`rq-020`, grade 3, not grade 1) | 0 | — | **Confirmed** (grade-1 "pattern" matches, e.g. p.10) | No item tagged to the actual Class 1 patterns topic | Defer |
| Measurement (non-standard) | None | 0 | — | Not checked | No evaluation item of any kind | Defer |
| Data Handling & Money | Retrieval only (`rq-016` "money", grade 2, not grade 1) | 0 | — | **Confirmed** (grade-1 "rupee/coin" matches, e.g. p.134) | No graded item; the one retrieval query present is tagged grade 2 | Defer |

**Class 1 summary:** Before Phase B, essentially untested except one addition case. After this pass's modest extension (below), addition and subtraction within 9 have minimal coverage; five of seven topics remain entirely untested.

---

## Class 2

| Topic | Dataset coverage | Item count | Question types | Corpus support | Known gaps | Recommended next action |
|---|---|---|---|---|---|---|
| Shapes & Spatial Geometry (incl. 3D shapes) | Retrieval only (`rq-014` "shapes") | 0 graded, 1 retrieval | — | **Discrepancy found:** keyword search for cube/cylinder/cone/sphere finds **0 matches at grade 2** and **30 matches at grade 5** in this corpus. Either the Class 2 book uses everyday object names (dice, ball, pipe) instead of formal shape terms — not confirmed either way in this pass — or the 3D-shapes content is concentrated later than the verified topic list's own class placement implies. Reported as a discrepancy, not a correction to the verified list. | No graded item; corpus-placement question unresolved | Have a project-team member read grade-2 pages directly (not keyword search) before concluding there is no corpus support |
| Numbers up to 100 | None | 0 | — | Not checked | No evaluation item of any kind | Add direct/word-problem items |
| Addition & Subtraction (Up to 99) | `arithmetic/v1_starter.jsonl`, `multi_turn/v1_starter.json` | 1 (`ar-002`, subtraction) + 2 multi-turn (`mt-005`, `mt-006`) | D, W (multi-turn) | Not checked | No addition-only item at this grade (only subtraction) | Add a grade-2 addition case |
| Measurement (Length/Weight/Capacity) | Retrieval only (`rq-023` "how to measure length") | 0 | — | Not checked | No graded item | Defer |
| Time & Calendar | None | 0 | — | **Confirmed** (grade-2 "calendar/month/week/season" matches, e.g. p.3) | No evaluation item despite confirmed corpus support | Add 1-2 conceptual items (time/calendar isn't reducible to a single arithmetic answer in most NCERT framings) |
| Data Handling & Patterns | Retrieval only (`rq-020` "patterns in numbers", grade 3 not 2) | 0 | — | Not checked | No item correctly tagged to grade 2 | Defer |

**Class 2 summary:** Thin. Only addition/subtraction has any graded coverage, and even that is subtraction-only plus two multi-turn conversations.

---

## Class 3

| Topic | Dataset coverage | Item count | Question types | Corpus support | Known gaps | Recommended next action |
|---|---|---|---|---|---|---|
| Numbers up to 1000 | Retrieval only (`rq-022` "place value") | 0 | — | Not checked | No graded item | Add direct place-value items |
| Addition & Subtraction with Regrouping | `arithmetic/v1_starter.jsonl` | 1 (`ar-013`, borrowing) | D | Not checked | Single item; no word-problem regrouping case | Add 1 word-problem case |
| Multiplication (Basic) | `arithmetic/v1_starter.jsonl`, `multi_turn/v1_starter.json` | 1 (`ar-003`) + 1 multi-turn (`mt-001`) | D, W | Not checked | No misconception case | Defer |
| Division (Introduction) | `arithmetic/v1_starter.jsonl` | 2 (`ar-004` exact, `ar-005` remainder) | D, W | Not checked | Reasonable for a starter set | Defer |
| Shapes, 2D Nets & Symmetry | Retrieval only (`rq-015` "what is a triangle") | 0 | — | **Confirmed** (grade-3 "symmetry/mirror" matches, e.g. p.12) | No graded/conceptual item despite confirmed corpus support | Add 1-2 conceptual symmetry items |
| Measurement (Standard Units) | Retrieval only (`rq-013` "subtraction with borrowing" — mislabeled, actually a regrouping query not a measurement query) | 0 | — | **Confirmed** (grade-3 cm/kg/L matches, e.g. p.5) | No item actually testing standard-unit measurement at grade 3 | Add 1-2 unit-conversion items |
| Time & Money | Retrieval only (`rq-017`, `rq-029`) | 0 | — | **Confirmed** (grade-3 rupee/paise/clock matches, e.g. p.13) | No graded item | Add 1-2 money/time word problems |

**Class 3 summary:** Multiplication and division are reasonably represented for a starter set; the other five topics have zero graded items despite three of them having confirmed corpus support.

---

## Class 4

| Topic | Dataset coverage | Item count | Question types | Corpus support | Known gaps | Recommended next action |
|---|---|---|---|---|---|---|
| Numbers up to 100,000 | None | 0 | — | Not checked | No evaluation item of any kind | Add direct place-value/large-number items |
| Multiplication & Division (long division, multi-digit) | `arithmetic/v1_starter.jsonl` (`ar-009`, multi-step, not true long division) | 1 | W (multi-step) | Not checked | No item actually exercising a 2-digit-by-2-digit long-division algorithm | Add 1-2 true long-division items |
| Fractions | `arithmetic/v1_starter.jsonl` (`ar-006/007/008`), `extraction/v1_starter.jsonl` (`ex-004`), `conceptual/v1_starter.jsonl` (all 9 cases), `retrieval/v1_starter.jsonl` (`rq-001/002/003/004/006/009/010` — 7 queries), `multi_turn` (`mt-003`, `mt-004`) | By far the densest topic in the project (20+ items across 5 dataset types) | D, W, C, M | **Confirmed** (grade-4 pages 101-112, per `docs/retrieval_evaluation.md`'s own grep) | None — this is the one topic that is genuinely over-covered relative to its curricular weight (1 of 34 topic cells) | No expansion needed; see cross-cutting note below |
| Geometry & Circles | None | 0 | — | **Confirmed** (grade-4 "radius/diameter/compass" matches, e.g. p.91) | No item despite confirmed corpus support | Add 1-2 conceptual circle items |
| Perimeter & Area | `arithmetic/v1_starter.jsonl` (`ar-011`, perimeter only) | 1 | D | **Confirmed** (grade-4 "boundary ... 400 metres" at p.25 is genuine perimeter content) | No area item (only perimeter) at this grade | Add 1 area item |
| Metric Conversions & Time | None | 0 | — | Not checked | No evaluation item of any kind | Defer |
| Data Handling | Retrieval only (`rq-028` "pictograph data handling") | 0 | — | **Not confirmed — searched and found nothing.** A keyword search for "pictograph", "picture graph", "bar graph", "pictogram" returns **zero matches across the entire corpus, all five grades**, not just grade 4. This does not prove the content is absent (it may use different wording, e.g. "picture" alone, or live only in images the PDF extraction (Section III of `main.tex`) explicitly says are lost), but no confirming evidence exists in this pass. | No graded item; corpus support actively unconfirmed, not just unchecked | A project-team member should check the actual grade-4 book pages directly before writing data-handling items, since keyword search alone could not locate this topic anywhere |

**Class 4 summary:** Fractions is extremely well covered; every other topic in the class ranges from thin to zero, and Data Handling specifically could not be located in the corpus by keyword search at all.

---

## Class 5

| Topic | Dataset coverage | Item count | Question types | Corpus support | Known gaps | Recommended next action |
|---|---|---|---|---|---|---|
| Large Numbers & Operations | None | 0 | — | **Confirmed** (grade-5 "lakh/crore" matches, e.g. p.16) | No item despite confirmed corpus support | Add direct/word-problem large-number items |
| Shapes & Angles | None | 0 | — | **Confirmed** (grade-5 "angle/protractor/degree" matches, e.g. p.6 — 60 matches, the strongest signal of any topic probed) | No item at all | Add 1-2 conceptual angle items |
| Symmetry & Rotations | None | 0 | — | Not checked | No item at all | Defer |
| Factors & Multiples (LCM, HCF, prime/composite) | None | 0 | — | **Confirmed** (grade-5 "factor/multiple/prime/HCF/LCM" matches, e.g. p.6) | Zero coverage of an entire topic despite confirmed corpus support — the single largest confirmed gap in the project | **Fill now** — see `arithmetic/v2_phaseB_extension.jsonl` below (this pass adds LCM/HCF items) |
| Fractions & Decimals | `arithmetic/v1_starter.jsonl` (`ar-014` fraction-of-fraction, `ar-015` remainder) — **no decimal item anywhere** | 2 fraction items, 0 decimal items | D | **Confirmed** (grade-5 "decimal/tenths/hundredths" matches, e.g. p.6) | Decimals are a confirmed-supported, zero-coverage sub-topic — the second-largest confirmed gap | **Fill now** — see `arithmetic/v2_phaseB_extension.jsonl` below |
| Area, Perimeter & Volume | None at grade 5 specifically (`ar-011` perimeter is tagged grade 4) | 0 | — | **Confirmed** (grade-5 "volume/cuboid" matches, e.g. p.193; "area/perimeter" broad search gives 82 grade-5 matches) | No grade-5 area/perimeter/volume item despite the strongest corpus signal of any topic in the class | Add 1-2 items; natural next expansion after this pass |
| Data & Mapping Skills | None | 0 | — | **Confirmed** (grade-5 "map/scale" matches, e.g. p.5) | No item despite confirmed corpus support | Defer |

**Class 5 summary:** Before this pass, five of seven topics had zero items, including two (Factors & Multiples, decimals) with strong confirmed corpus support. This pass's modest extension targets exactly those two.

---

## Cross-cutting findings

1. **Fractions (Class 4) is covered roughly 10-20x more densely than any other single topic.** This is a known, previously-documented artifact of project history (the conceptual-tutoring bug that drove most of the prior development session was a fractions conversation), not a deliberate curricular weighting. No further fraction items were added in this pass; the priority is breadth elsewhere.
2. **The conceptual dataset (`conceptual/v1_starter.jsonl`) has no `grade` field at all** (confirmed against `docs/evaluation_dataset_schema.md`'s own schema table for that file) — every "Class 4" attribution for its 9 items in this matrix is this document's own inference from context clues (toffees, mangoes, fraction framing typical of the Class 4 chapter), not a structural guarantee. This is a real limitation of the existing schema, not something this pass changes (schema changes to `v1_starter.jsonl` would need a new `v2` file per the existing versioning convention, which is a larger undertaking than Phase B's modest-expansion mandate).
3. **A few existing retrieval queries are tagged to a different grade than the topic they actually probe** (e.g. `rq-013`, `rq-017`, `rq-020`, `rq-027` as noted above). These are pre-existing items from before this pass; flagged here, not altered, per the instruction not to change existing labels in place.
4. **Keyword search is a weak corpus-support instrument.** "Confirmed" above means a plain-English keyword match was found; "Not confirmed" means the keywords used did NOT find anything, which could mean the content doesn't exist, uses different wording, or (per `main.tex` Section III) was lost during PDF extraction because it lived only in an illustration. Every "Not confirmed" row above is a candidate for a project-team member to read the actual source page before concluding anything.
5. **A corrected error from the prior audit:** `docs/current_state_evaluation.md` (the pre-Phase-A audit) stated the extraction dataset had 7 items. Independently re-counting in this pass found **14** — it was undercounted because only the first several lines were read in that pass. The extraction dataset in fact already covers both the `question_to_expression` stage (7 items, `ex-001..007`) and the `response_to_answer` stage (7 items, `ex-008..014`, testing `response_parser.final_number_str` directly). This is noted here rather than silently carried forward.

## Topic-cell tally

Of the 34 topic cells in the verified taxonomy (7 + 6 + 7 + 7 + 7 across Classes 1-5):

- **Zero dataset items of any kind (not even a mislabeled retrieval query):** 13 topics, before this pass's extension. After the modest arithmetic extension below, 11 remain at zero.
- **Retrieval-query-only coverage** (a query exists but is mistagged to a different class/topic, or no graded item backs it): 11 topics.
- **At least one graded/computable item:** 10 topics (before this pass), 12 (after).
- **Confirmed corpus support checked in this pass:** 16 of 34 cells probed; 14 confirmed, 1 actively not-confirmed (Class 4 Data Handling), 1 showing a class-placement discrepancy (Class 2 3D shapes). The remaining 18 cells were not probed in this pass and are marked "Not checked" above, not "no support."
