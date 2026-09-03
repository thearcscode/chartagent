# 2. Adopt Flint's input frame as the chart spec

- **Status:** Accepted (amended 2026-08-23, 2026-08-26, 2026-08-27)
- **Date:** 2026-08-21; Decision 2 job-shape amended 2026-08-23 (ADR-0004); Decision 3's transform specified 2026-08-26 (ADR-0008); Decisions 4, 5 and 7 amended 2026-08-26 (ADR-0009); **Decision 1's key list amended 2026-08-27 (ADR-0010) — `x_chartagent` holds six keys, not five**
- **Builds on:** ADR-0001 (pin Flint; compile in the client); ADR-0004 (fixture jobs)
- **Retires:** `prototypes/chartspec-v1/` — the grammar this replaces

## Context

ADR-0001 settled that we pin Flint unmodified and compile in the client. It left the
next question open: what does the planner emit, what do we store, and what does patch mode
diff?

`prototypes/chartspec-v1/` answered that with a grammar of our own — a Pydantic `ChartSpec`
with a discriminated `Mark` union, a per-mark channel contract expressed as data, overlay
layers, annotations and a style-precedence resolver. It is a good design and its README
records nine decisions worth keeping.

But it now sits on the wrong side of a boundary. If our stored spec is not Flint's input,
then a translation layer exists between them permanently, and it is bidirectional: patch
mode diffs a *stored* spec, and drift recovery remaps fields inside one, so both have to
work in our vocabulary and then compile down. Every Flint release that widens the frame is
a translation we have to write before the feature is reachable. Worse, a spec valid in our
types can still be unrenderable by Flint — a whole failure class that exists only because
the two vocabularies differ, and that no upstream fixture can catch.

Adopting Flint's frame deletes the translation layer and the failure class with it. The
cost is that Flint's frame has no concept of four things we need — the transform that
produces the columns, annotations, interactions, and the record of why a request escaped
the deterministic rail — and its chart identity is a bare string where ours was a typed
union.

So the real question is not *whose grammar*, but *whether Flint's document can carry ours
without disturbing what upstream compiles*. That is measurable, and we measured it.

## Decision

**Adopt Flint's assembler argument as the chart spec. Carry our grammar in one namespaced
sibling key, `x_chartagent`. Keep a typed Python façade over it. Do not fork the frame, and
do not put our grammar in `chartProperties`.**

```json
{
  "semantic_types": { "quarter": "Quarter", "revenue_sum": "Revenue" },
  "chart_spec": {
    "chartType": "Bar Chart",
    "encodings": { "x": { "field": "quarter" }, "y": { "field": "revenue_sum" } },
    "baseSize": { "width": 640, "height": 400 }
  },
  "options": { "addTooltips": true },
  "theme_spec": "economist",

  "x_chartagent": {
    "spec_version": "1.0",
    "transform": { "group_by": ["quarter"], "aggregate": [{ "op": "sum", "field": "revenue" }] },
    "annotations": [{ "kind": "rule", "channel": "y", "value": { "stat": "mean" } }],
    "interactions": { "hover": "nearest" },
    "escape": null
  }
}
```

Concretely:

1. **`x_chartagent` is the only place our grammar lives.** One key, at the top level,
   holding `spec_version`, `transform`, `annotations`, `interactions` and `escape`. Not
   `chartProperties` — see *Alternatives rejected*, and note that the evidence does **not**
   show `chartProperties` misbehaving today. This is a bet on where future breakage lands,
   not a measured defect.

   **Erratum — 2026-08-27 ([#42](https://github.com/thearcscode/chartagent/issues/42),
   ADR-0010).** The key list is **six**, not five. `source_schema` joins it: a map of
   referenced source columns to coarse type buckets, recording the types the spec was
   *planned against* so that a retype can be detected. It exists because ADR-0005 Decision 7
   found PRD P0.11's retype clause undeliverable against this frame — `semantic_types` maps
   transform *output* columns to Flint semantic meanings and is a different fact about
   different columns. **ADR-0010 specifies it**: written by the caller's save path from the
   `Envelope.source_schema` diagnostic, never by `bind`; absent on `raw_sql` with `STAR` and
   on frames predating the key, which draw a `retype_unchecked` advisory rather than an
   error. Adding it takes `x_chartagent.spec_version` to **1.1** (ADR-0008 Decision 13's
   MINOR-bump rule), and existing `1.0` frames stay valid unchanged.

   This amends the *grammar*, not stored bytes: no frame is rewritten, and opening an old
   chart does not bump its `spec_version` — only a save does. Whether the key set is
   *closed* — what the façade does with an unknown key here — is deliberately still open;
   ADR-0010 Decision 6 closes `source_schema`'s **values** only.

   **Erratum — 2026-08-28 ([#60](https://github.com/thearcscode/chartagent/issues/60),
   ADR-0018).** The key list is **five**, not six: **`escape` leaves the set.** ADR-0018 closes
   the open question in *Related* below — a custom-rail result is a **`ChartRecipe`**, a sibling
   result type, not a frame carrying a flag — because a frame for a chart Flint never draws must
   still name a `chartType` from ADR-0009 Decision 1's closed generated `Literal`. A key that
   would be `null` on every frame forever is a grammar promise maintained for nothing.

   Same rule as `source_schema`'s arrival, in the opposite direction: **this amends the grammar,
   not stored bytes.** Decision 9's canonical JSON omits nulls, so `escape: null` was never in a
   stored frame and there is nothing to migrate. The removal is a MINOR bump under ADR-0008
   Decision 13, taking `spec_version` to **1.2** — one line shared with `ChartRecipe`, whose
   `transform` and `source_schema` are the same grammar objects, so recipes are **born at 1.2**
   and 1.0/1.1 are frame-only history.

   The *closed key set* question stays open and **gets its first live case here**: a stored 1.0
   or 1.1 frame may legitimately name `escape`, a key the 1.2 grammar no longer declares.
   ADR-0018 points at it and deliberately does not decide it.

2. **CI invariant: deleting `x_chartagent` must leave a document that upstream Flint
   compiles, byte for byte identical to the same document without it.** This is the whole
   decision expressed as a test. The job that asserts it is ADR-0004's
   `fixtures-invariant` — every commit, both add and delete, all 705 × 5, including
   `_`-prefixed metadata — not "on every Flint bump." If a Flint release ever starts
   reading unknown top-level keys, that job fails on the release rather than in
   production.

3. **`data` is a compile-time argument, not part of the stored spec.** Flint's frame takes
   rows inline. We store the frame *without* `data` and supply it per render from
   `x_chartagent.transform`, which is what makes the `$0.00` refresh claim true: the stored
   artifact describes how to get the rows, never the rows themselves.

   **Erratum — 2026-08-26 ([#4](https://github.com/thearcscode/chartagent/issues/4)).**
   This decision asserts the transform's *existence* and leaves its shape unspecified.
   **ADR-0008 specifies it**: eight fixed slots in one canonical order — `filter` →
   `derive` → `bin` → `group_by`/`aggregate` → `having` → `sort` → `limit` — over a closed
   24-node expression AST, compiled to DuckDB's relational API rather than to SQL text, with
   `raw_sql` as an exclusive-or alternative held by three independent locks. Two additions
   to PRD §8's op list are load-bearing *for this decision in particular*: without `derive`
   and `bin`, and given Decision 4 below forbidding derivation at the encoding, a monthly
   time series was inexpressible in the menu — so the escape hatch, not the menu, would have
   been the ordinary path to a refreshable spec.

   The `transform` in the example above is **not valid** under that specification: every
   `aggregate` entry now requires an explicit `name` (`{"name": "revenue_sum", "op": "sum",
   "field": "revenue"}`), because Decision 4 below makes the output column name a contract
   the encodings depend on, and an implicit `{field}_{op}` rule would be a second grammar to
   version. The example is left as written, since it is what the frame looked like when this
   decision was taken; ADR-0008's example is the current one.

4. **Encodings reference transform output columns, never raw columns, and never
   aggregate.** This was decision D2 in `chartspec-v1`, adopted there against Vega-Lite's
   habit; Flint enforces it for us, because a channel carries a field name and nothing else.
   The planner therefore has to name derived columns (`revenue_sum`) explicitly — the same
   cost D2 already accepted.

   **Erratum — 2026-08-26 ([#36](https://github.com/thearcscode/chartagent/issues/36),
   ADR-0009).** *"Flint enforces it for us"* is **false**, and so is the fate-table row
   below that repeats it. An `aggregate` key inside an encoding object compiles and
   **changes the compiled chart** — measured at 0.5.1. Flint ignores unknown encoding keys
   silently but honours this one, so nothing upstream was ever enforcing this rule. The
   decision itself stands and is now enforced *by us*: ADR-0009 Decision 6 types an encoding
   as `str | {field, type?}` with `extra='forbid'`, and records `aggregate` as the single
   deliberate narrowing of the façade against Flint.

   The count is also off. A channel is `{ field }` at **1830 of 1842** upstream channels,
   not 1830 of 1830: 12 channels are **string shorthand** (`"color": "value"`, on
   `Choropleth` and `Map`). The shorthand carries a field name and nothing else, so the
   claim survives; ADR-0009 admits it and normalises it to `{field}` on validation.

5. **Canonical JSON omits nulls, and stays the spec-diff unit for patch mode.** Decision D9,
   unchanged. It is safe against this frame because no fixture upstream uses an explicit
   null, so absent and `null` remain the same statement.

   **Erratum — 2026-08-26 ([#36](https://github.com/thearcscode/chartagent/issues/36),
   ADR-0009).** For one field this rule is **load-bearing, not a diff convention**.
   `theme_spec: null` does not read as "no theme" — it **crashes Flint**
   (`Cannot read properties of null (reading 'extends')`), while an absent `theme_spec`
   compiles. Absent and `null` are therefore *not* the same statement there. ADR-0009
   Decision 7 rejects it as `SpecShapeError` rather than coercing it to absent, because a
   caller who wrote `null` meant something and should be told which.

6. **`baseSize` is part of the spec and is pinned.** ADR-0001 recorded that Flint's layout
   optimizer filters data rows when a discrete channel overflows the layout budget, and that
   which rows survive depends on canvas size. A spec that does not pin its size is not a
   spec that refreshes reproducibly.

7. **A typed Pydantic façade, serialising down to this frame — a view, not a second
   grammar.** It gets `chartType` from a generated `Literal` of the strings the pinned Flint
   actually ships, and `chartProperties` from Flint's own `ChartPropertyDef` metadata, so the
   planner keeps completion and validation without us maintaining a parallel vocabulary. The
   façade must be *generated from the pinned bundle*, never hand-written, or it becomes the
   translation layer this ADR exists to avoid.

   **Erratum — 2026-08-26 ([#36](https://github.com/thearcscode/chartagent/issues/36),
   ADR-0009).** The principle — generated from the pin, never hand-written — is what
   [#17](https://github.com/thearcscode/chartagent/issues/17)'s probe confirmed, and it
   stands. Two specifics inside it were wrong. **`chartType` is not a flat `Literal` of 33
   strings**: the pinned bundle ships 48 chart types in union and 11 in intersection, and
   the vocabulary is **per backend** (36 vegalite / 37 echarts / 22 chartjs / 38 plotly / 18
   excel), so one flat list is wrong for every backend at once. And **`chartProperties` is
   not `ChartPropertyDef` alone** — the vocabulary lives in *two* runtime arrays,
   `properties[]` and `encodingActions[]`, 317 entries together.

   How strictly the generated façade may validate — which this decision left implied — is
   settled by **ADR-0009**, along with the five sites beyond `chartProperties` that carry
   the same silent-ignore failure.

8. **Layers stay out of scope.** Flint's template registry is why its output looks good, and
   a generic overlay engine gives that up. If composition is revisited, the cheap routes come
   first: `x2`/`y2` (already in the frame), then Flint's existing named combo templates, then
   contributing named templates upstream — not a layer primitive of our own.

### Palette precedence

The frame has one place for colour, `theme_spec`, and our design system has two palettes
(`design/README.md`): state hues for chrome, and a separate data palette for series. The
precedence rule, so it is written down once:

**`theme_spec` beats our default data palette; our default data palette beats the
renderer's.** The Tier-1 colourblind-safe lint applies to the unthemed default — choosing a
calibrated house theme is an override, not a lint violation. State hues never enter
`theme_spec`, because they never enter a chart.

Two caveats that belong on the record. `theme_spec` is realised for Vega-Lite and Plotly
only; ECharts and Chart.js ignore it silently (ADR-0001) — so whenever a request binds to
one of those two, the data palette reaches it through our own defaults, not through
`theme_spec`. And `theme_spec` appears in **no** upstream fixture, so nothing in the CI job
covers it.

**Erratum — 2026-09-03 ([#93](https://github.com/thearcscode/chartagent/issues/93),
ADR-0021).** The first caveat originally read *"and ECharts is our default web
target — so today the data palette reaches ECharts..."*, asserting ECharts as the product's
automatic pick. No ADR ever decided that, and ADR-0021 confirms Studio carries no standing
target — the caveat now reads conditionally, on whichever of the two backends a given
request actually binds to.

## Consequences

**What we gain.** No translation layer, in either direction. Patch mode diffs the same
document the compiler eats, so a two-line spec diff is a two-line diff of real input.
Anything Flint adds — a channel, a chart type, a theme, a backend — is reachable the moment
we bump the pin, with no grammar work. Flint's `ChartPropertyDef` and `EncodingActionDef`
give us machine-readable answers to "which knobs apply to *this* chart with *this* data",
which is the customisation panel `design/` currently draws by hand.

**What we accept.** `chartType` is an open vocabulary of strings — 33 in the pinned release
— where `chartspec-v1`'s `Mark` was a discriminated union with per-mark parameters. That is
the one real loss, and the façade narrows it to a generated `Literal` rather than removing
it. We also inherit `chartProperties` as an untyped bag for per-template knobs, which is
precisely the surface where every upstream breaking change has landed.

**What this obliges us to build.** The delete-`x_chartagent` invariant as ADR-0004's
per-commit job. A generator that derives the Pydantic façade from the pinned
bundle. Phase-2 validation — field existence and cardinality caps against a data profile —
which stays ours, because `chartspec-v1`'s finding still holds: a spec can be
grammatically valid and still unrenderable against a given dataset, and the planner needs
those errors as repair feedback rather than hard failures.

**What happens to `chartspec-v1`'s nine decisions.**

| # | Decision | Fate |
| --- | --- | --- |
| D1 | `mark` as a discriminated union of objects | **Lost.** `chartType` is a string; the façade recovers a `Literal`, not the per-mark parameters. |
| D2 | No `aggregate` on the channel; encodings reference transform output | **Kept — but enforced by us, not upstream.** ~~now enforced upstream~~; see the Decision 4 erratum (2026-08-26, ADR-0009): Flint honours `aggregate` on an encoding, and the façade is what forbids it. |
| D3 | `tooltip` as a list of channels | **Superseded.** Flint has no tooltip channel; `options.addTooltips` is a boolean, used by 93% of fixtures. |
| D4 | Per-mark channel contract as data, not branching code | **Superseded, better.** Flint ships `ChartPropertyDef` / `EncodingActionDef`, generated rather than hand-maintained. |
| D5 | Layers as bounded overlays on a base mark | **Deferred** — out of scope by explicit decision, see Decision 8. |
| D6 | A reference line's value may be a named statistic | **Kept**, in `x_chartagent.annotations`. |
| D7 | `spec_version` is MAJOR.MINOR only | **Kept**, in `x_chartagent.spec_version`. |
| D8 | Style precedence: spec > org skill > theme > adapter default | **Partly superseded** by `theme_spec` plus the palette rule above. |
| D9 | Canonical JSON excludes nulls | **Kept** — Decision 5. |

## Evidence

Reproducible via `prototypes/flint-frame/`, which reuses the pinned build from
`prototypes/flint-embed/`. Measured 2026-08-21 against `flint-chart` 0.5.1 (npm) and
`microsoft/flint-chart` `main` at `34ef451`.

**The frame is small, and its typed part is stable** (`probe.mjs survey`, 705 fixtures):

```
top-level     chart_spec 705 · data 705 · semantic_types 705 · options 656 (93%)
chart_spec    baseSize 705 · chartType 705 · encodings 705 · chartProperties 30 (4%)
channel keys  field 1830/1830 (100%) · type 3
options keys  addTooltips 656 · elasticity 13 · maxStretch 13 · facetElasticity 7
```

Four top-level keys, three of them universal. A channel is a field reference and nothing
else — 1830 of 1830 channels carry `field`, and only three carry anything more. This is why
Decision 4 costs nothing: the frame has no way to express an encoding-level aggregate, so
the transform boundary the project depends on cannot be violated through it. Meanwhile
`chartProperties` — the untyped bag — is used by 30 of 705 fixtures, and 23 channel names
appear across the corpus, `x2` and `y2` among them.

**An unknown sibling key is inert, on every backend** (`probe.mjs transparency`). Adding
`x_chartagent` with a realistic payload to all 705 fixtures:

```
vegalite   705 unchanged  byte-identical
echarts    667 unchanged  byte-identical, 38 unsupported by this backend
chartjs    595 unchanged  byte-identical, 110 unsupported by this backend
plotly     705 unchanged  byte-identical
excel      365 unchanged  byte-identical, 340 unsupported by this backend

_warnings: 71/705 fixtures already warn; the sibling key changes that set on 0
delete x_chartagent -> identical to the original document: true
```

Not one compiled spec moved, on any backend, and the compiler does not even complain: 71
fixtures produce warnings on their own, and adding the key changes that set on none of
them. The invariant in Decision 2 therefore holds today across the entire upstream corpus.

**But `chartProperties` is equally inert, so the placement rule is a judgment, not a
measurement.** The same payload nested inside `chart_spec.chartProperties` also leaves all
705 fixtures byte-identical on all five backends, with no warnings. Flint's
`core/normalize-properties.ts` says as much — keys not declared by the template are passed
through unchanged. The reason to prefer the sibling key is the churn record, not present
behaviour: every breaking change from 0.2.1 to 0.5.1 is a `chartProperties` key removal
(`Sparkline.independentYAxis`, `dodge: none`, `Rose.innerRadius`), while the typed frame
around it has only grown. Our grammar should not live in the one room upstream keeps
renovating.

**Nothing upstream depends on explicit nulls** — 0 of 705 fixtures contain one anywhere in
the document — so D9's canonical form is compatible with the frame rather than merely
tolerated by it.

**Unverified, and flagged as such.** No fixture uses an array-valued encoding channel
(0/705), so the `y: ["sales", "profit"]` route to multi-series charts is untested here;
`theme_spec` and `field_display_names` likewise appear in no fixture, so the palette
precedence rule above rests on API surface rather than on the CI corpus. Also worth
carrying forward from the transparency run: 340 of 705 fixtures are unsupported by the
Excel backend, 110 by Chart.js and 38 by ECharts, so any per-backend claim needs its own
baseline — a throw is not a difference.

## Alternatives rejected

**Keep `prototypes/chartspec-v1` and translate.** Rejected. A permanent bidirectional
translation between our grammar and Flint's, plus a failure class — valid-but-unrenderable
— that exists only because the two vocabularies differ. The typed `Mark` union is a real
loss, but it is one property of one field, not worth a layer.

**Put our grammar in `chartProperties`.** Rejected, and not because it fails: it is exactly
as transparent as the sibling key on all five backends. Rejected because `chartProperties`
is where 100% of upstream's breaking changes have happened, and it is normalised per
template, so a future template that declares a key we chose would silently capture our
block. A top-level sibling has no such registry to collide with.

**Fork the frame — adopt Flint's shape but rename keys to our taste.** Rejected. It
reintroduces the translation layer for a cosmetic gain and breaks the delete-key invariant,
which is the only cheap test that keeps us honest.

**Store the compiled output instead of the input.** Rejected. Compiled specs are large,
backend-specific, and ADR-0001 showed they move between Flint builds at the same version
number. Storing input means one artifact renders to five backends and survives upgrades;
storing output means re-planning to change target.

## Related

- ADR-0001 — pin Flint and compile in the client; source of the `baseSize` hazard, the
  `theme_spec` gap on ECharts, and the envelope around this frame.
- ADR-0004 — the 705-fixture jobs this ADR's Decision 2 is asserted by; no upstream
  `expected.json`.
- `prototypes/flint-frame/` — the probe behind every number above.
- `prototypes/chartspec-v1/` — retired by this decision. Keep it: its README is the primary
  source for D1–D9 and for the two-phase validation finding, which survives.
- ADR-0009 — what the façade validates: Decision 7's strictness, the per-backend chart-type
  vocabulary, and the five sites beyond `chartProperties` that carry the same silent-ignore
  failure. Amends Decisions 4, 5 and 7 above.
- `design/README.md` — the state / data palette split the precedence rule above refers to.
- **Settled — 2026-08-28 ([#60](https://github.com/thearcscode/chartagent/issues/60),
  ADR-0018): `escape` is a sibling result type, and the key leaves `x_chartagent`.** Whether it
  belonged inside the frame as a field was raised by `chartspec-v1`'s README and open until now.
  Both payloads land on **`ChartRecipe`** — `escape_reason` and a `ChartDocument`, beside
  `spec_version`, `transform`, `source_schema` and `theme_spec` — bound by a second verb,
  `bind_recipe`, and stored beside frames in `spec_revisions.content` under a `kind`
  discriminator. The original bullet and its 2026-08-28 note are kept below as the record of
  what was open and why it stopped being a tidy-up.

  Not yet decided *(closed by ADR-0018)*: whether `escape` belongs inside `x_chartagent` as a
  field or is a sibling result type. `chartspec-v1`'s README raises this and it is still open.

  **Note — 2026-08-28 ([#55](https://github.com/thearcscode/chartagent/issues/55),
  ADR-0016 Decision 8).** This question carries **two payloads, not one**. Besides the escape
  *reason* (whose vocabulary ADR-0013 Decision 11 fixed, and ADR-0016 Decision 3 widened to
  four buckets), a custom-rail result carries the **generated code**, which needs a runtime and
  a version story the reason does not. Placing one places the other, since both turn on whether
  a custom-rail result has an input frame at all. It is also no longer a tidy-up: **P0.5 cannot
  be met until the code has a home** — *re-invoking with new data requires no LLM call* is
  unsatisfiable if the code was never stored — and ADR-0007's schema has no column for it.
