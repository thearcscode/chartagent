# Research: Leveraging Microsoft `flint-chart` in chartagent

AFK research. Surfaces what `microsoft/flint-chart` is, where it overlaps with the
chartagent architecture in `chartagent-prd.md`, and gives a recommendation with
tradeoffs. The decision itself graduates from these facts.

- **Date:** 2026-07-22
- **Subject:** [`microsoft/flint-chart`](https://github.com/microsoft/flint-chart) — a
  visualization *intermediate language* + compiler, MIT-licensed, released July 2026 by
  Microsoft Research with Renmin University. ~2k GitHub stars at time of writing; already
  ships inside Microsoft's Data Formulator.
- **Scope:** the deterministic rail (PRD §7.3, pillar 3), the `ChartSpec` grammar
  (prototype `chartspec-v1`, issue #3), the adapter/CapabilityProfile boundary (issue #9),
  output-artifact contract (PRD pillar 1), and competitive positioning (PRD §2).

---

## TL;DR

Flint is **not a competitor** to chartagent — it occupies the exact layer *underneath*
the deterministic rail, the layer chartagent has not yet built: "given a chart spec,
compile it into a polished native chart." It solves that layer well, has a benchmarked
quality edge, and is MIT-licensed. chartagent is the agentic system *around* that layer
(profiling, planning, sandbox, review gate, zero-cost refresh, data-source abstraction) —
none of which Flint has or attempts.

Two concrete pieces of leverage, in priority order:

1. **Adopt Flint's semantic-type ontology into `ChartSpec`** (design leverage, high value,
   low risk). Today `Channel.type` is the blunt 4-way Vega-Lite `DataType`
   (`quantitative/temporal/ordinal/nominal`). Flint's 3-tier / 70+ semantic types, each
   carrying five orthogonal decision dimensions, is precisely the "design knowledge in the
   library, not in the prompt" that pillar 3 wants. This moves format / aggregation /
   zero-baseline / color decisions **off the LLM prompt and into deterministic library
   rules** — directly raising the ~80% deterministic-rail hypothesis's ceiling.
2. **Evaluate Flint's compiler as a deterministic-rail renderer backend** (build leverage,
   medium value, real integration cost). It would give Vega-Lite + ECharts + Chart.js from
   one spec, already benchmarked. Caveat: the full three-backend compiler is JS/TS;
   `flint-py` is Vega-Lite-only and source-only preview. This is a spike, not a commitment.

**Do not** depend on Flint wholesale, and do not treat it as a threat to the USP. The USP
was never the renderer.

---

## 1. What Flint actually is

Flint calls itself "a visualization intermediate language that lets AI agents create
expressive, polished visualizations from simple, human-editable chart specs." The compiler
derives optimized low-level settings (scales, axes, spacing, labels, marks, legends) from
four inputs — **data, semantic types, chart type, encodings** — instead of asking a model
to hand-author them.

### Packages (npm workspace)

| Package | What it is | Backends | Maturity |
| --- | --- | --- | --- |
| `flint-chart` (`packages/flint-js`) | The core TS library + compiler | Vega-Lite, ECharts, Chart.js | Published to npm |
| `flint-chart-mcp` (`packages/flint-mcp`) | MCP server for agent authoring in chat/coding tools | via core | Published (`npx -y flint-chart-mcp`) |
| `flint-py` (`packages/flint-py`) | **Native** Python port (not a JS wrapper) | **Vega-Lite only** | **source-only preview, no PyPI yet** |

Repo is TS-dominant (~85%) with a Python port (~14%). Public API on the JS side:
`assembleVegaLite`, `assembleECharts`, `assembleChartjs`, all taking one
`ChartAssemblyInput`. The Python side exposes `assemble_vegalite()` only.

### The input shape (`ChartAssemblyInput`)

```ts
assembleVegaLite({
  data: { values: myData },                 // or a file URL (JSON/CSV/TSV)
  semantic_types: { weight: 'Quantity', mpg: 'Quantity', origin: 'Country' },
  chart_spec: {
    chartType: 'Scatter Plot',
    encodings: { x:{field:'weight'}, y:{field:'mpg'}, color:{field:'origin'} },
    baseSize: { width: 400, height: 300 },
  },
});
```

Note the split: a **data/semantics layer** (`semantic_types`) and a **chart layer**
(`chart_spec`). This is the same data-vs-chart separation the `ChartSpec` prototype already
has (`DataRef` vs `mark`/`encodings`), which makes the mapping between the two grammars
fairly direct.

### The crown jewel: the semantic-type system

This is the part worth studying closely. Flint captures *what a field means* with 70+
semantic types (`Rank`, `Temperature`, `Price`, `Revenue`, `Country`, `Correlation`, …),
organized as a **three-tier registry**:

- **Tier 0 — Families (6):** `Temporal`, `Measure`, `Categorical`, … Determines the
  fundamental encoding strategy; cheap for an LLM to infer; enables rule-based fallback.
- **Tier 1 — Categories (17):** e.g. `Measure` → `Amount`, `Physical`, `Proportion`,
  `SignedMeasure`. Distinct aggregation / formatting / diverging behavior.
- **Tier 2 — Specific (46):** where compilation behavior actually changes vs the parent.
  `Revenue` ≠ `Price` (additive vs intensive aggregation); `Temperature` ≠ `Quantity`
  (conditional diverging midpoint).

Every type carries **five orthogonal decision dimensions**:

1. **Vis-encoding candidates** — preferred `quantitative/ordinal/nominal/temporal` order.
2. **Aggregation role** — `additive / intensive / signed-additive / dimension / identifier`.
3. **Domain shape** — `open / bounded / fixed / cyclic` (clamping, extrapolation, polar).
4. **Diverging nature** — `none / conditional / inherent` (sequential vs diverging palette).
5. **Format class** — currency / percent / unit-suffix / date … (prefix/suffix + precision).

Resolution walks **T2 → T1 → T0** and **degrades gracefully**: `Revenue` yields currency
format + sum + log-scale hint; if the model only knew `Amount`, it still gets currency +
sum; if only `Measure`, still quantitative + meaningful zero. Unknown types land on a
generic quantitative fallback. So an LLM never has to know all 46 types to get a sensible
result — it can mix tiers per field.

Compilation is **two-stage**, mediated by a flat, target-agnostic IR (`ChannelSemantics`):

- **Stage 1 (field semantics):** field-intrinsic properties — format, aggregation default,
  domain constraint. Never looks at which channel will show the field.
- **Stage 2 (channel semantics):** promotes field props into channel-specific decisions.
  The *same* `Rating [1,5]` field gets integer ticks `[1..5]` on X, but a diverging
  midpoint of 3 on color. "Per-field, then per-channel."

Ambiguity is resolved by an optional `SemanticAnnotation` (`intrinsicDomain:[1,5]`,
`unit:"°C"|"USD"`, `sortOrder:[…]`). When absent, Flint infers from the data distribution
(e.g. if 80% of |values| ≤ 1, treat `Percentage` as fractional).

### Why Microsoft built it, and the evidence they published

MSR's framing: polished charts require "verbose, fragile, and error-prone" low-level specs,
and "LLMs are especially prone to errors when they must manage complex, low-level
specification details." Semantic types are *easier for a model to infer* than the full set
of low-level parameters. Their eval compared Flint against **DirectVL** (direct Vega-Lite
generation) across three models on an LLM-judge score:

| Model | Flint | DirectVL |
| --- | --- | --- |
| GPT-5.1 | 16.27 | 15.91 |
| GPT-5-mini | 16.16 | 15.60 |
| GPT-4.1 | 15.91 | 15.34 |

A consistent, modest edge — and, more importantly, a *smaller/more-inferable* model output.
(Caveat: LLM-judge scores, same self-preference concern the PRD already flags for
chartagent' own benchmark in the v0.3 changelog.)

---

## 2. Where Flint and chartagent overlap — and where they don't

The one-line map: **Flint stops exactly where chartagent' deterministic rail begins
rendering.**

| Capability | Flint | chartagent |
| --- | --- | --- |
| Spec → polished native chart (VL / ECharts / Chart.js) | ✅ core competency | ⛳ planned ("validated spec → hand-written renderer"), not built |
| Semantic-type → layout/format/color decisions | ✅ 70+ types, 5 dimensions | ❌ only 4-way `DataType` |
| Multi-backend from one spec | ✅ (JS: 3 backends) | ⛳ intended (ECharts/Plotly/PNG/SVG/HTML) via adapters |
| Data profiling (DuckDB, data-stays-in-infra) | ❌ | ✅ pillar 2 |
| LLM planning loop / agentic custom-code rail | ❌ | ✅ pillars 1, 3 |
| Review gate (lint + VLM critique + interactivity) | ❌ | ✅ pillar 3 |
| Zero-LLM refresh against fresh data | ❌ | ✅ pillar 6 (the durability guarantee) |
| Self-hostable execution sandbox | ❌ | ✅ pillar 2 |
| Data-source abstraction (files / S3 / warehouse / text-to-SQL) | ❌ (values or a file URL) | ✅ §7.4 three-flavor `DataSource` |
| Python-first embeddable API | ⚠️ preview, VL-only | ✅ the whole product |
| MCP server for chat authoring | ✅ | ❌ **explicit non-goal** (chat analyst is out of scope) |

**Conclusion:** Flint is a *renderer/compiler library*; chartagent is an *end-to-end
agentic system*. They are complements. The right mental model is exactly the PRD's existing
treatment of Snowflake Cortex Analyst (§2): Cortex Analyst answers "*what data*"; Flint
answers "*given a spec, draw it well*"; chartagent answers "*given data + an instruction,
decide the spec, guarantee its quality, and refresh it forever.*"

---

## 3. Leverage option A — adopt the semantic-type ontology into `ChartSpec`

**This is the highest-value, lowest-risk takeaway, and it's independent of whether we ever
run a line of Flint code.**

### The gap it fills

`chartspec-v1`'s `Channel.type` is `DataType ∈ {quantitative, temporal, ordinal, nominal}`.
That is the Vega-Lite typing, and it is exactly the "blunt instrument" MSR built Flint to
replace. With only 4-way typing, every decision that depends on *what the number means* —
currency vs percent formatting, sum vs average aggregation, sequential vs diverging color,
whether zero is meaningful on a bar baseline — has to come from somewhere. Today that
somewhere is the LLM prompt. That is the fragility pillar 3 is trying to engineer away.

The `%chartspec-v1%` prototype already gestures at this design instinct:

- `ScaleSpec.zero` exists and the comment says the bar-baseline lint (§7.3 T1) reads it —
  but *nothing computes it*; the LLM has to set it. Flint's `zeroBaseline` decision is
  derived from semantic type × channel × mark.
- `Channel.sort` accepts a custom order — Flint's `sortOrder` annotation formalizes this.
- `AxisSpec.format` is a free d3-format string the LLM must author — Flint derives it from
  the type's format class + unit.

### The proposal

Add a `semantic` field to `Channel` (a semantic-type name, optionally with a
`SemanticAnnotation` for `intrinsicDomain`/`unit`/`sortOrder`), and introduce a **resolver
layer** between `profile.json` (issue #5) and final render that fills in `scale.zero`,
`axis.format`, aggregation defaults, and palette *from the semantic type* when the spec
leaves them `None`. This slots cleanly into the existing precedence rule:

> `Style` D8: explicit spec value > org skill > theme > adapter default.

The Flint-derived decisions become the **adapter-default layer** — the floor everything
else overrides. A spec that sets nothing inherits good semantic defaults; an org skill or
explicit value still wins. No new precedence concept required.

### Why this fits chartagent' existing decisions rather than fighting them

- **D2 (aggregation lives in the transform, not on the channel).** Flint's aggregation
  *role* (`additive`/`intensive`) is a **default/hint**, not an authority. It doesn't
  violate D2 — it *seeds* the transform planner ("Revenue ⇒ propose SUM; Price ⇒ propose
  AVG"), while `data.transform` (issue #4) stays the single source of truth. Complementary.
- **Zero-cost refresh (pillar 6 / §7.7).** Flint compilation is deterministic (spec →
  native spec, no model call). Semantic types are stored *in the spec*, so re-rendering on
  fresh data replays the same derivations — this *reinforces* the refresh guarantee rather
  than complicating it. And Flint's own data-distribution inference (the "80% ≤ 1 ⇒
  fractional percentage" rule) is exactly the kind of thing that should be pinned at plan
  time and frozen into the spec, so a schema/data drift can't silently flip it.
- **Two-phase validation (prototype phase-1 vs `validate_against_profile`).** Semantic
  resolution is naturally phase-2 (needs `profile.json`), the same phase where cardinality
  caps already live. Clean home.

### The chartagent-does-it-better angle

Flint pushes semantic-type inference onto the LLM (then falls back to data-distribution
guesses). **chartagent already profiles the data with DuckDB before the LLM is called.**
That means many semantic signals Flint infers heuristically — cardinality, min/max,
fractional-vs-whole distribution, monotonic dates, currency-ish ranges — chartagent can
compute *deterministically from the profile* and hand to the resolver, or use to *validate*
the LLM's semantic-type guess. So the chartagent + semantic-types combination can feed the
resolver **better annotations than Flint-in-a-chat ever gets**. This is a genuine edge, not
just parity.

**Action:** this is ADR-worthy. Recommend an ADR ("Semantic-type enrichment layer for
ChartSpec") under `docs/adr/` (the folder doesn't exist yet; per `docs/agents/domain.md`
it's created lazily when a decision is actually resolved — this qualifies). The ontology
and the five-dimension model are MIT-licensed prior art we can adapt directly; we need not
match all 46 types on day one (the tiered fallback means we can ship T0+T1 and grow T2).

---

## 4. Leverage option B — Flint's compiler as a deterministic-rail renderer

The PRD's deterministic rail is "validated spec → hand-written renderer, zero generated
code." Flint's compiler *is* a hand-written, semantics-aware renderer — already built,
already benchmarked, already shipping in Data Formulator. The question is whether
chartagent compiles `ChartSpec → Flint ChartAssemblyInput → native spec` instead of
writing per-mark renderers itself.

### Upside

- **Multi-backend for free.** PRD pillar 1 promises ECharts JSON, Plotly, PNG/SVG/HTML.
  Flint gives ECharts + Vega-Lite + Chart.js from one input — a large chunk of the
  output-artifact contract, without chartagent maintaining three renderers.
- **Layout/format quality that's already tuned** and independently benchmarked to beat
  direct generation.
- **Fits the adapter model (issue #9).** Flint becomes *one adapter* behind the
  CapabilityProfile boundary, declaring a `max_spec_version`, exactly as the D7
  version-compat helper and the rail router already anticipate. It is not "the rail" — it's
  a pluggable backend, which keeps the escape hatch to hand-written or custom-rail renderers
  intact.

### The real costs — flag these loudly

- **Language boundary.** chartagent is Python; ECharts (the PRD's *primary* web output)
  from Flint natively is JS/TS only today. `flint-py` compiles **Vega-Lite only** and is
  **source-only preview (no PyPI)**. So to get ECharts from Flint in a Python process you'd
  have to (a) wait for `flint-py` to grow an ECharts backend, (b) run `flint-js` via a Node
  sidecar/subprocess in the sandbox, or (c) port it. Option (b) adds a Node runtime
  dependency that the self-hostable-sandbox story (pillar 2) would have to absorb — a real
  ops cost. Option (a) is a bet on someone else's roadmap.
- **Research-artifact governance.** "No specific roadmap disclosed." API-stability risk on a
  young project. Mitigated by MIT license — we can vendor/fork the pieces we depend on — but
  that's a maintenance commitment.
- **Grammar impedance.** `ChartSpec` deliberately carries things Flint's input doesn't model
  the same way: overlay `layers` with a combo allowlist (D5), typed `annotations`
  (reference lines/bands, point labels, callouts), `interactions`, the `escape` custom-rail
  marker. A `ChartSpec → ChartAssemblyInput` mapping is lossy in both directions and needs a
  clear "what Flint can/can't express" capability matrix before committing.

**Action:** a time-boxed spike, not a commitment. Map a handful of `ChartSpec` cases
(single-mark bar/line/scatter/heatmap) to `flint-py`'s `assemble_vegalite()` and compare
output quality + fidelity against a naive hand-written Vega-Lite emitter. Keep Flint strictly
behind the adapter boundary so the decision stays reversible. Defer the ECharts question
until the Vega-Lite spike proves the mapping is clean.

---

## 5. Leverage option C — positioning & competitive intelligence

- **Flint validates the thesis and does *not* threaten the USP.** Microsoft independently
  concluded that a semantic intermediate layer beats raw-spec LLM generation — the same bet
  chartagent' deterministic rail makes. But Flint is a *library*, not a *product*: no
  profiling, no review gate, no zero-cost refresh, no data-source abstraction, no
  data-stays-in-infra guarantee. The moat was always the agentic wrapper, and Flint leaves
  it entirely intact.
- **`flint-mcp` targets the niche chartagent explicitly de-scopes.** Flint's MCP server is
  for the individual authoring charts *in a chat/coding tool* — the exact "ad-hoc analyst in
  a chat" the PRD lists as a non-goal. So `flint-mcp` is not competition for the core; it's
  confirmation that the chat niche is being served by others, which *sharpens* chartagent'
  "embeddable, SLA-shaped, data-in-infra" differentiation.
- **Update the PRD §2 adjacent-competitor section.** Add Flint alongside Cortex Analyst as a
  named *complement* chartagent can sit on top of. Suggested framing: *"Flint answers 'draw
  this spec well'; chartagent decides the spec, guarantees its quality across a review gate,
  and refreshes it forever at $0 inference. chartagent can consume Flint as one deterministic
  renderer among several."* This pre-empts the "isn't this just Flint?" objection the same way
  the PRD already pre-empts "but Claude already does this."

---

## 6. Recommendation

| Horizon | Action | Confidence |
| --- | --- | --- |
| **Now (design)** | Write an ADR adopting Flint's **semantic-type ontology + five decision-dimensions** as the enrichment/resolver layer between `profile.json` and `ChartSpec`. Upgrade `Channel` with a `semantic` field; move format/aggregation/zero-baseline/color derivation off the prompt into deterministic rules (adapter-default precedence layer). Use DuckDB profiling to *seed and validate* semantic types — do it better than Flint-in-a-chat. | **High** |
| **Next (build)** | Time-boxed spike: `ChartSpec → flint-py assemble_vegalite()` behind the CapabilityProfile adapter boundary, for single-mark cases. Compare fidelity + quality vs a naive emitter. Produce a Flint capability matrix (layers/annotations/interactions/escape). | **Medium** |
| **Later (build, conditional)** | If the VL spike wins, evaluate ECharts via `flint-js` Node sidecar *or* track `flint-py`'s ECharts backend. Decide only after the sandbox/ops cost is scoped. | **Low — gated on the spike** |
| **Now (positioning)** | Add Flint to PRD §2 as a named complement (Cortex-Analyst treatment). | **High** |

**What not to do:** don't make Flint a hard dependency of the core, don't route the primary
ECharts output through a Node sidecar before the Vega-Lite spike proves the mapping, and
don't frame Flint as a competitor internally or externally — it isn't one.

### Open questions this research surfaces (for tickets)

1. How many of Flint's 46 T2 types can chartagent' DuckDB profile infer *deterministically*,
   vs how many still need an LLM guess? (Bounds how much LLM planning the ontology actually
   removes.)
2. What is the exact lossy boundary of `ChartSpec → ChartAssemblyInput`? (Layers,
   annotations, interactions, escape.) Needs a capability matrix.
3. `flint-py` ECharts backend: is it on their roadmap, or do we own that bridge? (Determines
   whether option B reaches the primary output format in-process.)
4. License/vendoring posture: pin-and-vendor the ontology tables vs depend on the package
   as it stabilizes.

---

## Sources

- [`microsoft/flint-chart` (GitHub)](https://github.com/microsoft/flint-chart) — README,
  `packages/flint-py`, `docs/design-semantics.md`, `docs/` index.
- [Flint: A visualization language for the AI era — Microsoft Research blog](https://www.microsoft.com/en-us/research/blog/flint-a-visualization-language-for-the-ai-era/)
  — motivation, DirectVL benchmark, Data Formulator adoption.
- [Show HN: Microsoft releases Flint, a visualization language for AI agents](https://news.ycombinator.com/item?id=48834924)
- [Microsoft and Renmin University Open-Source 'Flint'](https://www.chinatechnews.com/2026/07/16/125428-microsoft-and-renmin-university-open-source-flint-to-solve-ai-chart-generation-clashes)
- Internal: `chartagent-prd.md` (§2, §7.3, §7.4, §7.7, pillars 1–6);
  `prototypes/chartspec-v1/chartspec_draft.py` (issue #3);
  `docs/agents/domain.md` (ADR conventions).
