# 29. The eval benchmark is a frozen 150, an unpublished hold-out, and two Goal 2 numbers

- **Status:** Accepted
- **Date:** 2026-09-20
- **Settled on:** [#170](https://github.com/thearcscode/chartagent/issues/170)
- **Builds on:** ADR-0013 Decisions 7/12/13 (two instruments; scorer is a harness;
  named review leaves an artifact), ADR-0014 Decision 17 (disjoint request sets,
  shared tagging schema; do not re-score `corpus-prereg-v1`), ADR-0021 (Excel is
  never chosen by the ranking), ADR-0024 (`painted` omitted on the custom rail and
  on Excel), ADR-0026 (five defect checks; judge-family constraint; bake-off
  candidates; per-item `not_checked`; chart-type appropriateness is a benchmark
  finding), ADR-0027 (`balanced` is 0-or-1 review repair; hop only on Flint
  `marks_present`; `fast` never escalates), ADR-0028 (measurement rule this set
  inherits: three quality runs, `$0.05` sample, usage wiring, p50/p95 table,
  named-review note in this report)
- **Amends:** PRD Goal 2; PRD P0.10; PRD §10 executable/rubric line; PRD §12
  hold-out mitigation; ADR-0013 Decision 7's leftover composition; ADR-0014
  Decision 17's feed clause; ADR-0026's "two rubrics may drift"; ADR-0027
  *Leaves open* for #170; ADR-0028 *Leaves open* for the set and Decision 9's
  unnamed path. Dated errata in place, listed under *What this amends*.
- **Leaves open:** authoring the tagged bytes (`eval/pre-registration.json` and
  datasets) — this ADR freezes the rules, not the 180 requests; the critic
  bake-off's **outcome** (ADR-0026 Decision 10; named run on this set); the
  OpenAI image-plus-schema probe (blocking only if that bake-off flips the critic
  to Gemini); whether `fast` still raises on planner buckets 1–3 (#175);
  `generate_recipe` (#175); the reference `Rasteriser`'s default size and scale.
  Quality counts, wiring, `fast` never escalates, the `$0.05` sample, and the
  billed-token rule stay **closed** on ADR-0027 / ADR-0028.

## Context

P0.10 / PRD Goal 2 asked for ≥95% executable-output and ≥85% rubric pass at
`balanced` on a public ≥150, independent judge, ≥20% human double-scoring per
release, CIs, run in CI. ADR-0013 Decision 7 split instruments: the 50 **gates**
rail share once; the ≥150 **publishes**. ADR-0014 Decision 17 forbade nesting
the 50 inside the 150. ADR-0026 parked chart-type appropriateness on this judge,
required a different judge family from the critic, and left the two rubrics
unaligned. ADR-0028 told this ticket to measure cost and latency **here** and
not to re-score `corpus-prereg-v1`.

Until `#175`, buckets 1–3 still **raise**. Cell-1 density is therefore
load-bearing for the 95% line: 3× the 50's matrix makes 95% unachievable before
the custom rail exists.

## Decision

### 1. Four instruments stay four

`corpus-prereg-v1` (pressure corpus, scored once), the **eval benchmark** (this
ADR), first-ask legality (25×3 over fixtures), and the injection suite. Disjoint
**(instruction text, dataset sha256)** across all four. Shared tagging schema
with the 50: intents, shapes, stress cell. No eval-benchmark case, public or
hold-out, enters a prompt as a few-shot.

### 2. Freeze a public 150; hold-out is extra

Tag **`eval-benchmark-v1`**. Membership is frozen; scoring is not. Goal 2/3
published numbers are always this 150. Community cases land in the hold-out or a
future tagged v2, never silently in the frozen 150. Do not cut eval-v2 when
`#175` ships.

**Hold-out** is an extra unpublished pool that **starts at 30**, same tagging
schema, at least one of each public cell 0–4. Each release scores 30 drawn by a
**pre-registered permutation**. Community / newly authored cases **append**.
First release scores the initial 30. Never used for prompt, model, or few-shot
work. Not published as Goal 2.

### 3. `eval/` is the artifact tree, disjoint from `corpus/`

| path | role |
| --- | --- |
| `eval/pre-registration.json` | hashed freeze: public 150, smoke 30 IDs, hold-out pool, `human_calibration_permutation`, hold-out permutation, Q10/Q18 matrices |
| `eval/pre-registration.md` | dated authoring note |
| `eval/NOTICE` | Spider / nvBench table licences |
| `eval/data/` | pinned datasets; sha256 in the pre-registration. **Do not reuse `corpus/data/`** |
| `eval/report.md` + `report.json` + `outputs.json` | **latest published** full-set table |
| `eval/runs/<date>/` | dated snapshot of that published run |
| `eval/report-notes.md` | append-only named reviews |
| `eval/holdout/report.md` | hold-out scores; never copied into Goal 2 tables |

The harness **refuses** to score unless `pre-registration.json`'s sha256 matches
the tag. Scorer is a harness, not `__all__`. `outputs.json` is harness records,
**not PNG bytes** — rasters stay CI artifacts / gitignored.

**Published** full-set runs (pre-release, and any run printed as Goal 2/3)
commit the latest table plus a dated snapshot. **Nightly CI does not commit** to
`main`. Smoke is CI-only.

This names ADR-0028's "#170 committed report artifact": `eval/report.md` +
`eval/report-notes.md`.

### 4. Executable-output rate (Goal 2, 95%)

Every request, n=150. Raises, blank canvas, raster/assemble throws = miss.

- **Flint (non-Excel):** `painted` pass **and** compiled row count equals bound
  row count.
- **Custom rail:** `Rasteriser` returned bytes **and** the harness finds the
  image non-blank. This is **not** a `painted` `CheckResult` — that check is
  omitted on the custom rail (ADR-0024). Do not reopen the omission. ADR-0017
  Decision 15 already raises on a false bootstrap paint signal; the harness
  check is the extra look at the bytes, using the same coarse whole-canvas
  predicate Flint `painted` uses.

`marks_present`, `data_truthfulness`, and `review.passed` are **not** this
number. Chrome-without-marks can be an executable hit.

The ≥150 run **supplies** `Rasteriser` + `critique_model`. A Flint
`painted: not_checked` is a **harness misconfig**, not an executable outcome.

**Excel-named requests are an authoring fault.** Ranking never picks Excel
(ADR-0021); `painted` is omitted on Excel (ADR-0024). Do not copy the 50's
Excel cell-3 families.

**Delivery rate** stays served-only, Q1 predicate, excluded count beside, on
the same report. Do not mint an end-to-end product of executable × delivery.

Until `#175`, bucket 1–3 raises are executable misses.

### 5. Rubric pass rate (Goal 2, 85%)

Denominator is **executable hits only**. Raises, blanks, and raster/assemble
throws are out; publish that excluded count beside (delivery's pattern). The
judge **never runs without a PNG**.

The **benchmark judge** scores the five Tier-2 defects **plus chart-type
appropriateness**. Not aesthetics. Never `ReviewReport`, the critic `note`, or
custom-rail `module`. Context is the PNG + instruction + renderer-fenced fields
(Flint: `chartType` / backend / encodings; custom: transform-output column
names). Appropriateness uses the **intent tag**, not a gold `chartType`.

On Flint the judge uses the **same host applicability table** as Tier 2: omit
items that never apply; do not send an inapplicable defect and fail the case on
`not_checked`. Appropriateness **always applies**. On the custom rail all five
defects are sent. `not_checked` on a **sent** item fails the judged case.
Publish per-item `not_checked` for the judge.

A case passes iff every judged item is `pass`.

Working reference judge: **`gemini-3.8-flash`** while the critic stays
Anthropic. If the bake-off flips the critic to Gemini, an OpenAI
image-plus-schema probe becomes blocking. Do not reopen the bake-off.

### 6. Composition — do not 3× the 50

Public **150**, strata **120 / 30**. Per-cell **counts**, not rates. Freeze in
the tag. Tag is final only when every `(cell, shape)` pair is consistent.

| | cell 0 | cell 1 | cell 2 | cell 3 | cell 4 | total |
| --- | --- | --- | --- | --- | --- | --- |
| common path | 90 | 0 | 12 | 2 | 16 | **120** |
| adversarial | 0 | 4 | 8 | 0 | 18 | **30** |
| total | 90 | 4 | 20 | 2 | 34 | **150** |

Cell-1 = **4**, same three uncarryable intents as the 50, none on the common
path. Cell-3 = **2 silent row-drop only** (common path, any backend). No Excel
families, no ranking-dependent boxplot slot.

**Designed certain executable misses until `#175` = 6** (four cell-1 raises +
two row-drops). 95% then has **1 discretionary** miss before the point estimate
fails (143/150 = 95.3%; 142/150 = 94.7%). Cell-4 is **not** a designed
executable miss — only if the planner escapes.

**Cell-4 families (34):**

| family | common path | adversarial | total |
| --- | --- | --- | --- |
| (i) named missing form, carryable intent | 0 | 8 | 8 |
| (ii) unstated measure or grain | 10 (degree **2**) | 2 (degree **≥4**) | 12 |
| (iii) compound ask | 4 | 4 | 8 |
| (iv) hostile metadata | 2 | 4 | 6 |
| **total** | **16** | **18** | **34** |

**Shapes (marginal, per stratum):** common-path 120: **48 long / 48 wide /
12 nested / 12 wide-sparse**. Adversarial 30: **6 / 9 / 6 / 9**. The 12
common-path cell-2 sit inside wide / wide-sparse. Authored adversarial cell-2
(8) sit in wide / wide-sparse / nested, never a shape `raw_sql` cannot carry.

**Nine intents on the common-path 120** (4× the 50's designed 30), using
ADR-0014's names: trend over time **28**, comparison across categories **36**,
distribution of one measure **4**, correlation between measures **8**,
part-to-whole **24**, ranking / top-N **8**, flow or transition between states
**4**, geographic distribution **4**, single value against a target **4**.
Gold chart type is **not** a selection key. Adversarial carryable intents are
reported, not designed. Cell-1 keeps the three uncarryable names.

**Hold-out initial 30** (4:1 strata): common 24 / adversarial 6; cells
**15 / 0 / 3 / 1 / 5** and **0 / 1 / 2 / 0 / 3**. One cell-1, one row-drop.
Floor of one family among its cell-4; no designed nine-intent table.

**Unanswerable instructions stay out** of the 150 and the hold-out. Own tests,
not Goal 2. No sixth cell. Cell-4(iv) stays dirty names. Injection stays its
own suite (ADR-0014 Decision 17, extended off this set too).

### 7. Authorship

Common-path cell-0/2: nvBench 1.0 unnamed-mark leftover IDs, **disjoint from
`corpus-prereg-v1`**, fluency rewrite (content-preserving, both versions
stored). Cell-1, cell-4, row-drop, hold-out, and **adversarial cell-2 (8):**
**authored**. Do not take leftover nvBench IDs from the common-path pool for
those eight. Quda out. nvBench 2.0 out until the repo asserts a licence. NLV is
register only. NOTICE unchanged in kind (Spider tables CC BY-SA 4.0).

Every case has a **reference frame** or a cell-1 null + `expressible_if`.
Diagnosis only (expected-vs-reported rail), never Goal 2. `expressible_if`
still feeds pin-bump recomputation (ADR-0014 Decision 13).

nvBench **databases** may recur if table bytes differ. First-ask fixtures are
not eval-benchmark datasets.

### 8. Cell-1 is authored once; `#175` changes how it is read

Do not retag. Do not drop the four from n=150. Expected **rail** is custom /
bucket 1 in both eras. Expected **executable** is era-conditional: pre-`#175`
known misses (raise); post-`#175` expected custom-rail executable hits
(Decision 4's custom predicate). Appropriateness still uses the uncarryable
intent. After `#175` the 95% designed-miss budget is the two row-drops.

### 9. Scoring protocol

One `create_chart` per (case, quality). **No majority-of-three.** The 50 paid
for a gate; the 150 pays for a table. Inherit ADR-0028: all three qualities on
a published full-set run; `$0.05` sample and raise counts; usage × dated list
price or fail the row/run; p50/p95 table; custom companion line omitted while
recipe n=0. `balanced` is 0-or-1 review repair, hop only on Flint
`marks_present` (ADR-0027). A balanced repair is not clipped into a fast row.

### 10. CI vs published vs bake-off

- **Smoke:** 30 IDs frozen in the tag — cell-0 **18**, cell-1 **1**, cell-2 **4**
  (2 common-path, 2 adversarial), cell-3 **1**, cell-4 **6** (3/3). Same 30
  every prompt/model-touching CI. `balanced`, executable only, no judge, no
  fast/best. After `#175` that cell-1 ID stays in the smoke and is expected to
  start passing executable.
- **Full 150** nightly (CI, not committed) and pre-release (published): three
  qualities, executable + judge + ADR-0028 table + delivery / rail-share
  companions.
- **Critic bake-off:** named **one-shot** on this set (re-run only if the critic
  family is revisited). Humans score the **five defects only**, on executable
  hits, critic applicability table. Do not rewrite Goal 2's 85% from bake-off
  labels. Selection criteria stay ADR-0026 Decision 10.

### 11. Human calibration of the judge

Each release: **30 executable hits** from the public 150, drawn by
`human_calibration_permutation` — a pre-registered order over the public 150;
each release take the first 30 that were executable hits that run (if
`n_exec < 30`, score all). Same Decision 5 rubric and applicability. **One
rater:** maintainer of the published eval claim. Publish per-item exact-match
vs the judge and a disagreement count. **85% is never rewritten** from human
labels. Hold-out is not in this 20%; its permutation is a separate freeze
field. A collapse is a **dated note in `eval/report-notes.md`**, not an ADR
erratum, and is **distinct** from Decision 12's target-miss note.

### 12. Named review when 95% or 85% misses

**Role:** maintainer of the published **eval claim** — Goal 2's 95%/85% **and**
ADR-0028's table on this set. That **is** ADR-0028's cost-model maintainer for
#170 runs. Do not staff two reviewers for one report. The 50's gate review
stays on `corpus/report-notes.md`.

**Fires:** a **published** full-150 run at `balanced` whose executable-output
point estimate is < 95% (n=150), or whose rubric-pass point estimate is < 85%
(n = that run's executable hits). Smoke, hold-out, fast/best, and p95 never
fire it. A Wilson interval that merely spans the target does not. Pre-`#175`
cell-1 raises and the two row-drops **count** in the point estimate (n stays
150) but the note must name them as **authored**, not as a new lever.

**Where:** one dated entry in `eval/report-notes.md` per published run that
missed **any** working target on that run (Goal 2 and/or ADR-0028 cost/latency),
covering every miss on that run. Not an ADR erratum. The note may pull an
implementation lever. **Lowering 95% or 85% needs a new ADR.** The first table
may still reprice **cost** per ADR-0028.

## What this amends

- **PRD Goal 2 / §10 executable and rubric lines** — 95% is every-request
  executable-output on the frozen 150; 85% is judge pass on **executable hits
  only**, five defects plus appropriateness. Published from the full set in
  `eval/report.md`, with CIs. Working targets, not gates.
- **PRD P0.10** — smoke is 30 **frozen IDs** from the public 150; full set
  nightly is CI-only (not committed); published numbers are pre-release (and
  any run we print as Goal 2/3). Judge is a different **family** from the
  critic. ≥20% human double-scoring is 30 executable hits, calibration only.
- **PRD §12 hold-out** — extra unpublished pool beside a **frozen** public 150,
  rotated by pre-registered permutation; community cases append to the pool.
- **ADR-0013 Decision 7** — "different composition" is this ADR's matrix, not
  3× the 50.
- **ADR-0014 Decision 17 feed** — tagging schema and disjointness stand; this
  ADR specifies n, mix, authorship, and the `eval/` tree.
- **ADR-0026 Consequences** — the two rubrics are **deliberately different**:
  the judge is the five defects plus appropriateness, not a second copy of
  Tier 2 and not a read of `ReviewReport`. "May drift" as an open alignment is
  discharged.
- **ADR-0027 *Leaves open*** for #170 — discharged here. `#175` / `#176` /
  `#177` stay open.
- **ADR-0028 *Leaves open*** for the set, and Decision 9's unnamed path —
  discharged: the set is this 150; the artifact is `eval/report.md` +
  `eval/report-notes.md`. Measurement rules stand. The first table may still
  reprice cost.

### PRD Goal 2 — two denominators

**Erratum, 2026-09-20 (#170, ADR-0029).** Goal 2's ±3.5 pp at n=150 is the
**executable-output** line. Rubric pass is 85% of **executable hits**, with
the excluded count beside. Putting raises in both numbers double-counts
planner failure.

### PRD P0.10 — nightly does not commit; smoke IDs are frozen

**Erratum, 2026-09-20 (#170, ADR-0029).** "The full set runs nightly and
pre-release" stays as **when it runs**. What is **committed** as the published
table is the pre-release (and any Goal 2/3 print) run under `eval/`. Nightly
does not land on `main`. The ≥30 smoke subset is a frozen ID list, not a
fresh draw.

## Consequences

- **Until `#175`, 95% is tight by design.** Six authored misses leave one
  discretionary. The report says so. After `#175` the four cell-1 cases can
  become custom-rail hits without a new tag.
- **85% can move while 95% does not.** A pretty wrong chart type fails the
  judge and still counts as executable.
- **Excel is invisible on this instrument.** Delivery's Excel dependence stays
  a pressure-corpus fact.
- **Core stays measurement-free.** The harness meters usage and judges
  pictures; `__all__` does not grow.

## Alternatives rejected

- **Nest the 50 in the 150, or 3× its matrix** — Decision 6. Pre-registration
  dies, or 95% is unachievable before `#175`.
- **Alias executable-output to delivery rate** — Decision 4. Different
  denominators; Goal 2 costed n=150.
- **Every-request 85%** — Decision 5. Double-counts planner failure.
- **Same five defects only, or appropriateness only** — Decision 5. Abandons
  ADR-0026's assignment, or lets a wrong chart type pass Goal 2.
- **Read `ReviewReport` as the 85%** — Decision 5. The circularity §14 exists
  to prevent.
- **Excel-named cases, or a special no-picture Excel predicate** — Decision 4.
  Reopens ADR-0024's omission or splits "picture with the rows."
- **Rotate the published 150** — Decision 2. Headline incomparable across
  releases.
- **Majority-of-three on the 150** — Decision 9.
- **Full 150 × 3 qualities + judge on every PR** — Decision 10.
- **Commit nightlies to `main`** — Decision 3.
- **`corpus/eval/` or `docs/eval/` without datasets** — Decision 3.
- **Human labels rewrite 85%** — Decision 11.
- **Wilson trip as a Goal 2 gate** — Decision 12.
- **Lower 95%/85% in a report note** — Decision 12. New ADR.
- **Unanswerable or injection cells in the 150** — Decision 6.
- **Retag or shrink n after `#175`** — Decision 8.
- **PNG bytes in `outputs.json`** — Decision 3.

## What this feeds

- **Authoring `eval-benchmark-v1`** — past this ticket's edge: leftover nvBench
  IDs, authored cells, `eval/NOTICE`, hash tag. Freeze fields in the appendix.
- **[#175](https://github.com/thearcscode/chartagent/issues/175)** inherits the
  cell-1 reading rule (Decision 8) and that buckets 1–3 enter the `$0.05`
  sample only as returned `ChartResult`s (ADR-0028).
- **The critic bake-off** inherits this set, five-defect humans, named one-shot
  (Decision 10). Outcome still open.
- **Studio** inherits nothing new on the public surface; this is a harness.

## Evidence

- PRD Goal 2 / P0.10 / §10 / §12 as written before this ADR.
- ADR-0014 Decision 2 matrix and `corpus/pre-registration.md` designed
  common-path intents 7/9/1/2/6/2/1/1/1 (4× = 28/36/4/8/24/8/4/4/4); shape
  marginals 12/12/3/3 and 4/6/4/6 (4× / 1.5× = 48/48/12/12 and 6/9/6/9).
- ADR-0024 Decision 4 table: `painted` omitted on Excel and the custom rail.
- ADR-0017 Decision 15: false paint signal is `RasterisationError`.
- ADR-0026 Decision 10: bake-off candidates; judge-family constraint.
- ADR-0028 Decision 9: named review in this report, not an ADR erratum.
- `corpus/report.md` / `report-notes.md` / `pre-registration.json` — the analog
  this tree copies, with a different lifetime (scored every release).

## Related

- [#170](https://github.com/thearcscode/chartagent/issues/170) — the grilling
  this settles.
- ADR-0013, ADR-0014, ADR-0024, ADR-0026, ADR-0027, ADR-0028.
- `CONTEXT.md` gains **Eval benchmark**, **Executable-output rate**, **Rubric
  pass rate**, **Hold-out**, **Benchmark judge**, **Smoke subset**.

## Appendix — `eval-benchmark-v1` freeze fields

Per request: `id`, `source` (`nvbench1` | `authored`), `source_id`,
`query_original`, `query_rewritten`, `stratum` (`common_path` | `adversarial`),
`cell` (0–4), `cell_family` (cells 3 and 4), `intent` (ADR-0014's nine names, or
an uncarryable name for cell 1), `shape` (`long` | `wide` | `nested` |
`wide_sparse`), `dataset_path`, `dataset_sha256`, `reference_frame` (façade-valid
input frame, or `null`), `expressible_if` (cell 1 only), `ambiguity_degree`
(cell-4(ii) only), `expected_outcome` (`hit` | `miss`), `expected_bucket`
(misses only). Cell-1 `expected_outcome` for **rail** is miss / bucket 1;
**executable** expected is era-conditional (Decision 8) and is **not** a second
stored field that flips the tag.

Per file: `flint_version`, `fixture_commit`, the cell × stratum matrix, shape
splits, designed common-path intent counts, cell-4 family table, `smoke_ids`
(30), hold-out pool records, hold-out permutation, `human_calibration_permutation`
(pre-registered order over the public 150; each release take the first 30 that
were executable hits that run), and the initial hold-out 30's cell × stratum
mix. The two permutations are separate fields.
