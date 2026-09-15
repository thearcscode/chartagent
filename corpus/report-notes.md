**Sort direction ignored in frozen envelopes — 2026-09-13 (#139, ADR-0023).**
19 runs across 9 requests emitted sort items shaped `{field, order}` instead of `{field, dir, nulls}`. The compiler ignored `order` and sorted ascending. All 19 were rail hits and all were counted as delivered.

| request | runs | `order` value |
| --- | --- | --- |
| r03 | 1, 2, 3 | `asc` |
| r06 | 1, 2, 3 | `ascending` |
| r09 | 2 | `ascending` |
| r20 | 1, 2, 3 | `descending` |
| r21 | 3 | `descending` |
| r22 | 3 | `descending` |
| r30 | 1, 2, 3 | `asc` |
| r37 | 1, 2, 3 | `asc` |
| r43 | 3 | `ascending` |

For the 14 `asc` / `ascending` items, the ignored value matched the default. The 5 `descending` items (r20 runs 1–3, r21 run 3, r22 run 3) were drawn in ascending order.

**None of the 19 runs carried a `limit`**, so every bound row set was correct and only row order was wrong. Rail share is unaffected, because the rail was chosen correctly. Delivery counted these as painted with matching row counts, which is still true. The gate number is not re-scored.

**`step1_calls` / `step2_calls` change definition — 2026-09-13 (#144, ADR-0023 Decision 8).**
This frozen `corpus/outputs.json` (`corpus-prereg-v1`, 150 runs) counts a step's call only after it decodes: a decode failure recorded `0` for that step, which is why both `r09` decode failures at P1 exit show `step1_calls=0` instead of `2`. `tools/record_corpus.py`'s `RecordingClient` now counts every ask, decoded or not — a transport retry inside one ask still doesn't count twice, but a schema decode failure counts exactly like a decoded return.

A series recorded after this fix is **not comparable to this frozen series** on `step1_calls` / `step2_calls` alone: the same underlying rate reads as a smaller number here than it would today. This file is not re-recorded or re-scored; the gate number this report published is unaffected, since it never depended on the miscount. Per-attempt journal rows (`step`, `ask`, `outcome`, `emit`, `rejected_emit`, `checker`) are new with the fix and are absent from this frozen file's records.

**Plumbing retest after the typed menu — 2026-09-14.** Same 50, `--purpose plumbing`, library `01e3671` (`main` after #156). Rail share **39 of 50**, Wilson 95% [0.648, 0.872]; that gate would clear. This directory's `report.md` / `report.json` / `outputs.json` are not rewritten. Covering note: `docs/research/rail-share-retest-2026-09-14.md`.

**Gate-trip review (ADR-0013 Decision 13) — 2026-09-15 (#163).**
Reviewer: the maintainer of the published cost model.

*Breach.* The P1-exit gate run (#129, `report.md`, 2026-09-11) scored **27 of 50**, Wilson 95% [0.404, 0.670], and tripped. This directory stays frozen and is not re-scored.

*Bucket.* The 23 misses were dominated by **bucket 3, planner failed on an expressible reference**: 15 were `planner_failure` (illegal emits exhausting retries). Bucket 1 (no type in the 48): 3. Bucket 2 (menu cannot express it): 3. Unanswerable: 2. Unattributed: 0.

*Lever pulled: planner quality.* The structured-output shape and repair were changed; the prompt's examples and the cost target were not.
- Repair retries carry the rejected emit and the checker message (#140).
- The transform menu is typed once, ADR-0023 (#139, #147); first-ask legality 74/75.
- Bind-time leaks became repairable `SpecShapeError`s (#137, #156).

*Evidence.* The 2026-09-14 plumbing re-sit above (library `01e3671`, same model) scored **39 of 50**, Wilson 95% [0.648, 0.872], which would clear. Planner failures fell from 15 to 2, and cell 0 is 22 of 22. Its purpose is `plumbing`, not `gate`, and the questions were known from the P1-exit misses, so it is evidence that the lever worked, not a replacement gate number.

*After the re-sit, not re-measured on the 50.* #159 makes `bin.unit` on a non-temporal column a `SpecShapeError` (the `r27` run-3 leak). #160 makes the `raw_sql` repair name `source` (aimed at `r33`, `r35`, `r36`, `r38`, `r48`): a two-line spelling statement in `step1.system.md` with no examples, consistent with ADR-0022 Decision 8. `main` at `3ef30ed`: 610 passed, 5 skipped. Known residue: `tools/record_corpus.py` still labels any non-`ChartAgentError` as a transport fault.

*Cost target.* Not repriced. The ≤ $0.05 `balanced` target is finalised in P2 (PRD §10), once the review gate adds its own cost.

*Verdict: P2 commits.* The remaining misses are buckets 1 and 2 (upstream, and the `window`/`pivot` fog) plus two planner failures. The custom rail and the review gate are the path for those, not further P1 tuning.
