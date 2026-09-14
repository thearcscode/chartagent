# Rail-share score — 2026-09-14

Tag `corpus-prereg-v1`. Pre-registration sha256 `e4372c8d9309440f0ba1d6d58db841cfda7ffd0b2003120d11f3b7b2aae84c79`.

**Authoring pin:** Flint `0.5.1` / fixture `34ef451`.
**Scoring pin:** Flint `0.5.1` / bundle `d82901aa5bf701f892e11b6e68b28cfc7ec6cd7ac8cac35bdf2e9a0248a23e06`.

## Rail share (gated)

39 of 50. Wilson 95% [0.648, 0.872]. Gate clear: Wilson lower bound is at or above 60%.

At this frozen mixture the count is Poisson-binomial, whose SD is 1.44× smaller than the binomial at the same mean, so Wilson overstates sampling uncertainty and the gate is harder to clear than costed.

Goal 3's ≥75% is a published target, not a gate.

Common-path stratum: 28 of 30, Wilson 95% [0.787, 0.982].
Adversarial stratum: 11 of 20, Wilson 95% [0.342, 0.742].

Backend ranking applied: vegalite > echarts > plotly > chartjs > excel, unless the request named a backend (ADR-0021). Of cell 3's six stress slots, four are silenced by this ranking and never fire: Excel's empty-after-filter refusal, the pyramid two-groups rule, candlestick ordering, and the non-painting ECharts boxplot (Boxplot routes to Vega-Lite). The two discrete-channel row-drop slots remain — the ranking-proof floor.

Backend default partition — filter+rank only, no override applied (pin fact, beside the share, never inside it): vegalite 36, echarts 8, plotly 1, chartjs 3, excel 0 of the union; 8 on exactly one backend.

## Per-cell rail counts (k of n; no rates, no intervals)

Counts are against the tagged snapshot. Cell moves on the scoring pin are listed below and do not rewrite the tag.

- cell 0: 22 of 22
- cell 1: 3 of 4
- cell 2: 5 of 10
- cell 3: 5 of 6
- cell 4: 4 of 8

## raw_sql_used (menu coverage)

Pooled: 4 of 39.
Common-path: 2 of 28, Wilson 95% [0.020, 0.226].
Adversarial: 2 of 11, Wilson 95% [0.051, 0.477].

## Delivery rate

37 of 39 painted with matching row counts. Excluded from the denominator: 11. The combined end-to-end figure is not minted.

## Escape-reason histogram

Bucket 1: 3. Bucket 2: 4. Bucket 3: 0. Bucket 4: 0.

Bucket 2 reads zero by construction and the menu lever is fed by the raw_sql_used rate, not by the histogram.

## Planner-failure, unanswerable, and unattributed misses

A planner-failure miss carries no escape reason — the planner broke rather than judged — and is never folded into bucket 3 or guessed as a bucket. An unanswerable-instruction miss (ADR-0020) is a request that made no sense against the data — a different fault from bucket 1 or 2, and also never a bucket. An unattributed miss carries neither a bucket nor a `miss_kind` and is a harness bug, never guessed as either.

Planner-failure misses (no bucket): 2.
Unanswerable-instruction misses (no bucket): 2.
Unattributed misses (no bucket, no miss_kind): 0.

hits 39 + buckets 1–4 7 + planner-failure 2 + unanswerable-instruction 2 + unattributed 0 = 50, n 50.

Planner-failure ids: r35, r48.

Unanswerable-instruction ids: r24, r41.

## Call cost (floor, not a live measurement)

ADR-0019 D6: a run is two calls (step 1, step 2), so the cost line ADR-0014 D12 called "150 planner calls" means 150 runs.

At 150 recorded runs the floor is 300 calls and the worst case is 750 at the 5-call retry cap.
Mean planner calls per chart has a floor of 2.0 on a hit and 1.0 on a miss; at this run's rail share the no-retry floor is 1.780, not 1.0. The floor is published beside the mean so a reader does not mistake the no-retry baseline for the mean and conclude the planner retries constantly.

Retry rate is published per step, since step 1 and step 2 point at different levers — the same argument ADR-0013 D10 makes for the histogram. No per-call retry data is recorded yet, so no per-step rate is minted here; it is published once the harness records it.

## Expected versus reported

Surprise hit on a cell-1 request: r31, r32, r34.

- r24: expected hit, reported miss
- r25: expected hit, reported miss
- r31: expected miss, reported hit
- r32: expected miss, reported hit
- r34: expected miss, reported hit
- r35: expected hit, reported miss
- r36: expected hit, reported miss
- r38: expected hit, reported miss
- r41: expected hit, reported miss
- r45: expected hit, reported miss
- r46: expected hit, reported miss
- r47: expected hit, reported miss
- r48: expected hit, reported miss

## Bucket confusion (among actual misses)

- expected 1: reported 2: 1

## Cell moves on the scoring pin

No cell moved between the tagged snapshot and the scoring pin.

## Per-request 2–1 counts

Rail 4, raw_sql_used 3, delivery 4.
