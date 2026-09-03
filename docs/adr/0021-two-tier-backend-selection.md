# 21. Two-tier backend selection: `requested_backend`, then the ranking — and Studio carries no override

- **Status:** Accepted
- **Date:** 2026-09-03
- **Settled on:** [#93](https://github.com/thearcscode/chartagent/issues/93)
- **Builds on:** ADR-0019 (the fixed ranking `vegalite > echarts > plotly > chartjs > excel`;
  "a backend named in the instruction wins over the list", mechanism left open; the two-call
  planner shape and its `code: filter + rank` step), ADR-0020 (`create_chart`'s signature has
  no `backend=`; `bind`'s errors surface un-wrapped through `create_chart`), ADR-0012
  Decision 7 (backend selection is a filter, never a fallback, never a ranking — ranking left
  open pending "the instruction, the quality dial and Studio's target"), ADR-0006 (all five
  backends reachable, `backend` a validated request field with no hardcoded default — this
  ADR needs no correction, it never claimed a default)
- **Amends:** ADR-0012 Decisions 7 and 8 (the "ECharts is Studio's default web target"
  citation — struck; misattributed to ADR-0006, which never decided it). Prose errata, not
  reopening any decision, on ADR-0001 (Decision 5's envelope-pick aside; the `theme_spec`
  motive), ADR-0002 (the palette-precedence caveat), ADR-0003 (the fidelity argument for
  browser rasterisation; the `vl-convert` rejection), and ADR-0005 (`theme_spec_ignored`'s
  motive; the rejected `backend="echarts"` default) — each corrected in place with a dated
  erratum paragraph. PRD's "ECharts remains the default web target" line — struck, was never
  an ADR decision.
- **Leaves open:** the prompt renderer's actual schema for step 1's tagged union — #92's
  build, this ADR only fixes the shape `requested_backend` must match; a create-time backend
  picker as a UI affordance distinct from #27's view/bind switcher (Not yet specified on the
  map).

## Context

ADR-0019 fixed *that* a named backend wins over the ranking and *that* Excel is never chosen
by the ranking. It deliberately left three things to this ticket: **where** the override is
recognised, **how** Studio's stated preference for ECharts (PRD, ADR-0001, ADR-0002, ADR-0003,
ADR-0005 all repeat some form of "ECharts is the default web target") composes with the
ranking, the **exact** disclosure wording ADR-0019 Decision 4 requires, and what
`backend_forced` in `tools/score_corpus.py` should mean now that a ranking exists.

The first question the grilling session settled turned out to invalidate the framing of the
second: **Studio has no standing backend preference at all.** It is not, in any decision that
actually made it, an ECharts product — every ADR that said so was repeating an unexamined PRD
line, never citing a decision that established it. This closes the "Studio's target" question
by dissolving it rather than answering it, and reopens (as prose errata, not as decisions) five
ADRs that carried the assumption forward.

The second finding is architectural: step 2's `chartProperties` is validated against one of 151
generated `(backend, chartType)` models (ADR-0009), so **the backend must be fixed before step
2 runs.** Whatever mechanism resolves an override has to land in ADR-0019's `code: filter +
rank` step, between the two model calls — not after either one.

## Decision

### 1. Two tiers, and Studio is a plain caller

```
requested_backend (if present) ──▶ survives the declared-capability filter? ──▶ chosen
        │ no                                                    │ yes
        ▼                                                       ▼
BackendCapabilityError                                       chosen = requested_backend
(raised here, step 2 never runs)

no requested_backend ──▶ rank filter-survivors: vegalite > echarts > plotly > chartjs > excel
                          ──▶ chosen = first survivor
```

**Tier 1** is `requested_backend` (Decision 2) if step 1 emitted one, checked against the
declared-capability filter on its own. **Tier 2** is ADR-0019 Decision 3's fixed ranking,
applied only when tier 1 is absent, among backends that survive the filter. There is no tier
3: **Studio passes nothing.** A direct script and Studio planning the same unnamed bar chart
both land on the ranking's first survivor — today, Vega-Lite. Studio's backend-switcher (#27)
stays what it already was: a view/bind control on an already-saved frame — pick a different
backend, re-`bind` the stored frame against it — never a re-plan, and it does not feed
`requested_backend`. A create-time backend picker, choosing before the first plan, is a
different affordance; #27 is not loaded with it, and it stays fog on the map until someone
specifies it.

### 2. `Fragment.requested_backend: Backend | None` — extraction only

Step 1's tagged union (ADR-0019 Decision 2, widened again by ADR-0020 Decision 3 for
`UnanswerableInstructionError`) gains a fourth field on the `Fragment` member:

```python
class Fragment(BaseModel):
    chart_spec: ...          # the judgement — chart type, encodings
    x_chartagent: ...        # transform, semantic_types
    requested_backend: Backend | None   # extraction, not a judgement
```

**Extraction only.** The model reads the *whole* instruction to make its chart-type and
encoding judgements anyway; `requested_backend` asks it to additionally note, mechanically,
whether that instruction named one of the five backends by name — "as a vega-lite chart",
"make it interactive in the browser" implying a web backend is a judgement call the model is
already positioned to make and code is not. It is typed against the existing closed `Backend`
literal, so a hallucinated name fails façade validation rather than being trusted. It **never
rides on the stored `InputFrame`** — it is consumed by the filter step and discarded, the same
treatment `chart_spec.chartType` already gets before it becomes part of the frame.

Rejected mechanisms, both from ADR-0019's original three candidates:

- **A code pre-pass (regex/keyword scan) over the instruction string.** Brittle against
  ordinary phrasing variety, aliases, and typos, and it duplicates judgement step 1's model is
  already paying for.
- **A caller argument for typed text.** A caller who already knows the backend out of band
  doesn't need text parsed at all — that case is Decision 1's tier 1 check plus Decision 4's
  confirmed absence of a `backend=`/`default_backend=` kwarg, not a new channel for text.

The full instruction still reaches step 1 unmodified; code cannot read English, so this field
is the model's typed note back to code about what it read.

### 3. A failed filter raises `BackendCapabilityError` at the filter step — no retry, no fall-through

When `requested_backend` fails the declared-capability filter (the ticket's own example: "a
Sankey diagram in Vega-Lite" — Sankey is ECharts-exclusive), the shortest correct path wins:

**Raise `BackendCapabilityError` right there, between step 1 and step 2.** Same error, same
`kind` vocabulary (`chart_type`, `property`, `facet`) `bind` already raises it with — this is
not a new error type, just an earlier raise site for an existing one. `kind="chart_type"`
covers the Sankey case; `kind="facet"` covers Excel-plus-`column`/`row` the identical way
(ADR-0012 Decision 6's biconditional). **`kind="property"` cannot fire here** — it needs
`chartProperties`, which is step 2's output and does not exist yet; a property-level capability
miss still only surfaces through `bind`, exactly as ADR-0020 Decision 4 already covers ("`bind`'s
own errors surface un-wrapped" through `create_chart`).

Three things this deliberately does not do:

- **No retry.** Step 1 produced a well-formed, self-consistent answer — a real chart-type
  judgement paired with a real backend name, both correctly extracted. Retrying asks the same
  question again and gets the same, correct, incompatible answer.
- **No fall-through to the ranking.** Silently swapping in the first ranking survivor when the
  user asked for a specific backend by name is exactly the silent substitution ADR-0012
  Decision 7 rejected for `bind` — it would hide the mismatch from the one party who stated a
  preference, for the same reason `bind` never re-routes on its own `BackendCapabilityError`.
- **No detour through `bind`.** Nothing is gained by constructing the frame and calling `bind`
  only so it can raise the identical error a step earlier check already knows about; that's
  ADR-0020 Decision 4's path for the case this filter *can't* pre-empt (`kind="property"`), not
  a reason to route the cases it can through the same detour.

### 4. `backend=` stays absent from `create_chart`/`create_chart_agent` at P1

ADR-0020 Decision 1 is unamended: no `backend=`, and — new here — **no `default_backend=`
either.** A standing-default kwarg would exist only for a caller who wants one, and Decision 1
establishes there isn't one: Studio passes nothing, and no other P1 caller has been named.
Minting a reserved kwarg against a hypothetical future need is the exact trap `quality=`
avoided in ADR-0020 Decision 5 — a parameter that silently does nothing today reads as broken,
not as unfinished. **Excel-never-default (ADR-0019 Decision 3) constrains the ranking only** —
tier 1 can still choose Excel when a request names it and the chart type survives the filter;
it is only ever absent from tier 2's automatic pick.

### 5. `BACKEND_RANKING` — one citable tuple, not ADR prose plus a hand-copied constant

```python
# src/chartagent/frame/input.py, beside Backend
BACKEND_RANKING: tuple[Backend, ...] = ("vegalite", "echarts", "plotly", "chartjs", "excel")
```

Not exported in `chartagent.__all__` (it governs nothing a caller sets — the same treatment
`SourceBucket` already gets in the same module), but importable by path, the way
`tools/score_corpus.py` already imports `InputFrame` from `chartagent.frame.input`.
`tools/score_corpus.py` now imports it instead of hand-declaring its own `BACKENDS` tuple,
which had drifted from the rank order (`chartjs` before `plotly`) since ADR-0019 shipped. #92
imports the same constant rather than re-deriving the order when it builds the real filter+rank
step; this ADR fixes the order and its one home, not where #92's module structure puts the
code that reads it.

### 6. `backend_default_partition` replaces `backend_forced`

`backend_forced`'s `neither_vegalite_nor_plotly` predates any ranking — it checked two
backends that were never the actual top two (rank 2 is `echarts`, not `plotly`), so it stopped
meaning anything the moment ADR-0019 shipped. Replaced with a full partition of the union under
filter+rank alone:

```python
def backend_default_partition(vocab: Mapping[str, Any]) -> dict[str, int]:
    """{vegalite: N, echarts: N, plotly: N, chartjs: N, excel: N, exactly_one_backend: N}."""
```

For each of the 48 union chart types, which `BACKEND_RANKING` entry would be chosen if nothing
overrode it — a pure pin fact, data-free, computed the same way `backend_forced` already was
(off `vocab.json`, never against a request). `exactly_one_backend` is kept unchanged (a
different fact: how many types have no real choice regardless of ranking). Measured against
the shipped pin: `vegalite 36, echarts 8, plotly 1, chartjs 3, excel 0`, `exactly_one_backend
8` — the same `8` `backend_forced` already reported, confirming the replacement preserves the
one number that survives.

Reported in `tools/score_corpus.py`'s markdown alongside the disclosure line (Decision 7),
"beside the share, never inside it" — unchanged framing from `backend_forced`.

### 7. The disclosure line

ADR-0019 Decision 4 fixed the facts (four of cell 3's six stress slots silenced; the two
discrete-channel row-drop slots remain; no boxplot special case). This settles the wording,
now landing in `tools/score_corpus.py`'s report:

> Backend ranking applied: vegalite > echarts > plotly > chartjs > excel, unless the request
> named a backend. Of cell 3's six stress slots, four are silenced by this ranking and never
> fire: Excel's empty-after-filter refusal, the pyramid two-groups rule, candlestick ordering,
> and the non-painting ECharts boxplot (Boxplot routes to Vega-Lite). The two discrete-channel
> row-drop slots remain — the ranking-proof floor.

**"Studio's target wins" is deliberately absent** — there is no such tier (Decision 1). The
non-painting-boxplot clause is unchanged from ADR-0019 and holds in Studio exactly as it holds
anywhere else: Studio applies no override, so `Boxplot` routes to Vega-Lite there too.

## Consequences

- **`requested_backend` widens step 1's `Fragment`, once #92 builds it.** No `__all__` change
  — it never crosses the seam, same treatment as `chart_spec.chartType` before it becomes part
  of the emitted frame.
- **`BackendCapabilityError` now has two raise sites**: `bind` (unchanged, ADR-0012) and the
  planner's filter step (new, `kind` restricted to `chart_type`/`facet` — `property` still only
  from `bind`). Both are the same type, so `except ChartAgentError` at a `create_chart` call
  site (ADR-0020 Decision 4) catches either without change.
- **Five ADRs plus the PRD carried a claim no decision ever made** ("ECharts is the default web
  target" / "Studio's default"), corrected in place as prose errata (ADR-0001, 0002, 0003,
  0005, 0012) — none of their actual decisions changed.
- **`tools/score_corpus.py`'s `BACKENDS` constant is gone**, replaced by an import of
  `BACKEND_RANKING` from the library — the scorer's ranking order and the planner's (once #92
  ships) cannot drift apart silently again.
- **The library's raw ranking is what Studio actually ships**, for any request that doesn't
  name a backend — a real, disclosure-relevant fact this ticket's grilling surfaced: Studio was
  never going to override it, because there was never an override to write.

## Alternatives rejected

- **Three tiers** (`requested_backend` → Studio's standing target → the ranking). Rejected once
  the premise died — Studio has no standing target to be a tier.
- **Studio injects its preference into the instruction text.** Would have conflated a product
  default with a human's stated ask, in the same text field, with no way to tell them apart —
  moot once there's no product default to inject.
- **A `default_backend=` kwarg on `create_chart`.** Considered as the tier-2 channel Studio
  would use; rejected once Studio turned out not to want one — see Decision 4.
- **Falling `requested_backend` through to the ranking on a capability miss**, or retrying step
  1. Both considered for Decision 3; both silently override or waste a call on an answer that
  was already correct — see Decision 3.
- **Routing a `requested_backend` capability miss through `bind`** rather than raising at the
  filter step. No functional difference in what's raised, but it wastes a `bind` call
  constructing a frame no one needed, for no benefit over checking at the filter directly.

## Evidence

- `src/chartagent/bind.py:257-290` — `_check_backend_chart_type` (`kind="chart_type"`) and
  `_check_excel_facet` (`kind="facet"`) both need only `chart_spec.chart_type` and
  `chart_spec.encodings`, not `chart_properties` — confirming both are derivable before step 2
  runs, and `kind="property"` (needs `chart_properties`) is not.
- `src/chartagent/frame/vocab.json` at Flint `0.5.1`, partitioned under `BACKEND_RANKING`:
  `vegalite 36, echarts 8, plotly 1, chartjs 3, excel 0`, `exactly_one_backend 8` (matches
  `backend_forced`'s prior count exactly).
- `tools/score_corpus.py`'s prior `BACKENDS = ("vegalite", "echarts", "chartjs", "plotly",
  "excel")` — out of step with ADR-0019's rank order before this ADR.
- Grep across `docs/adr/` and `chartagent-prd.md`, 2026-09-03: "ECharts is/remains the default
  web target" or "Studio's default" appears unexamined in ADR-0001, ADR-0002, ADR-0003 (twice),
  ADR-0005 (twice), ADR-0012 (twice), and the PRD — none citing an actual decision.

## Related

- [#93](https://github.com/thearcscode/chartagent/issues/93) — the grilling this settles.
- [#79](https://github.com/thearcscode/chartagent/issues/79) / ADR-0019 — the ranking and the
  two-step shape this composes with.
- [#91](https://github.com/thearcscode/chartagent/issues/91) / ADR-0020 — the planner's public
  surface; `backend=`'s absence confirmed here.
- [#92](https://github.com/thearcscode/chartagent/issues/92) — the prompt renderer; builds the
  actual `Fragment` schema and `filter + rank` code against this ADR's shape.
