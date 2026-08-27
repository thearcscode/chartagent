# 13. Rail share is a pooled, pre-registered number, and the gate's remedy is a diagnosis

- **Status:** Accepted
- **Date:** 2026-08-27
- **Settled on:** [#10](https://github.com/thearcscode/chartagent/issues/10)
- **Builds on:** ADR-0002 (the input frame *is* the spec), ADR-0008 (the transform menu and
  its `raw_sql` escape), ADR-0009 (the per-backend vocabulary; what the façade validates),
  ADR-0012 (declared versus realised capability; selection is a filter)
- **Amends:** ADR-0008's feed clause, and PRD §7.3, §9 Goal 3, §11, §12 and §14 plus the
  v0.3 changelog — recorded as dated errata in place and listed under *What this amends*

## Context

PRD §7.3 carries a load-bearing number it explicitly marks as a guess: *"the ~80%
deterministic-rail share used throughout this document is a hypothesis, not a
measurement."* §11 makes it an exit criterion — publish the measured share, and **if it is
below 60%, revisit grammar scope and the cost model.** Goal 3 wants ≥75% on the benchmark.

Three things have changed underneath that, and a fourth was never checked.

**The rule is now mechanical.** ADR-0009 generates the vocabulary and ADR-0012 fixes what
declared capability is, so *expressible on the deterministic rail* is no longer a judgment:
it is **valid against the generated façade, and within declared capability**. There is
nothing left for a rubric to score.

**The grammar stopped being ours.** The gate protected a cost model built on a grammar we
could grow on demand. We pinned Flint instead, so growing the chart vocabulary now means
persuading an upstream project on its own schedule. The gate's original remedy is not a
lever we can pull.

**Capability turned out not to be the binding constraint.** ADR-0012 measured it: Vega-Lite
and Plotly accept every one of Flint's 705 cookbook fixtures. That corpus is Flint's own, so
it says nothing directly about *requests* — but it does mean the per-backend capability
surface is not what will exclude a request. What excludes a request is that **no chart type
among the pin's 48 can carry the ask**, or that the transform menu cannot express the shape.

**And nobody had costed the gate as a statistic.** It is a proportion measured on 50
requests, compared to a threshold, and the PRD never asks whether 50 can carry it.

### What 50 requests can and cannot say

Wilson 95% intervals on the pressure corpus:

| measured | interval |
| --- | --- |
| 30/50 = 60% | [46.2, 72.4] |
| 35/50 = 70% | [56.2, 80.9] |
| 40/50 = 80% | [67.0, 88.8] |

A 70% reading is compatible with *both* "the gate is breached" and "the hypothesis holds".
But the specific contrast the gate exists for is affordable:

| contrast | n for 80% power, one-sided α=.05 |
| --- | --- |
| 60% vs 80% | **33** |
| 60% vs 75% | 61 |
| 75% vs 80% | **440** |

**The gate is answerable at n=50 and Goal 3 is not answerable at any planned n.** That is
not a defect in the corpus; it is a property of the two questions, and the PRD already knows
how to say so — Goal 2 costs its own n in the text (*"±3.5 pp at n = 150 — narrow enough to
publish; at n = 30 it would be ±8 pp, which is not"*). Goal 3 was written without that
discipline.

## Decision

### 1. Expressible means façade-valid and within declared capability, against the union

A request is **rail-expressible** when the frame a competent analyst would write for it is
valid against the generated façade *and* within declared capability for **some** backend the
pin ships — not for the backend the planner happened to pick.

The share validates a **cost model**, and cost turns on whether an LLM wrote chart code, not
on which assembler ran. Scoring against the chosen backend would also bind the headline
number to ranking policy, which ADR-0012 Decision 7 deliberately left open, making the
measurement unreproducible between sessions.

Backend-forced cases are a **pin fact published beside the share, never inside it**: 9 of
the 48 chart types are on neither Vega-Lite nor Plotly, and 8 exist on exactly one backend.
A request that only ECharts can draw costs nothing extra, but it is a real routing
constraint and it should be visible.

### 2. The rule is executed, not judged — so the number does not exist before the planner

There is no human labelling pass and no rubric. A rubric would score our opinion of the
router; a human label would score the labeller.

What stays human is the **reference frame** — what a competent analyst would have built for
each request — which is [#7](https://github.com/thearcscode/chartagent/issues/7)'s to author.
It is used to **diagnose misses** (Decision 10), never to manufacture a share before the
system can produce one. **This number does not exist in P0.** Saying so is better than
publishing a proxy.

### 3. The denominator is every request; the unit is one request, one chart

Numerator: requests served by the deterministic rail. Everything else counts against it —
custom rail, refusal, planner failure, and *nothing in the 48 fits*.

A denominator of "requests that produced a frame" would launder planner failures out of the
number, and the sentence being validated is *"~80% of requests"*, not *"~80% of requests we
managed to plan"*. One request maps to one chart, per PRD non-goal 4.

### 4. `raw_sql` is in the numerator, and published as its own rate beside it

A `raw_sql` chart generates no chart code, runs no sandbox, and refreshes at $0. On the cost
model it is a deterministic chart, and the share is a cost-model instrument.

But a rising `raw_sql_used` rate means the transform menu is under-powered, which is
precisely the diagnosis Decision 10 depends on — so it is **published beside the share and
never folded into it**. ADR-0008 fed this ticket the rate without saying which way it
counted; that is settled here.

### 5. Realised-capability failures are out of the share, and get a second number

Excel refusing on empty rows (353 of 365 fixtures), the pyramid two-groups rule, the
candlestick ordering rule, the 17 non-painting ECharts boxplots — all invisible at rail
decision time, because the rail is chosen before anything compiles.

Charging them to the share would measure the planner for something it structurally cannot
see. Dropping them would let the share overstate what users received. So there are **two
numbers, never merged**: **rail share** (planner-side, what the gate is about) and
**delivery rate** (did a chart actually paint). #7 inherits the corpus-composition
constraint; the split is this ADR's.

### 6. Rail is decided at plan time, and neither review nor retries move it

A deterministic chart that **fails the review gate stays deterministic** — that is a
review-gate number. Mixing them would make rail share a function of review strictness, so a
stricter gate would read as a grammar hole.

**One exception:** a review failure that *escalates* onto the custom rail scores custom,
because the escalation is the escape.

An invalid frame rejected by the façade, retried, and accepted is **still deterministic**.
The extra calls are cost — reported as mean planner calls per chart — not share. Otherwise a
flaky planner looks like a missing grammar feature, and the gate's diagnosis (Decision 10)
sends us to the wrong lever.

### 7. Two instruments: the pressure corpus gates, the benchmark publishes

The **50-request pressure corpus is the gate**, measured once at **P1 exit, before P2
commits**. The **≥150-case benchmark is the standing published number**, reported per
release with intervals, the same shape Goal 2 already uses for the executable rate.

They have different n, different composition and different purposes, and conflating them is
what produced the §11-versus-§14 contradiction this ADR corrects. The corpus can be
*authored* earlier (#7), but it cannot be *scored* until the planner exists (Decision 2).

**Note, 2026-08-28 ([#7](https://github.com/thearcscode/chartagent/issues/7), ADR-0014).**
*"Different composition"* is now specified: the two are **disjoint request sets sharing a
tagging schema** (intents, dataset shapes, stress cell). The 50 is scored once and the 150
every release, so a 50 nested inside the 150 would be re-scored continuously and tuned
against — pre-registration would die at the first look.

### 8. Pooled 50, with the mixture pre-registered

The gate is scored on the **pooled 50**, not on the 30-request representative stratum.

Stratifying sounds more honest and is worse: at n=30 the Wilson floor puts the trip
threshold at **76.7%**, so clearing a 60% gate would require 24/30 — hitting the hypothesis
exactly, just to pass. At n=50 the threshold is 72.0%, which is the only affordable reading
of the only affordable contrast.

The real worry — that a mixture chosen after seeing results tunes the answer — is killed by
**pre-registration, not by stratification**: #7 freezes the 30/20 ratio and the taxonomy
**before any request is scored**, and both strata are reported beside the pooled number so
*"we passed by going easy on the nasty 20"* is visible on the face of the report. The 30 is
how the *common majority* story is read; the 50 is the only n that can tell 60 from 80.

**This ADR hands #7 exactly one constraint: the ratio is frozen before scoring, not tuned to
the outcome.**

**Note on this decision's wording, 2026-08-28
([#7](https://github.com/thearcscode/chartagent/issues/7), ADR-0014).** This decision calls
the 30 the *representative* stratum and the 20 the *nasty* ones. Having examined every
available request corpus, **none measures request frequency in the wild** — nvBench 1.0 and
2.0 are SQL- and LLM-synthesised, Quda's task mix is a factorial of its own elicitation
protocol, and the NLV Corpus was elicited by showing participants a chart. So
*representative* asserts an external population nothing we can reach supplies, while this
decision's own gloss — *"how the common majority story is read"* — is already accurate. The
strata are renamed **common-path stratum** and **adversarial stratum** in `CONTEXT.md` and
in ADR-0014 Decision 1.

**This changes no decision here.** The 30/20 ratio, scoring on the pooled 50, reporting both
strata beside it, the Wilson trip rule and pre-registration-before-scoring all stand.

ADR-0014 Decision 12 additionally records — as a finding, not an amendment — that the
n-costing above assumes a **binomial**, while a frozen heterogeneous composition is
**Poisson-binomial** with strictly smaller variance (measured: 1.44× smaller SD at the
pre-registered mixture). Wilson therefore overstates sampling uncertainty and this gate is
**harder to clear than costed**. The trip rule is unchanged; the conservatism is disclosed
beside the interval.

One further consequence ADR-0014 draws out: pre-registration freezes the **ratio**, not the
**difficulty** of the 20 — and on this gate's arithmetic, if the common path lands exactly on
the ~80% hypothesis the adversarial stratum must still score **≥13/20 = 65%** to clear.
Difficulty is therefore frozen too, as a cell × stratum matrix, in ADR-0014 Decision 2.

### 9. The gate trips on the interval, not the point estimate

**Trip when the Wilson 95% lower bound falls below 60%** — at n=50, anything at or below
36/50 = 72.0%. A 70% point estimate does not establish that we are above the gate, and a
gate that treats it as if it did is decoration.

The consequence is Decision 10's named review, **not an automatic revision**. The gate says
*we cannot rule out being under 60%*, which is a reason to look, not a verdict.

### 10. The remedy is a diagnosis, because the original remedy no longer exists

Growing Flint's chart vocabulary is an upstream feature request on someone else's schedule.
It is not a lever available to clear a gate, and the PRD's *"grammar scope is revisited"*
quietly assumed it was.

Three levers remain, and the procedure is to **find out which bucket the misses are in
before pulling one**:

| miss bucket | lever | ours? |
| --- | --- | --- |
| no chart type in the 48 can carry the request | upstream feature request | **no** |
| the transform menu cannot express the shape | grow the menu — `pivot` and `window` are already cut to P1 by ADR-0008 | yes |
| a request with an expressible reference frame was escaped anyway | planner quality: prompt, model, structured-output shape | yes |
| — | reprice the published cost target | yes, always |

Repricing is the only guaranteed lever, and naming it as such is the honest version of what
§11 promised.

### 11. The escape-reason vocabulary is fixed here; `escape` placement stays fog

The reason recorded on every custom-rail request is one of the three buckets above. That
vocabulary is a scoring input and is settled here.

**Where the value is written is not** — a field inside `x_chartagent` versus a sibling
result type remains open on the map, and it does not change what the values are. When it
lands it **reconciles to this list**; it does not mint a second vocabulary.

One consequence for the UI: `design/`'s screen `5c` shows a single *"proposed grammar
change"* panel, and it is **two buttons, not one**. A missing chart type is an upstream
request nobody here can schedule; a missing transform is our backlog item. Presenting them
identically promises a response we cannot make for half of them.

### 12. The scorer is not in the library, and the report is committed

ADR-0012 Decision 2's discipline applies unchanged: **a measurement about the library is not
a capability of it**, and `__all__` does not grow for it. The scorer is a harness script in
this repo.

Its artifact is a **committed JSON plus a short dated markdown report** carrying the pooled
share, both strata, the Wilson interval, the `raw_sql_used` rate, the delivery rate, and the
escape-reason histogram. Committed rather than left in CI logs, because the gate's entire
purpose is that a later reader can see what the number was **at the moment the cost model
was locked**.

### 13. The reviewer is a role, and the review leaves an artifact

The named reviewer is **the maintainer of the published cost model**, a role rather than a
person, since §13's resourcing assumption is two engineers and the holder will change.

A breach produces a **public dated note** — in this ADR or in Decision 12's report — saying
which bucket the misses fell in and which lever was pulled. **A review that leaves no
artifact is indistinguishable from not having gated**, and this gate exists precisely
because a number went unexamined for three document versions.

## What this amends

Recorded as dated errata in place, so a reader of the original text is not required to find
this ADR to learn what changed.

| Document | What moved |
| --- | --- |
| **ADR-0008** feed clause | The gate measures **rail share**; `raw_sql_used` measures **menu coverage**. They are published together and counted apart (Decision 4) |
| **PRD §7.3** | The Phase-0 lock is struck — the share cannot be scored before the planner exists (Decision 2), and the gate is at P1 exit (Decision 7) |
| **PRD §9 Goal 3** | ≥75% becomes a **target reported with an interval**, not a pass/fail criterion — at n=150 it cannot be distinguished from the 80% hypothesis it tests |
| **PRD §11** | The P1 exit criterion gains the decision rule: Wilson 95% lower bound below 60%, pooled over the pre-registered 50 (Decisions 8, 9) |
| **PRD §12** | *"Deterministic-rail share ≥ 75% on benchmark"* is reported with an interval, matching the line above it on executable rate |
| **PRD §14** | The risk row's *"before launch"* is struck as a third gate nobody specified; the gate is §11's |
| **changelog v0.3** | *"Phase 0 validation gate"* is corrected to P1 exit |

### PRD §7.3 — the Phase-0 lock was never available

**Erratum, 2026-08-27 (#10, ADR-0013).** §7.3 says the hypothesis is *"validated (or
revised) against the Phase 0 pressure-test set and the eval benchmark before Phase 1 commits
to the cost model"*. The share is façade validity plus declared capability **on what the
system actually served**, which needs a planner — and the planner is P1. There is no
Phase-0 number to have. The corpus can be authored in P0 (#7); it cannot be scored there.

Same class as ADR-0004's finding that ADR-0001's *"fails on any unexplained diff"* was
unbuildable as written, and ADR-0011's that *"stratified sample rows"* was not deliverable at
profile time: a requirement that reads fine and has no moment at which it could run.

### PRD §9 Goal 3 — ≥75% cannot be a pass/fail criterion

**Erratum, 2026-08-27 (#10, ADR-0013).** Separating 75% from the 80% hypothesis at 80% power
needs **n ≈ 440**. The benchmark is ≥150 cases, so the criterion cannot be evaluated as
stated, at any n anyone has planned.

Goal 2 already applies the right discipline one line above — it costs its own n in the text
and declines to publish at a width it considers too wide. Goal 3 is restated to match:
**≥75% is a target, reported with a confidence interval, not a gate.** The gate is §11's
<60%, which is affordable at n=50 because the 60-versus-80 contrast needs only n ≈ 33.

## Consequences

**The gate can trip while the hypothesis holds, and that is correct.** At n=50 anything at
or below 72% trips it, including readings above 60%. The gate asserts *we cannot rule out
being under 60%*, and Decision 13's artifact is what keeps that from being read as *we are
under 60%*.

**Three numbers are published where the PRD implied one:** rail share (gated), delivery rate
(Decision 5), and `raw_sql_used` (Decision 4). Two of the three would have been invisible
inside a single figure, and each points at a different lever.

**#7 gains a hard constraint and loses a soft one.** The 30/20 ratio must be frozen before
scoring (Decision 8) — but the corpus no longer has to be balanced *for* the gate, because
the gate is pooled and the strata are reported.

**Escape-reason telemetry becomes load-bearing rather than nice-to-have.** Decision 10's
procedure cannot run without it, so the three buckets are a P0 requirement of the
measurement, not just of the roadmap.

**Nothing here is implementable today, and none of it is blocked.** The repo has no
`pyproject.toml` and no planner; like ADR-0010 and ADR-0012, the ADR text is the only
artifact.

## Alternatives rejected

**Score against the backend the planner chose.** Rejected in Decision 1. It binds the
headline number to ranking policy that ADR-0012 Decision 7 left open, so the same corpus
would score differently under two defensible planners and neither would be wrong.

**Gate on the 30-request representative stratum.** Rejected in Decision 8 on arithmetic: the
trip threshold at n=30 is 76.7%, so passing a 60% gate would require hitting the 80%
hypothesis exactly. A gate that only a perfect result clears is not a gate.

**A human-labelled or rubric-scored share, available in P0.** Rejected in Decision 2. It
would produce a number before the thing it measures exists, and the number would be about
the labeller.

**Charge realised-capability failures to the share.** Rejected in Decision 5. The rail is
chosen before compile; a planner cannot avoid an Excel refusal it cannot see, and a share
that punishes it for one is measuring the wrong component.

**Fold `raw_sql` out of the numerator.** Rejected in Decision 4. It costs one planner call,
runs no sandbox, and refreshes at $0 — on the cost model the share exists to validate, it is
a deterministic chart. Its own rate carries the menu-coverage signal.

**A point-estimate gate.** Rejected in Decision 9. At the corpus's n it would treat a reading
whose interval spans 56%–81% as a clean pass.

## What this feeds

- **[#7](https://github.com/thearcscode/chartagent/issues/7)** gets one constraint — freeze
  the 30/20 ratio and the taxonomy before scoring — plus the reference-frame job from
  Decision 2 and the composition constraint from Decision 5.
- **The review gate** (map fog) owns the numbers Decision 6 keeps out of this one.
- **The planner-output contract** (map fog) inherits the escape-reason vocabulary as an
  output requirement, and reconciles the `escape` placement question to Decision 11's list.
- **`design/`'s screen `5c`** splits its grammar-change panel in two (Decision 11).

## Related

- Interval and power arithmetic: Wilson score intervals, one-sided normal-approximation
  power. Reproduced inline in the ADR body; no probe artifact, because the inputs are the
  PRD's own numbers rather than a measurement of the system.
- Vocabulary counts (48 union; 9 of 48 on neither Vega-Lite nor Plotly; 8 single-backend):
  `prototypes/backend-capability/probe.mjs` and `prototypes/facade-codegen/build/vocab-0.5.1.json`.
