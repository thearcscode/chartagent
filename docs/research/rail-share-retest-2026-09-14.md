# Rail share after the typed menu — 2026-09-14

A **plumbing** re-sit of the frozen 50 (`corpus-prereg-v1`), not a replacement
gate. `corpus/report.md`, `corpus/report.json`, `corpus/outputs.json`, and
`corpus/report-notes.md` keep the P1-exit paper (27/50, 2026-09-11). This note
does not rewrite them.

Same 50 requests, three runs each, model `anthropic:claude-sonnet-4-6`,
temperature 0. Join `--purpose plumbing`. The questions were known from the
P1-exit misses; that is disclosed, not hidden. Journals stay under
`build/corpus-retest-2026-09-14/` (gitignored).

Scorer output: [`rail-share-retest-2026-09-14-report.md`](rail-share-retest-2026-09-14-report.md)
/ [`rail-share-retest-2026-09-14-report.json`](rail-share-retest-2026-09-14-report.json).

This is not first-ask legality. First-ask (74/75 after #147) lives in
[`first-ask-legality.md`](first-ask-legality.md).

## Headline

| | P1-exit (`corpus/report.md`) | This retest |
| --- | --- | --- |
| Date | 2026-09-11 | 2026-09-14 |
| Library | the P1-exit pin | `01e3671fadcf3979c953c5e2516fffdbc213bf3c` (`main` after #156) |
| Purpose | `gate` | `plumbing` |
| Rail share | **27 of 50** | **39 of 50** |
| Wilson 95% | [0.404, 0.670] | [0.648, 0.872] |
| Gate | tripped (LB < 60%) | would clear (LB ≥ 60%) |
| Common-path | 18 of 30 | 28 of 30 |
| Adversarial | 9 of 20 | 11 of 20 |
| Planner-failure | 15 | 2 |
| Unanswerable | 2 (`r24`, `r41`) | 2 (`r24`, `r41`) |
| Bucket 1 / 2 / 3 / 4 | 3 / 3 / 0 / 0 | 3 / 4 / 0 / 0 |
| `raw_sql_used` | 0 of 27 | 4 of 39 |
| Delivery | 26 of 27 | 37 of 39 |

Goal 3's ≥75% remains a published target, not a gate. 39/50 is 78% at the
point estimate; the Wilson lower bound is 64.8%.

## What moved

The typed menu (#147), first-ask legality, and repair retries (#140) were aimed
at the 15 `planner_failure` / `invalid_emit` misses. Twelve of those requests
are now majority hits: `r01`, `r02`, `r04`, `r07`, `r09`, `r15`, `r16`, `r23`,
`r27`, `r28`, `r29`, `r49`. Cell 0 is 22 of 22 (was 15 of 22).

Two planner-failure ids remain: `r35` (unpivot / quarterly revenue by region)
and `r48` ("Show performance."). Both are `invalid_emit` at `step1_calls=2,
step2_calls=0` on all three runs.

## Leftover misses (11)

| Pile | n | Ids | Meaning |
| --- | --- | --- | --- |
| Bucket 1 | 3 | `r45`, `r46`, `r47` | Word cloud, Marimekko, waffle — no type in the 48 |
| Bucket 2 | 4 | `r25`, `r33`, `r36`, `r38` | Menu cannot say it (`UNPIVOT` / window / ternary-as-bucket-2) |
| Planner-failure | 2 | `r35`, `r48` | Illegal plan; retries exhausted |
| Unanswerable | 2 | `r24`, `r41` | Garbled NL; authored-empty-filter "west region only" |

`r33` is the one bucket confusion: expected 1 (ternary), reported 2.

Bucket 3 is still 0: leftover inexpressible charts did not take the custom-rail
escape. That is why P2 remains the path for charts the menu will not express,
not a fallback for illegal plans.

## Surprise hits on cell 1

`r31`, `r32`, `r34` were authored as expected misses (Venn / overlap / flow
map). The planner now majority-hits them on the deterministic rail. `r34` is
rail 3/3 on ECharts and paint 0/3 (`no marks`); it counts in the share and
out of delivery.

## Delivery gaps among hits

37 of 39 rail hits painted with matching row counts. The two holes:

- **`r27`** — rail 2/3, delivery 1/3. Run 1 painted 96 compiled vs 144 bound
  (cell-3 discrete-channel row drop). Run 2 matched 144. Run 3 is
  `residual_error` `BinderException`: `date_trunc` on BIGINT `year`. Majority
  still a hit.
- **`r34`** — rail 3/3, delivery 0/3, ECharts `no marks`.

## `r27` run 3 and the recorder

`year` is already a year number. The reference frame is `group_by: year` plus
`sum(attendance)`. Run 3 followed the NL ("bin year into a year interval") and
emitted `bin` with `unit: "year"` on that BIGINT column.

`_apply_bin` calls DuckDB `date_trunc` with no bucket check. `create_chart`
only wraps `SpecShapeError` and `SchemaDriftError` from `bind` into a repair.
`BinderException` leaked. `tools/record_corpus.py`'s `attempt()` treats any
non-`ChartAgentError` as transport exhaustion, so the run was left
unjournalled until it was appended by hand as `residual_error`.

That is a library leak plus a recorder mislabel, not a transport fault. A later
fix is `SpecShapeError` when `bin.unit` is set on a non-temporal column, so
`create_chart` can repair, and the recorder should not call a DuckDB binder
error transport. Neither is done in this note.

## Manifest

- Tag: `corpus-prereg-v1`
- Pre-registration sha256: `e4372c8d9309440f0ba1d6d58db841cfda7ffd0b2003120d11f3b7b2aae84c79`
- Library: `01e3671fadcf3979c953c5e2516fffdbc213bf3c`
- Model: `anthropic:claude-sonnet-4-6`
- Flint: `0.5.1` / `d82901aa5bf701f892e11b6e68b28cfc7ec6cd7ac8cac35bdf2e9a0248a23e06`
- Join purpose: `plumbing`
- Journal (gitignored): `build/corpus-retest-2026-09-14/journal.jsonl`
- Paint journal (gitignored): `build/corpus-retest-2026-09-14/paint_journal.jsonl`
