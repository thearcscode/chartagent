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
