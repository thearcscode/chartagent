# Rail-share score — 2026-09-11

Tag `corpus-prereg-v1`. Pre-registration sha256 `e4372c8d9309440f0ba1d6d58db841cfda7ffd0b2003120d11f3b7b2aae84c79`.

**Authoring pin:** Flint `0.5.1` / fixture `34ef451`.
**Scoring pin:** Flint `0.5.1` / bundle `d82901aa5bf701f892e11b6e68b28cfc7ec6cd7ac8cac35bdf2e9a0248a23e06`.

## Rail share (gated)

27 of 50. Wilson 95% [0.404, 0.670]. Gate tripped: Wilson lower bound is below 60%.

At this frozen mixture the count is Poisson-binomial, whose SD is 1.44× smaller than the binomial at the same mean, so Wilson overstates sampling uncertainty and the gate is harder to clear than costed.

Goal 3's ≥75% is a published target, not a gate.

Common-path stratum: 18 of 30, Wilson 95% [0.423, 0.754].
Adversarial stratum: 9 of 20, Wilson 95% [0.258, 0.658].

Backend ranking applied: vegalite > echarts > plotly > chartjs > excel, unless the request named a backend (ADR-0021). Of cell 3's six stress slots, four are silenced by this ranking and never fire: Excel's empty-after-filter refusal, the pyramid two-groups rule, candlestick ordering, and the non-painting ECharts boxplot (Boxplot routes to Vega-Lite). The two discrete-channel row-drop slots remain — the ranking-proof floor.

Backend default partition — filter+rank only, no override applied (pin fact, beside the share, never inside it): vegalite 36, echarts 8, plotly 1, chartjs 3, excel 0 of the union; 8 on exactly one backend.

## Per-cell rail counts (k of n; no rates, no intervals)

Counts are against the tagged snapshot. Cell moves on the scoring pin are listed below and do not rewrite the tag.

- cell 0: 15 of 22
- cell 1: 1 of 4
- cell 2: 5 of 10
- cell 3: 3 of 6
- cell 4: 3 of 8

## raw_sql_used (menu coverage)

Pooled: 0 of 27.
Common-path: 0 of 18, Wilson 95% [0.000, 0.176].
Adversarial: 0 of 9, Wilson 95% [0.000, 0.299].

## Delivery rate

26 of 27 painted with matching row counts. Excluded from the denominator: 23. The combined end-to-end figure is not minted.

## Escape-reason histogram

Bucket 1: 3. Bucket 2: 3. Bucket 3: 0. Bucket 4: 0.

Bucket 2 reads zero by construction and the menu lever is fed by the raw_sql_used rate, not by the histogram.

## Planner-failure, unanswerable, and unattributed misses

A planner-failure miss carries no escape reason — the planner broke rather than judged — and is never folded into bucket 3 or guessed as a bucket. An unanswerable-instruction miss (ADR-0020) is a request that made no sense against the data — a different fault from bucket 1 or 2, and also never a bucket. An unattributed miss carries neither a bucket nor a `miss_kind` and is a harness bug, never guessed as either.

Planner-failure misses (no bucket): 15.
Unanswerable-instruction misses (no bucket): 2.
Unattributed misses (no bucket, no miss_kind): 0.

hits 27 + buckets 1–4 6 + planner-failure 15 + unanswerable-instruction 2 + unattributed 0 = 50, n 50.

Planner-failure ids: r01, r02, r04, r07, r09, r15, r16, r23, r27, r28, r29, r33, r35, r36, r38.

Unanswerable-instruction ids: r24, r41.

## Call cost (floor, not a live measurement)

ADR-0019 D6: a run is two calls (step 1, step 2), so the cost line ADR-0014 D12 called "150 planner calls" means 150 runs.

At 150 recorded runs the floor is 300 calls and the worst case is 750 at the 5-call retry cap.
Mean planner calls per chart has a floor of 2.0 on a hit and 1.0 on a miss; at this run's rail share the no-retry floor is 1.540, not 1.0. The floor is published beside the mean so a reader does not mistake the no-retry baseline for the mean and conclude the planner retries constantly.

Retry rate is published per step, since step 1 and step 2 point at different levers — the same argument ADR-0013 D10 makes for the histogram. No per-call retry data is recorded yet, so no per-step rate is minted here; it is published once the harness records it.

## Expected versus reported

Surprise hit on a cell-1 request: r34.

- r01: expected hit, reported miss
- r02: expected hit, reported miss
- r04: expected hit, reported miss
- r07: expected hit, reported miss
- r09: expected hit, reported miss
- r15: expected hit, reported miss
- r16: expected hit, reported miss
- r23: expected hit, reported miss
- r24: expected hit, reported miss
- r27: expected hit, reported miss
- r28: expected hit, reported miss
- r29: expected hit, reported miss
- r34: expected miss, reported hit
- r35: expected hit, reported miss
- r36: expected hit, reported miss
- r38: expected hit, reported miss
- r41: expected hit, reported miss
- r45: expected hit, reported miss
- r46: expected hit, reported miss
- r47: expected hit, reported miss
- r49: expected hit, reported miss

## Bucket confusion (among actual misses)

- expected 1: reported 2: 2

## Cell moves on the scoring pin

No cell moved between the tagged snapshot and the scoring pin.

## Per-request 2–1 counts

Rail 3, raw_sql_used 0, delivery 3.
