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
