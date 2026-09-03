# 12. Capability is declared or realised, and the library owns only the declared half

- **Status:** Accepted
- **Date:** 2026-08-27
- **Settled on:** [#9](https://github.com/thearcscode/chartagent/issues/9)
- **Builds on:** ADR-0001 (pin Flint; compile in the client; no fork and no modification),
  ADR-0002 (the input frame *is* the spec), ADR-0005 (`bind` is the public seam; `backend`
  is a required kwarg), ADR-0006 (the server binds, the browser compiles), ADR-0009 (what
  the façade validates; the per-backend vocabulary)
- **Amends:** ADR-0005 Decision 10, ADR-0006 Decision 8, ADR-0009 Decisions 11 and 15 —
  recorded as dated errata in place and listed under *What this amends*

## Context

The ticket that opened this asked us to author a `RendererAdapter` protocol and a
`CapabilityProfile`. ADR-0001 and ADR-0002 had already removed that job, and ADR-0009 then
removed most of what replaced it: the pin ships a machine-readable per-backend chart-type
vocabulary, the façade is generated from it, and `bind` already raises
`BackendCapabilityError` when a frame names a chart type the requested backend does not
declare.

What was left is the question a router actually has to answer — **can this chart be
produced, for this backend, from this data?** — and it turns out that question has two
halves that behave completely differently, which is the whole content of this ADR.

### The measurement that split it

All 705 fixtures through all five pinned assemblers
(`prototypes/backend-capability/probe.mjs`, Flint 0.5.1):

| backend | accepted | chart type undeclared | faceting | everything else |
| --- | --- | --- | --- | --- |
| vegalite | 705 | 0 | 0 | 0 |
| plotly | 705 | 0 | 0 | 0 |
| echarts | 667 | **38** | 0 | 0 |
| chartjs | 595 | **110** | 0 | 0 |
| excel | 365 | 146 | 102 | **92** |

**For four of five backends the pin's declared chart-type list is not merely sufficient, it
is exact.** ECharts refuses 38 fixtures and the list predicts 38; Chart.js refuses 110 and
the list predicts 110; Vega-Lite and Plotly refuse nothing at all. In no backend was a
fixture with an undeclared chart type ever accepted, so the list is sound as well as
complete at that grain.

**Excel is the entire problem, and it is not one problem.** Its 340 refusals are three
different kinds, and only the first is visible to the vocabulary.

### The half that cannot be predicted

Mutating **only the rows**, with the spec untouched, over each backend's accepted set:

| backend | accepted today | refuse on zero rows | on one row | on reversed order |
| --- | --- | --- | --- | --- |
| vegalite, echarts, chartjs, plotly | 2672 | **0** | **0** | **0** |
| excel | 365 | **353** | **19** | **2** |

An empty filter result breaks 353 of the 365 Excel charts that work today. A pyramid chart
refuses at one row (*"requires exactly two groups… found 1"*). A candlestick refuses when
the rows arrive in the other order (*"requires x values sorted in strictly increasing
chronological order"*).

**A saved Excel chart can bind on Monday and refuse to compile on Tuesday, on new data
alone.** That is a property of the `$0.00` zero-LLM refresh pillar, not a footnote to
capability, and no other backend has it.

Mirroring those checks in Python is the obvious response and it is not available. They are
`assembleExcel`'s own type inference over the bound rows; reproducing it is a second
compiler, which `CONTEXT.md` lists under *Avoid* and which ADR-0006 Decision 8 already
rejected once for `openpyxl`. Measuring an accept-list of `(chartType, shape)` pairs instead
fails for a sharper reason: **15 of those pairs change verdict on the rows**, so the list
would not be incomplete, it would be wrong — and wrong precisely on refresh, which is the
one path with no human in it.

## Decision

### 1. Capability is two things, and they are not two grains of one thing

**Declared capability** is what the pin says a backend can draw: pin-derived, decidable in
CPython, and settled before any data is read. **Realised capability** is whether the
assembler accepted the document and whether the output actually painted: client-side, after
compile, and on Excel a function of the rows.

They are not coarse and fine versions of the same predicate. Declared capability is a
property of the *spec*; realised capability is a property of the *run*. A model that treats
the second as a more precise form of the first would license predicting it, which is what
the measurement above forbids.

**The library owns the declared half and refuses the other.** `bind` succeeding never means
the chart compiles; on Excel it frequently does not.

### 2. Declared capability is the vocabulary, and nothing is added to `__all__`

It is `(backend, chartType)` read off the committed `vocab.json` — 36 chart types for
Vega-Lite, 37 for ECharts, 22 for Chart.js, 38 for Plotly, 18 for Excel, 48 in union — which
ADR-0009 already generates and `chartagent.vocabulary(backend)` already returns.

**No capability layer, no `CapabilityProfile`, and no `supports(backend, chart_type)`
predicate**, which would be that list under a second name with a second chance to drift.
This ADR adds no public verb and no public type. It decides what an existing raise *means*
and who is expected to act on it.

### 3. One named rule beyond the type list: Excel plus a facet channel

`bind(..., backend="excel")` on a frame carrying a `column` or `row` encoding raises
`BackendCapabilityError`. Without it the planner emits a faceted Excel frame, `bind` accepts
it, and the browser refuses — 102 fixtures deep, at the far end of a request.

The rule is admitted **not** because it "lives in the spec" — on a weak test most of Excel's
other preconditions look spec-resident too — but because it is expressible **entirely in
vocabulary we already ship**: two channel names from ADR-0009 Decision 5's closed 26-name
global export, against one backend name. No type inference, no row reading, no axis
analysis. It is Decision 2's `chartType ∈ this backend` one level down, and that is the line
every future candidate is measured against.

Measured: the 102 faceting refusals are stable across rows emptied, rows shrunk to one, rows
reversed, every value rewritten as a string, and `semantic_types` deleted outright. The rule
reads the encoding key set and nothing else.

### 4. The rule is bound to a biconditional, not to grep

The pin declares no facet flag anywhere — `isExcelSupported` is one line,
`flintChartType in EXCEL_TYPE_MAP` — so this rule is hand-written, which is the shape
ADR-0009 Decision 9 refused for the `options` bag. What makes it survivable is that its
truth is asserted against the corpus rather than remembered by a person:

| assertion | today |
| --- | --- |
| faceted Excel frames that refuse for faceting | 102 |
| faceted Excel frames accepted by Excel | **0** |
| faceting refusals with no `column`/`row` channel | **0** |

The remaining 12 faceted frames refuse earlier, for an undeclared chart type, which
Decision 6's order already resolves.

**The assertion lives on `fixtures-invariant`** (ADR-0004), which already compiles all five
backends on every commit and already carries the dirty-input count. It needs no oracle and
no render step, because this throw is `assembleExcel`'s. `flint-bump` inherits it when the
pin moves. **A bump that teaches Excel to facet therefore fails loudly**, instead of leaving
us silently refusing charts Flint has learned to draw — which is the failure mode a
hand-written rule is otherwise guaranteed to reach.

### 5. No Python mirror of `assembleExcel`, and no measured accept-list

Excel's remaining **92** refusals — axis types, colour-grouped boxplots, continuous
grouping, waterfall totals, unlegended detail series, chronological order, empty tables —
stay **realised capability**: reported by the client after compile, never predicted by the
library. (194 is the count *before* Decision 3: 102 faceting plus these 92 were together
what the vocabulary could not see. The facet rule takes the first group; this decision
declines the second.) Both available alternatives are rejected in *Alternatives rejected*
below.

This is the decision most likely to be re-litigated by someone looking at a support ticket,
so the reason is stated positively: **the library declines to answer a question it can only
answer by becoming a second implementation of the thing it pinned in order not to
maintain.**

### 6. `BackendCapabilityError` gains a `kind`, and the check order gains a step

Three raise sites now exist, and a caller should not have to match on message text — the
same argument that gave `SpecVocabularyError` its `kind` in ADR-0009 Decision 12:

```python
kind: Literal["chart_type", "property", "facet"]
```

Plain strings at runtime, matching `SchemaDriftError.stage` and `RawSqlRejectedError.reason`
rather than introducing a `StrEnum`. The facet raise carries the offending channel names as
a tuple, following ADR-0009 Decision 11's rule that an error carries every offender of its
own kind.

ADR-0009 Decision 11's fixed order becomes eight steps, the new one inserted between the
chart-type check and the property model:

1. shape — the 5-key envelope, inline `data`, `theme_spec: null` → `SpecShapeError`
2. `chartType` ∈ the pin union
3. channel names ∈ the global export
4. encoding-object keys
5. `theme_spec` preset / `semantic_types` values
6. `chartType` ∈ **this** backend → `BackendCapabilityError`, `kind="chart_type"`
7. **Excel + `column`/`row` → `BackendCapabilityError`, `kind="facet"`**
8. `chartProperties` against the (backend, chartType) model

Step 7 sits after step 6 so that the 12 faceted-and-undeclared frames report the chart type,
which is the more actionable of the two facts: a chart type Excel will never draw is not
repaired by dropping the facet.

### 7. Backend selection is a filter, never a fallback, and never a ranking

`bind` has no router — `backend` is a required kwarg (ADR-0005 Decision 2). The planner
picks from declared capability *before* it emits a frame, so an unsupported pair should not
reach `bind` at all.

When one does, it means a hand-authored frame, a direct API caller, or **a narrowing pin
bump** — and all three want a refusal naming the backend. **Silent substitution is
rejected**: it would make "one stored frame, five backends" false in the opposite direction
from the one ADR-0005 Decision 2 guarded, and it would hide the bump case entirely, which is
the one that needs a human. Studio's backend switcher (#27) is the same filter drawn in the
UI, not a runtime fallback.

**Ranking among the backends that qualify is not decided here.** It depends on the
instruction, the quality dial and Studio's target, none of which exist yet, and it belongs
to the planner-output contract.

**Erratum — 2026-09-03 ([#93](https://github.com/thearcscode/chartagent/issues/93),
ADR-0021).** This decision closed with *"ADR-0006's ECharts-as-default-web-target is
Studio's choice, not this model's"* — struck. ADR-0006 never decided that (the citation was
wrong), and ADR-0021 found **Studio has no standing target at all**: it is a plain caller of
the same ranking a script gets. The ranking question this decision left open is answered by
ADR-0019 (the fixed list) and ADR-0021 (`requested_backend`, the two-tier composition) —
"Studio's target" was never one of the real inputs.

### 8. The theme gap is an advisory, not capability

`theme_spec` is silently ignored by ECharts and Chart.js — byte-identical output with and
without a theme across three presets. It stays what ADR-0005 already made it: the
`theme_spec_ignored` advisory on `Envelope.warnings`, with Studio applying its palette after
`assemble*` (ADR-0006 Decision 7).

**Erratum — 2026-09-03 ([#93](https://github.com/thearcscode/chartagent/issues/93),
ADR-0021).** Dropped *"and ECharts is Studio's default web target"* from the opening
sentence, for the same reason as Decision 7's erratum above — the advisory earns its place
on the measurement alone, on whichever backend a request actually binds to.

Capability asks *can this be drawn*; theming asks *how it looks*. The chart draws — it draws
unthemed. Folding the two together would make a cosmetic gap raise the same error class as
Excel refusing a pyramid chart, and would put a caller in the position of catching an
exception to learn that their colours did not apply.

### 9. Applicability is realised capability, exposed and never a gate

ADR-0009 Decision 15 left this ticket the 161 of 317 vocabulary entries whose `check()` /
`isApplicable()` reads the data rows. It needs no new machinery: a declared key with no
effect — `colorScheme` set with no `color` channel — is neither a vocabulary error nor a
capability refusal. It is realised capability, evaluated in the client.

It stays the `data_dependent` flag on `vocabulary()` (ADR-0005 Decision 8), which #27's form
already renders as *"checked at compile"*. **Exposed, never enforced** — promoting it would
repeat the mistake ADR-0009 Decision 4 made with `min`/`max` and Decision 14 refused for
`dependencies`.

### 10. Compiles but does not paint is a pin defect, and it is unmonitored

**17 of 667 ECharts options do not paint at 0.5.1** — the boxplot fixtures, where Flint
emits a `custom` series with no `renderItem`, which the compiler accepts and ECharts cannot
draw — plus 50 more that emit runtime warnings
(`docs/research/rasterisation-options.md`, #22).

This is a third predicate, and it is neither vocabulary nor capability: it is a defect in
the pinned release. It is **not routed around** — a router that steers away from a specific
upstream bug encodes that bug into our behaviour permanently, and outlives the fix.

**And the count is unmonitored. Say so plainly:** *17 ECharts boxplot options do not paint
at 0.5.1; nothing will notice if that number changes until a render step exists.*
`fixtures-invariant` and `flint-bump` both compile and neither paints, so neither can see
it — claiming otherwise would create a gate everyone believes in and nobody runs. The P2
review gate inherits these 17 as its first known-failing set, because it is the first thing
in the system that looks at a real render. No allowlist ships in the library (ADR-0004,
ADR-0009).

### 11. Phase-2 validation is placed here and named elsewhere

Field existence and cardinality caps against a data profile are ours, because a spec can be
grammatically valid, within declared capability, and still unrenderable against a given
dataset. Their **placement** is fixed here: **after the transform, before the envelope,
backend-free, profile-derived, and explicitly not `BackendCapabilityError`.** Capability is
pin-derived and data-free; Phase-2 is profile-derived and backend-free. Different inputs,
different times, different errors.

**The thresholds are not set here and neither is the error name.** Field existence already
raises `SchemaDriftError`; cardinality has no error because it has no threshold, and naming
one now would widen `__all__` — which Decision 2 refuses — with a promise about a check
nobody has specified. The error ships with the thresholds that raise it. ADR-0011 fixed the
inputs (`bucket`, `distinct`, `saturated`, `null_rate`, saturation at `N = 1001`); the
thresholds stay in the map's *Phase-2 validation thresholds* entry.

One consequence worth stating: because Phase-2 runs after the transform, **zero-LLM refresh
runs it too** — which is correct, since on a refresh the data is the only thing that
changed.

## What this amends

Recorded as dated errata in place, so a reader of the original decision is not required to
find this ADR to learn what changed.

| Document | What moved |
| --- | --- |
| **ADR-0005** D10 | `BackendCapabilityError` gains `kind: Literal["chart_type", "property", "facet"]` and a third raise site (Decision 6) |
| **ADR-0006** D8 | `isExcelSupported()` gates the **declared chart type** — 146 of 340 — not "Excel will draw this" (Decision 3) |
| **ADR-0009** D11 | The fixed order becomes eight steps: facet is step 7, `chartProperties` step 8 (Decision 6) |
| **ADR-0009** D15 | Excel faceting is no longer an open illustration of the seam — it is Decision 3's named rule |

## Consequences

**Excel is a different kind of backend, and the docs have to say so once rather than
implying it five times.** It is the only backend whose capability depends on the data, the
only one where `bind` succeeding is weak evidence, and the only one where a refresh can
break a chart nobody edited. ADR-0003 already made it Tier-1-forever for the review gate and
ADR-0006 already made it a workbook rather than a native chart; this is the same fact
arriving a third time.

**`CONTEXT.md`'s zero-LLM refresh entry gains an Excel caveat**, because 353 of 365 is a
property of the pillar and not a detail of this model.

**The planner cannot emit an Excel frame with a facet channel**, and #27's form must gate
the facet affordance on the selected backend rather than only gating Excel on
`isExcelSupported()`. Both are filters over the same declared set.

**A frame that binds on one backend can refuse on another, and now for three reasons rather
than two.** #27's backend switcher presents all three as a capability conversation, not as
corruption — the `kind` is what lets it say which.

**Nothing in this ADR is implementable today and none of it is blocked.** The repo still has
no `pyproject.toml`; like ADR-0010, the ADR text is the only artifact, and the corpus
assertion lands when `fixtures-invariant` does.

## Alternatives rejected

**A Python mirror of `assembleExcel`'s preconditions.** Rejected. It is a second compiler by
any definition — Flint's type inference, re-implemented, kept in step by hand across a pin
we deliberately do not control. ADR-0001 paid a real price to avoid maintaining a renderer;
maintaining a shadow of one backend's validator collects the same cost with none of the
output.

**A measured `(chartType, shape)` accept-list per pin.** Rejected, and not for being
incomplete. **15 of Excel's 92 non-facet refusals change verdict on the rows alone**, so a
list measured against the corpus is *wrong* for any dataset that is not the corpus — and
wrong in the direction that matters, telling a caller a chart will draw when the day's rows
say otherwise. It would also be an allowlist in the library, which ADR-0004 and ADR-0009
have now each refused once.

**A `supports(backend, chart_type)` public predicate.** Rejected as surface without content:
`vocabulary(backend)` already returns exactly that list, and a second accessor over the same
data is a second thing to keep true.

**Silent re-routing to a backend that can draw the chart.** Rejected in Decision 7. It
converts an explicit capability question into an invisible substitution, and it would
swallow the narrowing-bump signal that ADR-0005 Decision 12 exists to make loud.

**Treating the 17 non-painting boxplots as capability.** Rejected in Decision 10. They are a
defect in a pinned dependency, not a statement about what ECharts can draw, and encoding
them as capability would make the workaround outlive the bug.

## What this feeds

- **[#10](https://github.com/thearcscode/chartagent/issues/10)** gets the vocabulary split
  it needs for a denominator: *rail routing* (deterministic vs custom) is what it measures;
  *backend selection* is a different decision and not part of its share.
- **[#7](https://github.com/thearcscode/chartagent/issues/7)** gains a composition
  constraint: a pressure-test corpus that is backend-blind will over-report Excel failures
  as planner failures.
- **#27's form** gates faceting on the backend, not only Excel on `isExcelSupported()`.
- **The P2 review gate** inherits the 17 boxplots as its first known-failing set, and is the
  first thing in the system that can see them.
- **The planner-output contract** (map fog) inherits backend *ranking*, which Decision 7
  deliberately leaves open.

## Related

- Probe and every number above: `prototypes/backend-capability/probe.mjs`, run from
  `prototypes/flint-embed`, Flint 0.5.1, fixture commit `34ef451`.
- The non-painting finding: `docs/research/rasterisation-options.md`
  ([#22](https://github.com/thearcscode/chartagent/issues/22)).
