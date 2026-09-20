# 14. The corpus is two strata and five stress cells, and difficulty is what pre-registration must freeze

- **Status:** Accepted
- **Date:** 2026-08-28
- **Settled on:** [#7](https://github.com/thearcscode/chartagent/issues/7)
- **Builds on:** ADR-0008 (the transform menu and its `raw_sql` escape; the three locks),
  ADR-0009 (what the façade validates; encodings are `str | {field, type?}`),
  ADR-0011 (the profile contract; the untrusted subtree),
  ADR-0012 (declared versus realised capability; selection is a filter),
  ADR-0013 (the share is pooled and pre-registered; the gate's remedy is a diagnosis)
- **Amends:** ADR-0013 Decision 8's **prose only** — recorded as a dated note in place. The
  30/20 ratio, the pooled 50 and the Wilson trip rule are untouched.

## Context

ADR-0013 handed this ticket three constraints and left everything else about the corpus
open: freeze the 30/20 ratio and the taxonomy before scoring; author a reference frame per
request, used to diagnose misses and never to manufacture a share; and compose the corpus so
that Excel's realised-capability failures land in delivery rate rather than in the share.

Three things were then measured, and each one moved a decision that looked settled.

### Pre-registration freezes the ratio; it does not freeze difficulty

The gate trips when the Wilson 95% lower bound falls below 60%, which at n=50 is any pooled
reading at or below 36/50. **The first clearing count is 37/50**, so the corpus tolerates
**13 misses in total**.

If **K** of the 50 are requests that miss before the planner runs — nothing in the pin's 48
chart types can carry them — the remaining 50−K must yield 37:

| K | required rate on the rest | discretionary misses left |
| --- | --- | --- |
| 0 | 74.0% | 13 |
| 3 | 78.7% | 10 |
| **4** | **80.4%** | **9** |
| 5 | 82.2% | 8 |
| 8 | 88.1% | 5 |
| 13 | 100% | 0 |
| ≥14 | **unclearable** | — |

And with the strata split 30/20, if the common-path stratum lands exactly on PRD §7.3's ~80%
hypothesis (24/30), **the adversarial stratum must score ≥13/20 = 65% for the gate to
clear**. A set of twenty requests that is 65% rail-expressible is not adversarial in any
ordinary sense.

So the composition rules are the gate. ADR-0013 Decision 8 killed *tuning the mixture after
seeing scores*; it did not address the fact that **difficulty is a free variable set at
authoring time**, and on the arithmetic above difficulty dominates the outcome. That is what
this ADR freezes.

### `raw_sql` absorbs almost everything the transform menu cannot express

Measured against DuckDB 1.5.5 with ADR-0008 Decision 7's Locks 1 and 2 —
`con.extract_statements` for the one-`SELECT` allowlist, `json_serialize_sql` for the
relation allowlist:

| shape | menu (ADR-0008 D2) | `raw_sql` | scores as |
| --- | --- | --- | --- |
| wide → long, `UNION ALL` | no | **1 `SELECT`**, relations `['source']` | numerator hit |
| wide → long, `UNPIVOT` | no | **1 `SELECT`**, relations `['source']` | numerator hit |
| non-ISO dates, `strptime(period,'%b %Y')` | no — the 24-node `Expr` AST has no cast or date-parse node | **1 `SELECT`** | numerator hit |
| window functions, `QUALIFY` | no — cut to P1 by ADR-0008 D2 | **1 `SELECT`** | numerator hit |
| `PIVOT … ON s IN ('a','b')` | no | **1 `SELECT`** | numerator hit |
| conditional aggregation | no | **1 `SELECT`** | numerator hit |
| **`PIVOT` with no `IN` list** | no | **2 statements** (`CREATE`, `SELECT`) → Lock 1 refuses | **genuine miss** |

`raw_sql` is in the numerator (ADR-0013 Decision 4), so every row above except the last is a
**hit**. A corpus built to stress the transform menu therefore moves `raw_sql_used` and
leaves the gated number untouched. In practice only two things move the gate: **requests no
chart type in the 48 can carry**, and **planner quality on expressible references**.

### There is no external corpus that can supply "representative"

Four candidates were examined, and each fails on a different axis:

| corpus | licence | ambiguity | register | tables | queries naming no mark |
| --- | --- | --- | --- | --- | --- |
| nvBench 1.0 | **MIT** (asserted in README) | none — one gold vis per record | SQL-templated, stilted | 152 databases | **3,693 of 25,762 (14.3%)** over 146 dbs |
| nvBench 2.0 | **not asserted** — the README's License section is inside an HTML comment | **100%** — 0 of 7,505 records have one gold | natural | 794 | 1,224 of 7,505 (16.3%) over 562 |
| Quda | **CC BY-NC-SA 3.0** | — | best — human, objectives not actions | 36 | — |
| NLV Corpus | MIT | — | human but **elicited from a shown chart** | 3 | — |

Two of those are structural disqualifications rather than inconveniences.

**nvBench 2.0 is ambiguous by construction.** Every one of its 7,505 released records
carries 2–5 valid gold interpretations (3,388 / 1,544 / 1,483 / 1,090); none carries one. A
corpus whose common-path stratum comes from it has no unstressed cell at all, and an
ambiguity budget inside an all-ambiguous corpus is not a budget.

**Quda's task mix is a factorial artefact.** Its own design is 20 participants × 2 tables ×
10 tasks × 2 queries = 800 target queries, with Amar et al.'s ten low-level tasks *presented
to participants as prompts* in randomised order. The distribution describes an elicitation
protocol, not what analysts ask, so there is no natural frequency in it to inherit.

PRD §7.3 derives the ~80% hypothesis from *"the concentration of common chart types in
published request corpora"* and cites none. **After looking, the citation does not exist to
be recovered:** no available corpus measures request frequency in the wild. Any claim that
the 30 are *representative* would be asserting an external population that nothing we can
reach can supply.

## Decision

### 1. The strata are the common path and the adversarial set; "representative" is retired

The 30 is the **common-path stratum** and the 20 is the **adversarial stratum**. Both terms
enter `CONTEXT.md`.

"Representative" is a claim about an external population, and the Context above establishes
that no source available to us supplies one. ADR-0013 Decision 8's own gloss is already the
honest version — *"the 30 is how the common majority story is read"* — which is a statement
about narrative role, not about sampling.

This is a **wording change and nothing else**. The 30/20 ratio, the pooled 50, both strata
reported beside the pooled number, and the Wilson trip rule are exactly as ADR-0013 fixed
them.

### 2. Nastiness is four stress cells plus an unstressed one, and the matrix is the freeze

"Nasty" as the ticket wrote it named two unrelated things — requests that miss the rail, and
requests that sail through the rail and fail somewhere else. They are separated here, and
what is frozen with the 30/20 ratio is the **cell × stratum matrix**:

| | cell 0 unstressed | cell 1 no intent in the 48 | cell 2 menu-miss, `raw_sql`-hit | cell 3 realised-capability risk | cell 4 expressible but hostile | total |
| --- | --- | --- | --- | --- | --- | --- |
| **common path** | 22 | 0 | 4 | 2 | 2 | **30** |
| **adversarial** | 0 | 4 | 6 | 4 | 6 | **20** |
| total | 22 | 4 | 10 | 6 | 8 | **50** |

What each cell does to the three published numbers:

| cell | moves rail share | moves `raw_sql_used` | moves delivery rate |
| --- | --- | --- | --- |
| 1 | **yes — certain miss** | no | no |
| 2 | no — numerator hit | **yes** | no |
| 3 | no — numerator hit | no | **yes** |
| 4 | **only if the planner escapes** | no | no |

Cell 4 is the only cell whose gate outcome depends on the planner, so its eight slots are
budgeted by family:

| cell-4 family | what it tests | common path | adversarial |
| --- | --- | --- | --- |
| **(i)** names a form the pin lacks, carryable intent — word cloud, Marimekko, waffle | does the planner substitute a carryable form or escape | 0 | 3 |
| **(ii)** instruction ambiguity — unstated measure or grain | does it commit or escape | 2 | 1 |
| **(iii)** compound ask — two questions in one sentence | one request, one chart under pressure | 0 | 1 |
| **(iv)** hostile metadata — `Unnamed: 3`, a `date` column holding strings | profile-to-plan mapping under dirty names | 0 | 1 |
| | | **2** | **6** |

Family (ii) belongs in the common-path stratum: real requests are ambiguous, and if ambiguity
appeared only in the adversarial 20 the common-path reading would be of a politeness that
does not exist in traffic.

**Family (ii)'s difficulty is frozen, not drawn.** nvBench 2.0 records how many valid
interpretations each query carries, so the ambiguity budget is set rather than inherited from
whichever rows we happened to pick:

| slot | stratum | ambiguity degree |
| --- | --- | --- |
| (ii)a | common path | **2** |
| (ii)b | common path | **2** |
| (ii)c | adversarial | **≥4** |

Degree is **recorded per slot in the pre-registration**. Degree 2 is what ordinary
underspecification looks like; degree ≥4 is a request with four defensible readings, which is
the adversarial version. Leaving it unfrozen inside a pre-registered cell would let tuning
back in through a side door, and the number is sitting in the data.

**The family is still *unstated measure or grain*, not "any nvBench 2.0 row with N golds."**
Interpretations that differ only by **mark** are family **(i)** — the planner is choosing a
form, not resolving an underspecified ask — and they do not qualify a slot for (ii). If
Decision 8's licence fallback fires, the three sentences are authored to these degrees
anyway; the number is pre-registered either way. Family (iii)'s reference frame **names which of the two questions
is answered** (ADR-0013 D3), frozen at authoring rather than argued at scoring. Family (iv) is
not an injection slot — see Decision 17.

**Cell 4 tests escape versus the deterministic rail, not frame-match against the reference.**
A valid substitute is a hit; whether it was the *best* chart is a review-gate question and
Decision 16's business, not the share's.

Two exclusions. **Backend-forced requests are not cell 4** — they are a pin fact published
beside the share (ADR-0013 D1). **Huge cardinality is not cell 4** — it produces a valid
frame, so it is cell 3 when it is the mechanism of a row drop, and otherwise a Phase-2
threshold or review-gate matter rather than a rail miss.

**Cell 2 is present in the common-path stratum, and that placement is load-bearing.**
`raw_sql_used` measured over the pooled 50 reports our own quota back to us. Only the
common-path figure is a statement about menu coverage on ordinary requests, and that is the
number ADR-0013 Decision 10's second lever reads. Cell-2 slots are defined as *the menu
cannot express it **and** `raw_sql` can **and** Locks 1 and 2 pass* — a shape `raw_sql`
cannot carry is not a cell-2 slot, because putting one there would silently raise K and
invalidate the arithmetic in Decision 3.

Cell 1 is 0 in the common-path stratum: the 30 is how the common-majority story is read, and
a deliberate impossible request does not belong in it.

### 3. K = 4, and cell 1 is defined at the intent level

Four requests are pre-registered as guaranteed misses — 80.4% required on the other 46, nine
discretionary misses left. Four is enough that ADR-0013 Decision 10's upstream bucket is
populated and the diagnosis has something to sort; much above eight and the gate stops
testing the planner and starts testing our taste in impossible requests.

**Decision 4 makes intent the design axis, which tightens what a cell-1 request is.** It is a
request whose *intent* nothing in the 48 can carry — not one that names a chart type absent
from the 48. Word cloud, Marimekko and waffle all fail that test: their intents are frequency
ranking and part-to-whole, which Bar Chart, Stacked Bar and Pie carry, so a competent
analyst's reference frame is expressible and they are **cell 4, not cell 1**.

Three intents survive, across four slots:

| intent | why the 48 cannot carry it | slots |
| --- | --- | --- |
| **set overlap / intersection structure** | nothing in the 48 encodes membership overlap | 2 — one small (three sets), one many-set |
| **compositional simplex** | no simplex geometry in the 48 | 1 |
| **origin–destination flow on a geography** | `Map` and `Choropleth` place values; flow lines are a layer, and ADR-0002 D8 puts layers out of scope; `Sankey` carries flow without geography | 1 |

The two set-overlap slots are the same intent at different scale, deliberately: the taxonomy
carries **three** uncarryable intents, not four.

A fourth intent was proposed and rejected — **layered distribution** (box plus violin plus
raw points on one axis). It fails the same test: `Boxplot` carries *compare distributions*.
Worse, its absence is **ours** (ADR-0002 D8) rather than upstream's, so a miss would be
diagnosed as bucket 1 — *ask Flint* — when the real lever is *reopen D8*. That contaminates
the histogram the gate's remedy reads. **The test for any future cell-1 intent is both
halves: a competent analyst's reference frame is null, and the lever is an upstream chart
type.**

Cell-1 requests name the **intent**, never the missing type — *"which customers are in both
campaigns but not the app"*, not *"make me a Venn"*. Naming the type would make it a
vocabulary test, and under Decision 13 a later Venn in the union would turn all four into
free hits, leaving K measuring nothing.

### 4. Intent is the design axis; chart-type coverage is reported, not engineered

A request names an intent, not a chart type. Making chart type the design axis would smuggle
the reference frame into the request text and pre-decide what the planner should pick.

**Nine carryable intents.** The stranded-type map below makes *"nothing is stranded"*
checkable rather than asserted, and it is stronger than illustrative: it is a **total
assignment of all 48 chart types in the 0.5.1 union, each to exactly one intent** — 48
assigned, 48 unique, none left over. Names are the pin's own strings, so the map can be
diffed against `vocab.json` on a bump.

| intent | types the 0.5.1 union assigns to it |
| --- | --- |
| trend over time | Line Chart, Area Chart, Range Area Chart, Streamgraph, Bump Chart, Calendar Heatmap, Sparkline, Candlestick Chart |
| comparison across categories | Bar Chart, Grouped Bar Chart, Stacked Bar Chart, **Combo Chart**, Lollipop Chart, Slope Chart, Radar Chart, Waterfall Chart, Gantt Chart, Bar Table |
| distribution of one measure | Histogram, Boxplot, Violin Plot, Density Plot, Strip Plot, ECDF Plot |
| correlation between measures | Scatter Plot, Bubble Chart, Regression, Connected Scatter Plot, Density Contour, Parallel Coordinates, Heatmap |
| part-to-whole | Pie Chart, Donut Chart, Doughnut Chart, Treemap, Sunburst Chart, Rose Chart |
| ranking / top-N | Ranged Dot Plot, Pyramid Chart |
| flow or transition between states | Sankey Diagram, Funnel Chart, Network Graph, Tree |
| geographic distribution | Choropleth, Map |
| single value against a target | KPI Card, Gauge Chart, Bullet Chart |

Several types genuinely serve more than one intent — Bar Chart and Lollipop Chart also answer
*ranking*, Bump Chart also answers *ranking over time* — and the map records the **primary**
assignment so that the partition stays checkable. Ranking is thin by that rule, not by
capability.

Facet (`column` / `row`) is a **layout**, not an intent. Waterfall is **comparison**, not a
tenth intent — a tenth would buy under-powered coverage of all of them at n=50.

**Chart-type coverage is a reported property of the corpus, never a design constraint.** For
the record at the pin: the union is **48** — 36 Vega-Lite, 37 ECharts, 22 Chart.js, 38
Plotly, 18 Excel — and **15 of the 48 have no upstream fixture at all** (Bubble, Calendar
Heatmap, Combo, Density Contour, Donut, Doughnut, Funnel, Gauge, Network Graph, Parallel
Coordinates, Sankey, Sparkline, Sunburst, Tree, Treemap), so nothing is known about whether
they compile. Backend-forced cases — the 9 types on neither Vega-Lite nor Plotly, the 8 on
exactly one backend — are a pin fact published beside the share, never inside it
(ADR-0013 D1).

### 5. Every request pins a dataset and carries a shape label

Rail-expressibility is a property of **(request, dataset)**, not of the request. *"Sales and
profit over time"* is expressible from a long source and needs the escape from a wide one —
same words, different cell.

So each request pins **one dataset, sha256 in the pre-registration**, and carries a
pre-registered **shape label**: `long | wide | nested | wide-sparse`. The split, frozen
marginally per stratum:

| | long | wide | nested | wide-sparse |
| --- | --- | --- | --- | --- |
| common path (30) | 12 | 12 | 3 | 3 |
| adversarial (20) | 4 | 6 | 4 | 6 |

Long is what a flavour-3 result set looks like and what the menu handles natively; wide is
what a spreadsheet export looks like. The adversarial skew toward wide and wide-sparse is
where cell-2 cases come from honestly rather than by fiat.

The freeze is **marginal, not per-cell**: 5 cells × 4 shapes × 2 strata over 50 requests
would mint filler to fill bins nobody asked for. The pre-registration is final only when
every request's (cell, shape) pair is mutually consistent — still before any scoring.

### 6. Single-turn, business language, and the chart type named in exactly one family

- **Single-turn only.** Multi-turn refinement is PRD §7.8, a product feature; inside the
  corpus it would make *"rail is decided at plan time"* (ADR-0013 D6) ambiguous about which
  turn decided it.
- **Business language, not exact column names.** Handing the planner the schema removes the
  profile-to-plan mapping from the measurement, which is a real source of misses in traffic
  and would make the rail look better than it is.
- **A chart type is named only in cell-4(i).** Never in cell 1 (Decision 3), never anywhere
  else — naming it would undo Decision 4 by putting the reference frame in the prompt.

### 7. The reference frame is a façade-valid input frame, and cell 1's is null with a recipe

ADR-0013 Decision 10 uses the reference frame mechanically — *façade-valid, and within
declared capability for some backend*. Prose cannot be run through a façade, so the artefact
is the frame itself: `chart_spec` with `chartType`, encodings and **`baseSize`**, plus
`x_chartagent.transform`. `baseSize` is required, not decorative — Decision 10's delivery
check is not reproducible without a pinned canvas.

For cell-1 requests **no valid frame exists by construction**, so the field is `null` with a
stated reason, and the scorer asserts the null count is exactly four. The absence is the
cell-1 assignment, not a gap in the authoring.

Every null frame additionally carries **`expressible_if`**: the chart-type strings that would
make the intent carryable (for instance `["Venn", "Euler", "UpSet"]`). That list is how
Decision 13 recomputes cell 1 after a pin bump without the impossible step of running a null
frame through a façade. Contingent frames keyed on those names may sit beside it; where they
do not, a newly-expressible request gets one disclosed authoring before scoring, recorded in
the report.

### 8. The sources, and why three of the four obvious ones do not survive

- **nvBench 1.0's unnamed-mark subset is the ID and dataset spine for the common-path 30.**
  MIT, one gold interpretation per record, and 3,693 candidate queries over 146 databases —
  enough to carry Decision 5's per-request dataset pinning and shape spread.
- **Its register is repaired under a pre-registered rewrite rule**: rewrite for fluency,
  never for content, with **both versions stored**. The rewrite may not add or remove a
  measure, a grain, a filter, or a chart-type name. **The diff is the audit**, which is
  exactly what hand-authored text could never offer.
- **NLV Corpus is a register reference only** — how people phrase requests. Never IDs, never
  datasets. Its utterances were elicited from a shown chart, so the chart type is baked in.
- **nvBench 2.0 supplies cell-4(ii) and nothing else**, where 100% ambiguity is the point of
  three slots rather than a property of thirty — **and only if its licence is asserted first.**

**`corpus-prereg-v1` is not cut until `HKUSTDial/nvBench-2.0` asserts a commercially usable
licence in the artefact itself.** Not an HTML comment in the README, not the licence stamp on
the OpenReview paper — an assertion in the repository, so that what we vendor is covered by
something a reader can check. This is a **gate on the tag**, not a preference.

**Fallback, if it is not asserted: cell-4(ii) is authored from their ambiguity patterns and we
redistribute nothing.** Three sentences is a small enough surface that the fallback costs
almost nothing, which is precisely why proceeding on an inferred licence is not worth its
risk — we would be taking a redistribution risk into a public Apache-2.0 repo feeding a
commercial product in order to save three hand-authored sentences. The degrees in Decision 2
are pre-registered under either branch.

This clause is stated in the Decision rather than left in *Evidence*, because a later author
reading only the decisions will otherwise vendor nvBench 2.0 on the strength of a footnote.
- **Quda is dropped entirely.** Decision 1 dissolved its only job — mix referent — its text
  is NC-SA and cannot be vendored into an Apache-2.0 repo destined to go public, and its
  tables carry upstream licence soup. A citation that does no work is worse than no citation.

Two locks on selection. **Do not stratify selection by nvBench's gold chart type** — that
reimports chart type as the design axis and undoes Decision 4; our vis-intent is assigned
*after* selection. And **nvBench's gold vis, its `chart` field, and nvBench 2.0's `steps`
reasoning are never our reference frame** — their `step_3` is literally chart-type reasoning,
and adopting it would be scoring the labeller, which ADR-0013 Decision 2 refused.

### 9. The mix is designed and disclosed, with a floor of one per intent

There is nothing to inherit (Context), so the nine-intent counts across the 30 are **ours,
designed, and published as designed**. Every intent is floored at 1, because at n=30 an
intent at 3% of any source rounds to zero and we would report *"spans nine intents"* while
observing seven.

The floor will do most of the work: the gold chart of nvBench 1.0's unnamed-mark subset is
**Bar 65.4%, Line 11.2%, Pie 9.3%, Scatter 5.6%**, with the remainder under 9%. The report
says so rather than smoothing it.

That same concentration is the first evidence anyone has produced for PRD §7.3's uncited
premise: **bar, line, pie and scatter are 91.5% of that subset, and all four are in the 48 on
all five backends.** It supports the hypothesis that the common path is union-expressible. It
is **not** a licence to make the 30 those four charts — the floor exists to prevent exactly
that — and it confirms that the gate's bite is the adversarial 20.

### 10. Delivery includes the silent row drop, and the denominators are not the same

Flint's layout optimiser drops rows when a discrete channel overflows the layout budget —
**59 of 705 fixtures returned a different row count** depending on canvas size — and nothing
throws. A delivery rate that counts a chart missing half its data as delivered is the number
ADR-0013 Decision 5 created to avoid.

**Delivery = the chart painted AND the compiled row count equals the bound row count.** The
row-count comparison is the predicate; Flint's client-side `_warnings` are supporting
evidence, not the test. This does not reopen ADR-0005 Decision 11, which refused to *predict*
the drop from Python — scoring it after compile is realised capability, which is where
delivery rate lives.

The three numbers do not share a denominator:

| number | numerator | denominator |
| --- | --- | --- |
| **rail share** (gated) | requests served by the deterministic rail | **every request** (ADR-0013 D3) |
| **`raw_sql_used`** | `raw_sql` charts | **deterministic-rail requests in that stratum** |
| **delivery rate** | painted **and** row counts match | requests that emitted a compilable artefact on either rail |

`raw_sql_used`'s denominator excludes custom-rail requests because they never had a menu to
fail; including them dilutes the menu-coverage signal. Delivery's excludes refusals because a
refusal has no chart to fail to paint and is already counted as a rail-share miss — counting
it twice would make delivery partly a copy of rail share, which is the merge Decision 5
forbids. ADR-0013 Decision 3's laundering objection does not transfer: its argument was about
the sentence *"~80% of requests"*, and delivery's sentence is *"of what we served, how much
painted"*.

The excluded count is **published beside** delivery rate so a reader can compose the
end-to-end figure. **We do not mint that combined number.** At P1 exit the either-rail clause
is vacuous — there is no custom rail until P2 — so it is schema for the ≥150 benchmark that
inherits it, and the gate reads deterministic-rail artefacts only.

### 11. Cell 3 is six slots with a ranking-independent floor

| family | slots | stratum | fires when |
| --- | --- | --- | --- |
| discrete-channel overflow / silent row drop | 2 | common path | **any backend** |
| Excel empty-after-filter (353 of 365) | 1 | adversarial | ranking picks Excel |
| Excel pyramid two-groups | 1 | adversarial | ranking picks Excel |
| Excel candlestick chronological order | 1 | adversarial | ranking picks Excel |
| ECharts non-painting boxplot (17) | 1 | adversarial | ranking picks ECharts |

The quota is **requests that exercise a known realised-capability risk**, not requests a
backend merely declares — 18 of the 48 are Excel-reachable, which is not a stress.

**No backend is pinned per request.** Rail share is scored against the union, so backend is
irrelevant to it (ADR-0013 D1); delivery rate genuinely describes what was served, and
pinning would make it describe what we chose instead. The consequence is stated rather than
engineered away: **delivery rate is partly a function of backend ranking policy, which
ADR-0012 Decision 7 deliberately left open.** The two row-drop slots are the floor that
ranking cannot zero out; the other four are the ranking-dependent remainder. The report gives
both.

### 12. Three runs per request, majority per request, and the estimand named

ADR-0013 costed n for *request* sampling and never costed planner stochasticity. Over this
matrix the count is **Poisson-binomial**, not binomial — 4 requests at p=0, 8 in cell 4, 38
elsewhere:

| cell-4 hit p | rest p | E[count] | SD | P(trip) | P(two runs disagree) |
| --- | --- | --- | --- | --- | --- |
| 0.5 | 0.95 | 40.1 | 1.95 | 3.7% | 7.1% |
| 0.5 | 0.90 | 38.2 | 2.33 | 22.7% | **35.1%** |
| 0.3 | 0.90 | 36.6 | 2.26 | 47.0% | **49.8%** |

**Each request is scored three times and its outcome is the majority.** The unit stays one
request, one chart; n stays 50 for the Wilson interval. Scoring three whole corpora instead
would change what n means and reopen which run to believe.

**Majority-of-three shifts the estimand, and that is the point rather than a side effect.**
At cell-4 p=0.5 / rest p=0.90 it moves E[count] from 38.2 to 40.9 and P(trip) from 22.7% to
0.7% — it turns 90% into 97% on the 38 and does nothing to cell 4, where p=0.5 stays 0.5. We
are measuring **the planner's typical routing of a request**, which is what the cost model
claims, rather than one unlucky call. The eight cell-4 slots remain the swing, and that is
stated next to the interval.

Four locks. Decoding settings are the **product's**, never an inflated temperature. Majority
is taken **independently** for rail, for `raw_sql_used` and for delivery. The per-request 2–1
count is **published as a diagnostic** — it is a free measure of planner instability and
feeds Decision 10's third bucket. And cell 1 is **not skipped**: the rule is uniform and 12
wasted calls are acceptable. Total cost is 150 planner calls, once, at P1 exit.

**One finding for ADR-0013's record, not an amendment.** Its n-costing assumed a binomial.
At a fixed heterogeneous composition the variance is strictly smaller — measured, the
Poisson-binomial SD is **1.44× smaller** than the binomial at the same mean — so **Wilson
overstates sampling uncertainty and the gate is harder to clear than costed**. Majority-of-
three narrows it further, since per-request p moves toward 0 and 1. The trip rule is not
reopened; the conservatism is disclosed beside the interval.

### 13. The pre-registration is a tagged, hash-asserted artefact, cut before planner work

`corpus/pre-registration.json` plus a short dated markdown, tagged **`corpus-prereg-v1`**,
and **the harness refuses to run unless the file's sha256 matches the one recorded at that
tag**. ADR-0013 Decision 13's argument applies with equal force here: a freeze nobody can
verify is indistinguishable from not having frozen.

The hashed bytes are the **authoring artefact** — requests (both rewrite versions), dataset
checksums, reference frames including nulls and their `expressible_if` lists, and
authoring-time cell, shape, intent and provenance per request.

**The tag is cut before the first planner-prompt commit**, and the report names both dates.
The hash freezes the file; it does nothing about a prompt written against remembered
requests, and with §13's two engineers a personnel split is theatre. Sequencing is nearly
free because it is already the phase order — the corpus is authored in P0 and the planner is
P1. A disclosed violation of the order is recoverable; an undisclosed one is not.

**On a pin bump between authoring and scoring, score the pin we ship.** Cell 1 is recomputed
**before any request is scored**, mechanically, by intersecting each `expressible_if` list
with the new `vocab.json` union — never by hand. Non-null frames are re-validated against the
new façade in the other direction, because a narrowing bump creates misses and suppressing
those would be as perverse as suppressing a new type. The report names both pins — authoring
`0.5.1` / fixture `34ef451`, and the scoring pin — and every request whose cell moved. Cell
moves are reported **against** the tagged snapshot; they do not rewrite it and they do not cut
a new tag.

### 14. Five reserves, keyed on (cell, stratum)

n=50 is not a round number, it is the only affordable n for the 60-versus-80 contrast.
Measured: n=50 tolerates 13 misses, n=45 tolerates 11, n=40 tolerates 9.

So the tagged file carries **five reserve requests**, drawn in a pre-registered order, each
able to replace only a slot of the **same (cell, stratum)** — cell alone would let a
wide-for-long swap silently break Decision 5. A substitution is a lookup, not a decision.

Scoring a lost request as a miss would charge the planner for our licensing problem. Dropping
it is the fallback when the reserve is exhausted, and the lock on it is that **dropping is
never a choice made after seeing a score**: the trigger is unscoreability discovered before
the run, and the report states the true n and the recomputed Wilson threshold.

### 15. Bucket 2 will read zero, and the report must say why

Cell 2 requires that `raw_sql` **can** carry the shape, so every cell-2 request is a numerator
hit and never enters the escape-reason histogram. No other cell produces a bucket-2 miss.
**ADR-0013 Decision 10's bucket 2 — the transform menu, one of only two levers we own — will
read zero on this corpus by construction.**

That is correct, and ADR-0013 Decision 4 already decided it without spelling out the
consequence: *"a rising `raw_sql_used` rate means the transform menu is under-powered, which
is precisely the diagnosis Decision 10 depends on."* **The menu lever is fed by the rate, not
by the histogram.** The report states this in as many words, because the first reader of an
empty bucket 2 otherwise concludes the menu is fine.

**Expected-empty is conditional, and a violation is news.** If a pre-registered cell-2
frame's `raw_sql` is refused at scoring — a Lock 1 or Lock 2 verdict that moved, or a shape
authored wrong — that request is a **genuine bucket-2 miss and must appear in the
histogram**. It is a finding, not a design artefact.

### 16. Reporting: per-cell counts, never per-cell rates

The cells sort misses into levers. They were never sized as estimators, and publishing rates
for them invites exactly the reading ADR-0013 Decision 9 refused for the point estimate.
Measured widths at 95%: cell 1 at 2/4 spans **[15%, 85%]**; cell 3 at 3/6 spans [19%, 81%];
cell 4 at 4/8 spans [22%, 78%]; even the adversarial stratum at 10/20 spans 40 points.

So: **per-cell counts (k of n), no per-cell rates, no per-cell intervals.** The two strata
carry intervals because they were sized for it.

Alongside them, the pre-registration records the **expected rail outcome per request**,
derived only from the frame — null frame → miss, bucket 1; valid frame → hit; cell 3 is a
rail **hit**, since delivery is the other number. At scoring, **expected versus reported** is
published as a fourth diagnostic, including a surprise hit on a cell-1 request. Among actual
misses, the bucket confusion table is the only check anyone has on whether Decision 10's
histogram is telling the truth: a planner reporting *no chart type in the 48* for a request
whose frame is façade-valid has mislabelled its escape, and an unchecked histogram would send
the named review to the upstream lever for a prompt problem. This is not a second share and
it does not enter the gate. The scorer consumes the escape reason **without depending on where
it is written** — ADR-0013 Decision 11 leaves `escape` placement open.

### 17. Injection cases are outside the 50, and the corpus is disjoint from the benchmark

**Indirect prompt injection through profiled metadata gets its own suite and its own number.**
Under ADR-0013's rules a successful injection that escapes to the custom rail scores as a
bucket-3 planner-quality miss, indistinguishable from a prompt that was merely not good
enough — so injection cases would contaminate the gated number with a security result, and
there is no third instrument that would catch them. The 50 slots are affordable only because
nothing is wasted, and PRD §14 already treats this as first-class. Cell-4(iv) is **not** an
injection slot: it is profile-to-plan under dirty column names (ADR-0011's untrusted subtree),
and it fails the gate only if the planner escapes.

**The pressure corpus and the ≥150-case benchmark are disjoint request sets sharing a tagging
schema** — intents, shapes, stress cell — so a reader can compare their composition. The 50 is
pre-registered and scored **once**; the 150 is scored every release. A 50 nested inside the 150
would be re-scored continuously and the planner would be tuned against it, and pre-registration
would die at the first look. The cost is authoring roughly 200 requests rather than 150; that
is the price of a gate fixed before anyone saw a number.

## What this amends

### ADR-0013 Decision 8 — "representative stratum" and "the nasty 20"

**Dated note, 2026-08-28 (#7, ADR-0014).** Decision 8's prose calls the 30 the
*representative* stratum and the 20 the *nasty* ones. After examining every available source
(Context), no corpus measures request frequency in the wild, so *representative* asserts an
external population that nothing we can reach supplies — and Decision 8's own gloss, *"how the
common majority story is read"*, is already the accurate description. The strata are renamed
**common-path** and **adversarial** in `CONTEXT.md` and in Decision 1 above.

**This changes no decision in ADR-0013.** The 30/20 ratio, scoring on the pooled 50, reporting
both strata beside the pooled number, the Wilson 95% lower bound trip at <60%, and
pre-registration before scoring are all untouched.

Decision 12 above additionally records — as a finding, not an amendment — that ADR-0013's
power arithmetic assumed a binomial, while a fixed heterogeneous composition is
Poisson-binomial with strictly smaller variance (measured: 1.44× smaller SD). The trip rule
stands; the conservatism is disclosed beside the interval.

### ADR-0013 Decision 7 — "different composition" is now specified

**Dated note, 2026-08-28 (#7, ADR-0014).** Decision 7 says the pressure corpus and the
benchmark have *"different n, different composition and different purposes"* and leaves the
relation between them open. Decision 17 above fixes it: **disjoint request sets, shared
tagging schema.**

**Dated note, 2026-09-20 (#170,
[ADR-0029](0029-the-eval-benchmark-is-a-frozen-150.md)).** Decision 17's disjointness
stands. The 150's **mix** is ADR-0029's 120/30 matrix, not 3× this ADR's table.

## Consequences

**The corpus, not the planner, sets most of the gate's difficulty — and that is now written
down.** With K=4 the other 46 must hit 80.4%, which is the hypothesis itself on everything
that is not a deliberate impossible request. Anyone re-reading the gate result can see the
budget that produced it.

**Three of the four obvious corpora do not appear in the corpus.** Quda is absent despite
being the best-registered and most task-appropriate source; NLV appears only as a phrasing
reference; nvBench 2.0 appears in three slots out of fifty. Each exclusion has a specific
cause recorded in Decision 8, because the next person to look at this will start by proposing
Quda.

**Bucket 2 reads zero and that is a designed result, not a measurement.** Decision 15 makes
the report say so. Without it the single most likely misreading of the gate's output is that
the transform menu needs no work.

**Delivery rate is partly a function of an undecided ranking policy.** Decision 11 declines to
engineer that away and instead gives the number a ranking-independent floor and says which
part is which. When ADR-0012 Decision 7's ranking question is settled, the delivery number
becomes comparable across releases; until then it is comparable only against its own floor.

**`corpus/` carries mixed licences, and that is a NOTICE rather than a relicensing.** nvBench
1.0 query text is MIT; its tables descend from Spider and are CC BY-SA 4.0 — attribution and
share-alike on those files, not relicensed under the repo's Apache-2.0. The NOTICE lands
before the tag, not after.

**Nothing here is implementable today, and none of it is blocked.** There is no planner and no
`pyproject.toml`; like ADR-0010, ADR-0012 and ADR-0013, the ADR text is the artefact. The
corpus is authored in P0 and cannot be scored before P1 exit.

## Alternatives rejected

**Leave "nasty" as one undifferentiated bucket.** Rejected in Decision 2. The ticket's own
axes span requests that miss the rail and requests that sail through it and fail elsewhere;
pooled into one bucket, the gate's outcome is set by an unexamined mix, and the two
non-gated numbers lose all power.

**Quda as the request spine.** Rejected in Decision 8. CC BY-NC-SA 3.0 cannot be vendored into
an Apache-2.0 repo destined to go public and consumed by a commercial product, and
pre-registering Quda IDs to fetch text at scoring would distribute the same material through
the report.

**Inherit the intent mix from Quda's task distribution.** Rejected in Decision 9. Quda's mix
is 20 × 2 × 10 × 2 by protocol design with tasks presented as prompts — inheriting it would
publish an elicitation artefact as a traffic estimate.

**nvBench 2.0 as the spine for the 30.** Rejected in Decision 8 on measurement: 0 of 7,505
records carry a single gold interpretation. Cell 0 would be 22 on paper and 0 in fact, and an
ambiguity budget inside an all-ambiguous corpus is not a budget.

**NLV Corpus as the spine.** Rejected in Decision 8. Its utterances were elicited by showing
participants a chart, so the chart type is inside the request — the exact contamination
Decision 4 and Decision 6 exist to prevent — and three datasets cannot carry Decision 5.

**Hand-author the 30 against nvBench tables.** Rejected in Decision 8. It is the labelling
pass ADR-0013 Decision 2 refused, one step removed: we would be authoring requests while
knowing what the grammar covers, and the share would measure our restraint. The stored
fluency diff is what makes the rewrite route auditable in a way this is not.

**A fourth cell-1 intent: layered distribution.** Rejected in Decision 3. `Boxplot` carries
*compare distributions*, and the absence of layers is ADR-0002 Decision 8's — ours — so the
miss would be diagnosed as an upstream request when the lever is reopening our own decision.

**K = 5, adding a dynamic-`PIVOT` request to populate bucket 2.** Rejected in Decision 15. It
moves the required rate on the rest from 80.4% to 82.2% and discretionary misses from 9 to 8,
spending gate headroom to populate a bucket whose signal already arrives through
`raw_sql_used` — and buying one observation of a shape the map already waits on that rate for.

**Proceed on nvBench 2.0's inferred licence.** Rejected in Decision 8. The OpenReview paper
stamp and the site footer disagree, and the repository's own License section is inside an
HTML comment — so vendoring would take a redistribution risk into a public Apache-2.0 repo
feeding a commercial product, to save three hand-authored sentences. The fallback costs
almost nothing, which is what makes the risk unjustifiable rather than merely unwise.

**Pin a backend per request.** Rejected in Decision 11. Rail share is scored against the union
so it would change nothing there, and it would make delivery rate describe what we chose
rather than what was served.

**Publish per-cell rates with intervals.** Rejected in Decision 16 on arithmetic: cell 1 at
2/4 spans [15%, 85%].

**Injection cases inside the gated 50.** Rejected in Decision 17. A successful injection scores
as a planner-quality miss, conflating security with grammar coverage in the one histogram the
gate's remedy reads.

**The 50 as a subset of the ≥150 benchmark.** Rejected in Decision 17. The 50 is scored once;
a nested 50 is re-scored every release and tuned against, and pre-registration becomes theatre
at the first look.

**A single scoring run.** Rejected in Decision 12. At 90% planner reliability two runs of the
identical system disagree on the verdict about a third of the time.

## Evidence

Every number in this ADR is reproducible. Probes were run at Flint `0.5.1` / fixture commit
`34ef451`, DuckDB 1.5.5.

- **Vocabulary counts** (48 union; 36/37/22/38/18 per backend; 9 on neither Vega-Lite nor
  Plotly; 8 single-backend; 26 declared channels; 15 of 48 with no fixture) —
  `prototypes/facade-codegen/build/vocab-0.5.1.json` against
  `prototypes/flint-embed/build/fixtures/`. The 705-fixture corpus uses 33 chart types and 23
  of the 26 channels (`angle`, `opacity`, `radius` never appear) and is concentrated: Bar 166,
  Scatter 115, Line 78 — 51% of 705.
- **Transform-escape reachability** (the Decision-2 Context table) — `extract_statements` and
  `json_serialize_sql` per ADR-0008 Decision 7. Bare `PIVOT` and `PIVOT` in a subquery both
  parse as two statements (`CREATE`, `SELECT`); `PIVOT … IN (…)`, `UNPIVOT`, `UNION ALL`,
  `strptime`, window functions, `QUALIFY` and recursive CTEs all parse as one `SELECT` naming
  only `source`.
- **Gate arithmetic, Poisson-binomial variance, and per-cell interval widths** — Wilson score
  intervals and exact Poisson-binomial convolution over the Decision 2 matrix.
- **nvBench 1.0** — `TsinghuaDatabaseGroup/nvBench`, MIT asserted in README: 7,247
  visualisations, 25,762 NL queries, 152 databases; 3,693 queries (14.3%) name no mark, over
  146 databases; gold chart of that subset Bar 65.4% / Line 11.2% / Pie 9.3% / Scatter 5.6% /
  Grouping Scatter 3.7% / Stacked Bar 3.3% / Grouping Line 1.7%.
- **nvBench 2.0** — `HKUSTDial/nvBench-2.0`: **7,505** records across `train`/`dev`/`test`
  (the repo's `data/readme.md` claims 7,878 — the released files do not match the stated
  counts, which is itself a reason the licence should be asserted before use); 794 distinct
  tables; **0** records with one gold interpretation; degrees 2:3,388 / 3:1,544 / 4:1,483 /
  5:1,090; 1,224 queries (16.3%) name no mark over 562 tables. The README's License section is
  inside an HTML comment.
- **Quda** — CC BY-NC-SA 3.0 per `freenli.github.io/quda`; design is 20 participants × 2
  tables × 10 Amar-et-al. tasks × 2 queries = 800 target, 920 expert queries, 13,115 validated
  paraphrases, 36 tables across 11 domains; deliberately low-composition and
  context-independent, collecting *objectives* rather than *actions*.
- **Spider** — CC BY-SA 4.0 per `yale-lily.github.io/spider`; nvBench 1.0's databases descend
  from it.
- **Pin currency** — upstream `microsoft/flint-chart` CHANGELOG lists 0.5.1 (2026-08-13) as
  the latest release with an empty `[Unreleased]` section, so Decision 13's bump procedure has
  no live trigger at the time of writing.

## What this feeds

- **The corpus authoring itself** — past the map's edge. What remains is execution against the
  freezes above: the designed nine-intent counts across the 30, the four cell-1
  `expressible_if` lists, the cell-2 escape-shape assignments, `corpus/`'s layout and NOTICE,
  and the five reserves keyed on (cell, stratum). The freeze fields are listed in the appendix
  so a later implementer does not re-derive them, and that list is **not** a second grammar.
- **The scorer harness** (ADR-0013 Decision 12) inherits the hash assertion (Decision 13), the
  majority-of-three rule and its three independent majorities (Decision 12), the three
  denominators (Decision 10), the per-cell-counts rule and the expected-versus-reported table
  (Decision 16), and the bucket-2 sentence (Decision 15).
- **The planner-output contract** (map fog) gains a consumer for its escape reason that must
  work without knowing where the value is written (Decision 16).
- **The ≥150-case benchmark** (P0.10) inherits the tagging schema and the disjointness rule
  (Decision 17).
  **Settled — 2026-09-20 ([#170](https://github.com/thearcscode/chartagent/issues/170),
  [ADR-0029](0029-the-eval-benchmark-is-a-frozen-150.md)).**
- **`pivot` and `window` graduation** (map fog) is fed by the common-path `raw_sql_used` figure
  (Decision 10), which Decision 15 names as the menu lever's only evidence.

## Related

- ADR-0013 for the gate itself; this ADR decides only what the corpus is.
- ADR-0012 Decision 7 for the open backend-ranking question that Decision 11 declines to work
  around.
- ADR-0002 Decision 8 (layers out of scope) for why layered distribution is not a cell-1
  intent.
- ADR-0011 Decision 10 (the untrusted subtree) for what cell-4(iv) actually stresses.

## Appendix — the pre-registration's freeze fields

Per request: `id`, `source` (`nvbench1` | `nvbench2` | `authored`), `source_id`,
`query_original`, `query_rewritten`, `stratum` (`common_path` | `adversarial`), `cell` (0–4),
`cell_family` (for cells 3 and 4), `intent` (one of the nine, or an uncarryable name for cell
1), `shape` (`long` | `wide` | `nested` | `wide_sparse`), `dataset_path`, `dataset_sha256`,
`reference_frame` (a façade-valid input frame, or `null`), `expressible_if` (cell 1 only),
`ambiguity_degree` (cell-4(ii) only), `expected_outcome` (`hit` | `miss`), `expected_bucket`
(misses only).

Per file: `flint_version`, `fixture_commit`, the cell × stratum matrix, the shape split, the
designed intent counts, and `reserves` — five full request records each carrying the
`(cell, stratum)` it may replace and its draw order.
