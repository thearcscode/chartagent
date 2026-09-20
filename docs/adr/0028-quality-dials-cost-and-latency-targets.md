# 28. The quality dial's cost and latency are working published targets

- **Status:** Accepted
- **Date:** 2026-09-20
- **Settled on:** [#169](https://github.com/thearcscode/chartagent/issues/169)
- **Builds on:** ADR-0013 Decision 13 (named reviewer is the maintainer of the published
  cost model; a miss produces a public dated note), ADR-0019 Decision 6 (emit-repair
  budgets 1/2/5, counted by the planner, not this dial), ADR-0020 Decision 5 (`quality=`
  omitted at P1), ADR-0022 (planner client; no extended-thinking requirement), ADR-0026
  Decision 9–10 (no critique default; documented reference critic is Sonnet 5), ADR-0027
  (repair counts `fast=0` / `balanced=1` / `best=2`; factory vs per-call wiring;
  `budget_exhausted`; `fast` never escalates; hop only on Flint `marks_present` at
  `balanced`/`best`)
- **Amends:** PRD pillar-4 user story; PRD Goal 3's cost assumption; PRD §10 cost and
  latency lines; ADR-0020 Decision 5's leftover pointer; ADR-0026's "$0.05 is finalised
  from measured token counts in P2"; ADR-0027 *Leaves open*, consequence, and feed for
  #169. Dated errata in place, listed under *What this amends*.
- **Leaves open:** the eval benchmark's cases, judge, and hold-out
  ([#170](https://github.com/thearcscode/chartagent/issues/170) — this ADR feeds the
  measurement rule, not the set); whether `fast` still raises on planner buckets 1–3
  ([#175](https://github.com/thearcscode/chartagent/issues/175); ADR-0027's "fast never
  buys codegen" stays closed); the reference `Rasteriser`'s default size and scale; a
  `ChartResult` cost field and a `ModelClient` usage return (neither is this ticket).
  The first #170 table may reprice a working target; that is the named review, not a
  silent edit of this ADR.

## Context

PRD pillar 4 and Goal 3 published `quality="fast" | "balanced" | "best"` as a
cost-and-latency dial, with a provisional **median cost ≤ $0.05 at `balanced`**
("Sonnet-class planner and small critique model"; "finalised from measured token
counts in Phase 2") and **median latency** deterministic < 10 s / custom < 60 s.
ADR-0020 kept `quality=` off `create_chart` at P1. ADR-0027 put it on, closed the
counts and the hop, and left this ticket **cost and latency targets only**.

Three facts changed what "cheap" and "$0.05" can honestly mean.

**The dial does not skip the critic.** ADR-0027 and the glossary already forbid
reading `fast` as skipping Tier 2. A first-round pass at `fast` and at `balanced`
is the same invoice: planner steps plus one critique. `fast` caps the worst case
(no review repair, no hop). It does not cap emit repairs.

**Token counts have never been measured.** The 2026-09-14 rail-share retest recorded
call counts only. **1.78 calls/chart is the no-retry floor mean** at that run's
rail share (floor 2.0 on a hit, 1.0 on a miss), not a measured mean. Retry rates
were never recorded. 74/75 first-ask legality is step-1 *shape* on a different
25×3 set and does not stand in for emit-repair frequency on #170. An illustrative
Sonnet 4.6 planner at 3k in / 800 out is ~$0.021/call; a two-call first-ask-pass
hit plus the documented Sonnet 5 critic (~$0.009) is **~$0.051**. That figure
assumed no thinking, no cache, and guessed prompt sizes. It is a **floor**, not a
forecast, and it is still unmeasured.

**The median of a ~78% hit mixture is a returned chart**, not the 1.78 mean.
`create_chart` also raises (`InexpressibleRequestError`,
`UnanswerableInstructionError`, `PlannerFailureError`). Raises never reach the
critic. Until #175, buckets 1–3 raise; a hop returns a `ChartResult`. Putting
cheap raises in the $0.05 sample would make the median look better as
planner-failure rises.

## Decision

### 1. `quality=` is a repair-and-hop dial, not a cheaper typical bill

Typical inference cost at `fast` and `balanced` is the same. `fast` caps the
worst case: no presentational revise, no codegen. Do not reopen skipping the
critic, skipping Tier 1, or folding emit retries into this dial (ADR-0027;
glossary **Quality**).

The pillar's first sentence already says *review-loop budget* and stands. The
SaaS user story and ADR-0027's "`fast` is actually cheap" do not.

### 2. The invoice is vendor inference dollars on the documented reference stack

**Reference planner:** `anthropic:claude-sonnet-4-6`. **Reference critic:**
`claude-sonnet-5` (ADR-0026's documented reference, not a pin, not a library
default). An embedder who passes a different `model=` or `critique_model=` is
off the claim. A caller may still pass a small critic; that is ADR-0026
Decision 9 and the risk-table mitigation, not this stack.

Sum every in-loop call on that request: planner steps (including emit repairs),
review repairs, critic, and codegen only if a hop actually fired. Exclude
host/rasteriser compute, Studio, and the CI judge.

### 3. The $0.05 sample is every returned `ChartResult` from `create_chart` at `balanced`

Including `passed=False` and hops/recipes. Raises are **out** of the sample.
Publish the excluded raises as **counts beside it**, split by
`InexpressibleRequestError` / `UnanswerableInstructionError` /
`PlannerFailureError` — the delivery-rate excluded-count pattern, not rail
share's every-request denominator.

After #175, buckets 1–3 enter this sample only if they return a `ChartResult`.
Whether `fast` still raises on 1–3 is #175.

Refresh is not `create_chart` and is not this sample. Rasteriser default size
is not this ticket.

### 4. $0.05, 10 s, and 60 s are working published targets, not gates

Measured on whatever ≥150-case set #170 owns. **Do not re-score
`corpus-prereg-v1`.**

- **Cost:** p50 ≤ $0.05 at `balanced` on Decision 3's sample, USD, Decision 2's
  invoice. Do not move $0.05 off the illustrative first-round-pass floor
  (~$0.051). The first #170 table is what would justify a change.
- **Latency:** p50 wall-clock of `create_chart` on the reference stack
  (profile → planner → bind → rasterise → critique → at most one review
  repair at `balanced` → hop only if `marks_present` actually fired), split by
  the rail of the **returned** artifact. Deterministic < 10 s; custom < 60 s
  at `balanced`. Custom's 60 s is a target for the #175 path; until that seam
  exists, or while recipe n=0, there is no custom latency to score.

A miss triggers Decision 9's named review, not a blocked phase.

### 5. Custom-rail companion: recipe p50, with p95 and n beside

p50 inference $ of ChartResults whose payload is a **recipe**, same invoice,
same #170 run, `balanced`. Not hops-only. **Omit the line while n=0**; do not
publish $0.00. Beside Goal 3, never a substitute (same pattern as
`raw_sql_used`).

### 6. p95 is published beside p50; the same table runs at all three qualities

No second target number. Fast/best rows are **observations**, no targets.
#170 must run the set at all three qualities. A balanced repair cannot be
clipped into a fast result. Empty custom-rail cells (`fast` never hops today)
are omitted like Decision 5, not zeroed.

### 7. 10 s / 60 s are harness targets, not `create_chart` timeouts

`create_chart` does not abort at those walls. Bind's DuckDB timeout is a
different knob. Refresh < 2 s stays the zero-LLM path and is not this dial.

### 8. Emit-repair tokens are on the $0.05 invoice

`quality=` does not cap them. The 1/2/5 emit cap is not reopened. The
illustrative two-call hit is a floor. 74/75 does not stand in for emit-repair
frequency on #170.

### 9. Named review: one dated note per missed #170 run, in the #170 report

Same role as ADR-0013 Decision 13: **maintainer of the published cost model**.

Fires if **any** working target misses on that run: balanced cost p50,
deterministic latency p50, or custom latency p50 when companion n>0. Custom
60 s does not fire while n=0. Fast/best and every p95 never fire it by
themselves.

One public dated note **per missed run**, covering every missed working target
on that run, in the **#170 committed report artifact** (the analog of
`corpus/report.md` / `report-notes.md` — P1's note went in `report-notes.md`,
not into ADR-0013). This ADR states the rule once and points at that report.
Do not log misses as errata on this ADR.

The review may reprice a working target, pull an implementation lever, or
both; the note must say which. Repricing is allowed because $0.05 is still an
unmeasured floor.

### 10. Dollars are vendor-reported usage × a dated list-price snapshot

Each in-loop call: vendor-reported usage on the **actual call** × list prices
snapshotted in that #170 report (dated; reference planner and critic).
Thinking/reasoning tokens count in the bucket the vendor invoices. Critic
image tokens count. Cache-read price only if usage reported a cache read —
do not impute cache hits, do not forecast $0.05 on a cache discount. No
batch, flex, or committed-use. USD. Do not estimate from character counts.

If usage is absent, the harness cannot dollarize that row: **fail the row or
the run**. Never fall back to 3k/800.

Wiring usage is #170's harness, not a `ChartResult` field, not a
`ModelClient` return-type change on this ticket.

## What this amends

- **PRD §4 user story** — "serve free-tier users cheaply and premium users
  with the full review loop" becomes cap review-repair and codegen spend vs
  allow the full review loop. Pillar 4's first sentence stands.
- **PRD Goal 3 cost assumption** — "Sonnet-class planner and small critique
  model" / "finalised from measured token counts in Phase 2" becomes the
  documented reference planner and critic (Sonnet 4.6 / Sonnet 5), a working
  published target measured on the eval benchmark. §10 had no "small critique
  model" phrase; this ADR does not invent a §10 strike for it. §10's cost and
  latency *lines* are restated as working targets and the measurement rule.
- **ADR-0020 Decision 5** — the 2026-09-20 erratum's "cost and latency
  targets remain #169" is discharged here.
- **ADR-0026 Consequences** — the ≤ $0.05 median is a working target; the
  first-round-pass arithmetic is a floor; the first #170 table is what would
  justify a change. Decision 9 (no critique default) is not rewritten.
- **ADR-0027** — *Leaves open* for #169, the "`fast` is actually cheap"
  consequence, and the #169 feed clause. Counts, wiring, hop, and "fast
  never escalates" stay closed.

## Consequences

- **`fast` is a tail cap.** A SaaS free-tier that wants a cheaper *median*
  has to pass a cheaper model, not `quality="fast"`.
- **Planner tokens decide the $0.05 line.** One emit repair already puts a
  chart over the illustrative floor; it moves p50 only if first-ask-pass is
  not the majority, which is unmeasured.
- **Custom/hop sits in the upper tail** of the pooled `balanced` median at
  current rail share and does not move p50. The companion line is how that
  tail is read.
- **The library does not enforce the latency walls.** Missing 10 s is a
  harness finding, not a `TimeoutError`.
- **Core stays usage-unaware.** `ModelClient.run` still returns a typed
  emit. The #170 harness is the meter.

## Alternatives rejected

- **Skip the critic at `fast`** — Decision 1. Closed by ADR-0027.
- **Read `fast` as cheaper at the median** — Decision 1.
- **Bill whatever models the caller supplied** — Decision 2. Unenforceable.
- **Tokens, not dollars** — Decision 2. Throws away the published unit.
- **Include host/rasteriser compute** — Decision 2.
- **Every `create_chart` including raises** — Decision 3. Cheap failures
  pull the median the wrong way.
- **Only `passed=True`** — Decision 3. Drops the fail-closed Flint chart
  ADR-0027 still returns.
- **Drop hops/custom from the $0.05 denominator** — Decision 3. A vanity
  median.
- **P2 exit gate on $0.05 / 10 s** — Decision 4. Same discipline as Goal 3's
  ≥75% share (ADR-0013).
- **Move $0.05 off ~$0.051 now** — Decision 4. Still an unmeasured model.
- **Hops-only companion** — Decision 5. Stale the day #175 serves planner
  misses.
- **Publish $0.00 while recipe n=0** — Decision 5.
- **p95 as a second target, or no fast/best table** — Decision 6. Guesses,
  or cannot test Decision 1.
- **Clip a balanced repair into a fast row** — Decision 6.
- **`create_chart` aborts at 10 s / 60 s** — Decision 7.
- **Exclude emit repairs from the invoice** — Decision 8. A bill nobody
  paid.
- **Cap emit repairs at `fast`** — Decision 8. Reopens ADR-0019.
- **Log misses as errata on this ADR** — Decision 9. The lock document is
  not a log.
- **Cost-miss only** — Decision 9. A 30 s deterministic median would have
  no owner.
- **Impute cache hits, batch/flex rates, or 3k/800 fallback** — Decision 10.
- **`ChartResult.cost` or a `ModelClient` usage return on this ticket** —
  Decision 10. Harness, not public surface.

## What this feeds

- **[#170](https://github.com/thearcscode/chartagent/issues/170)** inherits
  usage wiring (fail the row or the run if usage is absent), three quality
  runs, Decision 3's sample and raise counts, Decision 5's companion line,
  the p50/p95 table, and Decision 9's note location in the committed report.
  It also inherits `balanced` as 0-or-1 review repair plus a possible hop
  only on Flint `marks_present` (ADR-0027).
- **[#175](https://github.com/thearcscode/chartagent/issues/175)** inherits
  that buckets 1–3 enter the $0.05 sample only as returned ChartResults, and
  that whether `fast` still raises on 1–3 is not settled here.
- **Studio** inherits the user-story reading: `quality=` caps review-repair
  and codegen, not typical inference cost.

## Evidence

- `docs/research/vlm-candidates.md` (2026-09-15) — illustrative dollars;
  thinking billed as output; cache-read 0.1×; batch not for the in-loop
  critic; no vendor p50 latency.
- `docs/research/rail-share-retest-2026-09-14-report.md` — no-retry floor
  mean 1.780 at 39/50; retry rates unpublished.
- `docs/research/first-ask-legality.md` — 74/75 after the typed menu, 25×3,
  step-1 shape, not #170 emit-repair frequency.
- `src/chartagent/plan/client.py` — `ModelClient.run` returns a typed emit;
  no usage capture.
- ADR-0013 Decision 13 / `corpus/report-notes.md` (2026-09-15) — the P1
  named-review analog: role, public dated note in the report, not in the
  lock ADR.

## Related

- [#169](https://github.com/thearcscode/chartagent/issues/169) — the grilling
  this settles.
- ADR-0013, ADR-0019, ADR-0020, ADR-0026, ADR-0027.
- `CONTEXT.md` **Quality** was updated in the grilling (typical cost; worst
  case; Avoid: cheaper at the median).
