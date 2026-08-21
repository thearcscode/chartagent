# 1. Embed the pinned Flint compiler in-process

- **Status:** Accepted
- **Date:** 2026-08-21
- **Supersedes:** the backend and integration claims in `docs/research/flint-chart-leverage.md`
  (written 2026-07-22 against flint-chart 0.2.x)

## Context

chartagents needs to turn a stored spec into polished, backend-native chart output.
`microsoft/flint-chart` already does that part well: at 0.5.1 it compiles one input
shape to Vega-Lite, ECharts, Chart.js, Plotly and native Excel, with ten calibrated
theme presets, a semantic-type registry, an auto-layout optimizer and deterministic
chart-type recommendation. Reimplementing that is not a good use of our time; the
planner is our product, the compiler is not.

Three integration routes were on the table.

**A port to Python.** `packages/flint-py` exists and is faithful — its own gallery report
claims 658/658 byte-identical Vega-Lite specs. But it is a *partial* port: Vega-Lite only,
and its `core/` is missing `theme/` (~230 KB of TypeScript), `pivot.ts` (44 KB),
`recommendation.ts` (49 KB) and `chart-type-recommendation.ts` (17 KB). The two most
valuable recent additions — themes and named views — are absent. Porting the ECharts
backend alone is 42 files and 526 KB of TypeScript, roughly 1.2× the size of everything
already ported, and there is no oracle for it: all 705 fixtures in `shared/test-data/`
record **Vega-Lite** output only.

**A Node sidecar.** `flint-chart-mcp` (new since the July research) is a ready-made one:
six tools over stdio, in-process rendering, no remote upload. But it adds a second runtime
to every deployment, plus process supervision, IPC framing and failure modes we would own.

**Embedding the JavaScript.** `flint-chart` declares **zero runtime dependencies** — only
optional `peerDependencies` (vega, vega-lite, echarts, chart.js, plotly.js), and those are
needed to *render*, never to *compile*. The published bundle contains no `process.`,
`Buffer.`, `__dirname` or `require(`. The compiler is pure, platform-neutral JavaScript,
so it can run in a JavaScript engine embedded inside CPython.

We verified the third route works. See **Evidence**.

## Decision

**Embed the Flint compiler in-process, at a pinned version, as a vendored single-file
bundle executed by an embedded JavaScript engine. Do not port it. Do not run it as a
sidecar. Do not modify it.**

Concretely:

1. **Pin and vendor.** Build one bundle per Flint release we adopt:

   ```
   npm pack flint-chart@<pinned>
   esbuild package/dist/index.js --bundle --format=iife --global-name=Flint \
           --platform=neutral --target=es2020 --outfile=flint.iife.js
   ```

   The bundle ships inside our Python package. No npm at runtime, no network, no
   subprocess. Upgrades are a deliberate version bump with a fixture re-run, never
   an implicit resolution.

2. **One JavaScript context per thread. Never shared.** Sharing a QuickJS context across
   threads **segfaults the process** — a hard crash with no catchable exception. The
   context pool must make this structurally impossible, not merely discouraged
   (thread-local storage, or a pool that hands out a context and refuses re-entrant
   checkout). This is the single most dangerous constraint in this ADR.

3. **Normalise dates to ISO-8601 in our transform layer, before Flint sees the data.**
   Parsing of non-standard date strings is implementation-defined in ECMAScript, and the
   engines genuinely disagree: `"Jan 2020"` yields a **temporal** axis under V8 and an
   **ordinal** one under SpiderMonkey — a different chart, not a rounding difference.
   Normalising upstream eliminates the divergence (see Evidence). Where a string is
   irreducibly ambiguous (a bare `"Jan"`), state the meaning with a `semantic_types`
   annotation rather than relying on parsing.

4. **No fork, and no modification, for the product build.** We consume the released
   package as a vendored bundle and add nothing to it. An earlier draft of this decision
   described "our fork" adding a `src/highcharts/` backend, which contradicted the "do not
   modify it" above; that ambiguity is resolved in favour of no fork (amended 2026-08-21).

   This is deferred, not ruled out. If a backend of our own is ever needed, two constraints
   already apply and are recorded here so the option stays open: extension must be
   *additive at declared seams* — new files plus the existing `postProcess(spec, context)`
   hook on `ChartTemplateDef`, never edits to `compute-layout.ts`, `theme/ground.ts` or the
   templates — and it must rebase onto upstream tags. The merge tax is a function of which
   files we touch, not of whether we forked. Taking that step needs its own ADR, and is
   entangled with the unresolved Highcharts licensing question.

5. **Render client-side.** The browser is the renderer; the embedded engine only produces
   the option object, in under a millisecond. Server-side rasterisation (PNG export,
   scheduled digests, thumbnails) is a separate, later, queued service — not a dependency
   of the compile path.

### Engine choice

**PythonMonkey (SpiderMonkey) as the default; QuickJS as the isolation fallback.** Keep
the engine behind one interface so it stays swappable, and treat the fixture suite as the
contract both must satisfy.

|                          | QuickJS          | PythonMonkey     |
| ------------------------ | ---------------- | ---------------- |
| Cold boot                | 64 ms            | 185 ms           |
| Resident memory          | +22 MB           | +58 MB           |
| Vega-Lite compile (p50)  | 0.63 ms          | 0.12 ms          |
| ECharts compile (p50)    | 0.37 ms          | 0.06 ms          |
| Serial throughput        | 2,619/s          | 19,055/s         |
| Thread scaling           | 6,824/s on 4 (2.6×) | single realm  |
| Agreement with Node      | 676/705          | **695/705**      |
| …after ISO date fix      | not measured     | **705/705**      |
| Isolation                | per context, 5.2 MB each | one global realm |

PythonMonkey is ~7× faster per compile and, with the date rule above, **matches Node
exactly on all 705 fixtures**. Its costs are a slower boot, ~2.6× the memory, and a single
global JS realm per process with no context-isolation API — so multi-tenant isolation has
to come from process boundaries rather than contexts.

QuickJS is the fallback where per-tenant isolation inside one process matters more than
throughput: real contexts at 5.2 MB each, and it scales across threads (2,619/s serial →
6,824/s on four, so the binding releases the GIL). It is further from V8 on dates, and it
alone needs the `structuredClone` polyfill.

Note: the two engines segfault if imported into the same interpreter. One engine per
process; never co-load.

## Consequences

**What we gain.** Every backend Flint supports today and every backend, chart type and
theme it adds later, for the cost of a version bump — no porting, no catching up. No Node
in production. No sidecar to supervise. Sub-millisecond compilation. The semantic
resolver, layout optimizer, overflow handling, faceting, themes, named views and
recommenders all come along, and any Stage-3 backend we write ourselves inherits them.

**What we accept.** A JavaScript engine in our Python process, and a small C-extension
dependency. An engine-specific fidelity surface that only the fixture suite can police.
No control over the compiler's internals — when Flint changes how axis titles are placed,
our output changes with it.

**What this obliges us to build.** A context pool that makes cross-thread sharing
impossible. A date-normalisation step in the transform layer. A pinned-fixture CI job that
re-runs all 705 cases on every Flint bump and every engine change, and fails on any
unexplained diff.

**Known hazard, unrelated to embedding.** Flint's optimizer filters data when a discrete
channel exceeds the layout budget, and which rows survive depends on canvas size and row
count. In our run, **59 of 705 cases returned a different number of data rows** than the
recorded fixture. Any "refresh is free and stable" claim requires pinning `baseSize` and
`canvasSize` and reading `_warnings`.

## Evidence

Reproducible via `prototypes/flint-embed/`. Measured 2026-08-21 against `flint-chart`
0.5.1 (npm) and `microsoft/flint-chart` `main` at `34ef451`.

**All five backends compile inside CPython, no Node** (`harness.py smoke`). One shim is
required: QuickJS lacks `structuredClone`, polyfilled with `JSON.parse(JSON.stringify(x))`.
That was the only missing global.

```
engine + bundle loaded in 65 ms (once)
vegalite 0.85 ms | echarts 0.43 ms | chartjs 0.40 ms | plotly 0.59 ms | excel 0.17 ms
10 theme presets and recommendChartTypes() reachable
```

**705/705 of Microsoft's own fixtures execute with zero errors** through both embedded
engines (`harness.py parity`). Agreement with Node/V8, canonicalised in Python on both
sides and ignoring `_`-prefixed keys:

- PythonMonkey: **695/705**. All ten disagreements are in one category, `dates_year_month`.
- QuickJS: 676/705, spread across `dates_date_datetime`, `dates_year`, `dates_year_month`
  and `gallery_kpi_card`.
- After ISO-8601 normalisation of the affected columns (`harness.py dates`):
  **10 of 10 fixed, 0 remaining, 0 unmatched — PythonMonkey reaches 705/705.**

So the embedding approach has exactly one fidelity gap, it is confined to ambiguous date
strings, and it closes completely under a rule we already own because the transform layer
is ours.

**Sharing a QuickJS context across threads dies with SIGSEGV** (`harness.py bench`,
exit −11). Demonstrated deliberately in a subprocess. No exception is raised, so this
cannot be caught — only prevented.

**The compiler churns; the input frame does not.** Comparing npm 0.5.1 against the
fixtures committed at the same commit, only 51.8% match once the `config` block is set
aside. The differences concentrate exactly where the 0.5.1 changelog says work happened:

```
705  config.legend                 163  config.view.continuousHeight
598  config.axisY.labelSeparation  149  config.facet.spacing
591  config.axis{X,Y}.titleFontSize 70  width.step
371  config.axisX.labelSeparation   59  data.values   ← row count differs
```

Meanwhile every breaking change in the changelog since 0.2.1 is a `chartProperties` key
removal (`Sparkline.independentYAxis`, `dodge: none`, `Rose.innerRadius`). The typed frame
has only ever grown. **This is the core argument for pinning and not forking:** the churn
lives entirely in the code we would never intend to change.

**`theme_spec` is silently ignored by the ECharts and Chart.js backends.** Not an error,
not a warning — byte-identical output with and without a theme, verified across three
presets. Themes are realised for Vega-Lite and Plotly only. Recorded here because ECharts
is our default web target.

## Alternatives rejected

**Port to Python.** Rejected: the port is partial and always will be lagging by design
(the TypeScript output is the test oracle), themes and pivot are absent, and an ECharts
port is larger than everything ported so far with no oracle to validate it against.

**Node sidecar (`flint-chart-mcp`).** Rejected as a runtime, though it stays useful as a
local dev tool and as a reference implementation of in-process rendering. It is *not* a
hosted service — `npx flint-chart-mcp` runs locally over stdio, Microsoft operates nothing
in the path, and data never leaves the host. The objection is a second runtime, not
privacy.

**Fork the compiler and maintain it.** Rejected. The evidence above shows the compiler's
output moving continuously; a fork that changes little pays the full merge tax for almost
no benefit. Should extension ever become necessary, the additive-seams route in Decision 4
gets the same result for a fraction of the cost — but nothing in the product build needs
it, so we carry no fork at all.

**Depend on Flint unpinned.** Rejected. Minor releases have removed chart properties, and
compiled output changes between builds at the same version number.

## Related

- `docs/research/flint-chart-leverage.md` — stale on backend count (three, now five) and
  on `flint-py` scope; superseded here.
- Next decision, not yet written: adopting Flint's input frame as our spec with a
  namespaced `x_chartagent` extension block for `transform`, `annotations`, `interactions`
  and `escape`.
- `prototypes/chartspec-v1/` — the grammar this frame decision would replace. Still marked
  `PROTOTYPE — THROWAWAY`.
