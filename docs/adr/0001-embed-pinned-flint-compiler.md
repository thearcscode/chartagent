# 1. Pin Flint; compile in the client

- **Status:** Accepted (amended 2026-08-22)
- **Date:** 2026-08-21; amended 2026-08-22
- **Supersedes:** the backend and integration claims in `docs/research/flint-chart-leverage.md`
  (written 2026-07-22 against flint-chart 0.2.x). The 2026-08-21 *in-process embed*
  decision in this same file is withdrawn; pin, no-fork, date normalisation, and
  client-side *render* remain.

Filename kept (`0001-embed-pinned-flint-compiler.md`) so existing links hold.

## Context

chartagent needs to turn a stored spec into polished, backend-native chart output.
`microsoft/flint-chart` already does that part well: at 0.5.1 it compiles one input
shape to Vega-Lite, ECharts, Chart.js, Plotly and native Excel, with ten calibrated
theme presets, a semantic-type registry, an auto-layout optimizer and deterministic
chart-type recommendation. Reimplementing that is not a good use of our time; the
planner is our product, the compiler is not.

Four integration routes were on the table.

**A port to Python.** `packages/flint-py` exists and is faithful — its own gallery report
claims 658/658 byte-identical Vega-Lite specs. But it is a *partial* port: Vega-Lite only,
and its `core/` is missing `theme/` (~230 KB of TypeScript), `pivot.ts` (44 KB),
`recommendation.ts` (49 KB) and `chart-type-recommendation.ts` (17 KB). The two most
valuable recent additions — themes and named views — are absent. Porting the ECharts
backend alone is 42 files and 526 KB of TypeScript, roughly 1.2× the size of everything
already ported, and there is no oracle for it: all 705 fixtures in `shared/test-data/`
record **Vega-Lite** output only.

**A Node sidecar.** `flint-chart-mcp` is a ready-made one: six tools over stdio,
in-process rendering, no remote upload. It adds a second runtime to every *library*
deployment, plus process supervision, IPC framing and failure modes we would own.

**Embedding the JavaScript in CPython.** `flint-chart` declares **zero runtime
dependencies** — only optional `peerDependencies` (vega, vega-lite, echarts, chart.js,
plotly.js), and those are needed to *render*, never to *compile*. The published bundle
contains no `process.`, `Buffer.`, `__dirname` or `require(`. The compiler is pure,
platform-neutral JavaScript, so it *can* run in a JavaScript engine embedded inside
CPython. We verified that route works (see **Evidence**). The 2026-08-21 decision took
it: PythonMonkey default, QuickJS isolation fallback.

**Compile in the client.** ADR-0002 already stores Flint's assembler argument, not
compiled output. Microsoft's own Flint host (Data Formulator) is a Python package that
opens a browser and runs Flint in TypeScript, not in CPython. Bokeh and Altair display
the same way: Python emits JSON; JavaScript in the browser does the rest. Headless PNG
is a separate job (Altair uses `vl-convert`; Plotly uses Chrome). See
`docs/research/polyglot-chart-compile.md`.

The embed decision conflated "the library is Python" with "Python must execute the
compiler." Those are different jobs. The library user who draws a chart already has a
JavaScript runtime: a browser, a notebook renderer, or a bundler. Callers without one
are outside the library's compile promise.

## Decision

**Pin Flint at a version. Emit an envelope whose `input` is Flint's assembler argument.
Compile that input in the client. Do not execute Flint inside CPython. Do not port it.
Do not run it as a Node sidecar for the library runtime. Do not modify it.**

Concretely:

1. **Pin.** One Flint release per library release we ship. Upgrades are a deliberate
   version bump with a fixture re-run, never an implicit resolution. The pin is how the
   generated Pydantic façade, the CI oracle, and the client's `assemble*` stay on the
   same compiler. How the matching JavaScript reaches the browser (vendored IIFE in the
   wheel, npm peer, HTML helper) is a packaging question, not this one.

2. **No JavaScript engine in the Python process.** The 2026-08-21 constraint — one
   context per thread, never shared, because a shared QuickJS context SIGSEGVs — is
   withdrawn. There is no context to pool. Probes that embed QuickJS, PythonMonkey, or
   MiniRacer remain valid measurements of a route we did not take.

3. **Normalise dates to ISO-8601 in our transform layer, before Flint sees the data.**
   Parsing of non-standard date strings is implementation-defined in ECMAScript, and
   engines disagree: `"Jan 2020"` yields a **temporal** axis under V8 and an **ordinal**
   one under SpiderMonkey — a different chart, not a rounding difference. Clients may
   run V8, SpiderMonkey, or JavaScriptCore. Normalising upstream eliminates the
   divergence. Where a string is irreducibly ambiguous (a bare `"Jan"`), state the
   meaning with a `semantic_types` annotation rather than relying on parsing.

4. **No fork, and no modification, for the product build.** We consume the released
   package and add nothing to it. An earlier draft of this decision described "our fork"
   adding a `src/highcharts/` backend, which contradicted the "do not modify it" above;
   that ambiguity is resolved in favour of no fork (amended 2026-08-21).

   This is deferred, not ruled out. If a backend of our own is ever needed, two
   constraints already apply and are recorded here so the option stays open: extension
   must be *additive at declared seams* — new files plus the existing
   `postProcess(spec, context)` hook on `ChartTemplateDef`, never edits to
   `compute-layout.ts`, `theme/ground.ts` or the templates — and it must rebase onto
   upstream tags. Taking that step needs its own ADR, and is entangled with the
   unresolved Highcharts licensing question.

5. **Compile and render in the client.** The library's last object is an **envelope**:

   ```
   { "flint_version": "<pin>", "backend": "<planner pick>", "input": <assembler argument> }
   ```

   `input` is the ADR-0002 frame. For a live render it includes `data` after our
   transform has run. For persistence it omits `data`; rows come back from
   `x_chartagent.transform`. `backend` is the planner's recommendation (ECharts is the
   default web target). The caller may ignore it and pass the same `input` to a
   different assembler. `x_chartagent` rides on `input`; Flint reads named fields only
   and does not throw on an unknown sibling (ADR-0002, 705/705, zero throws). CI keeps
   the delete-`x_chartagent` invariant so a future Flint cannot start rejecting the key
   on a version bump.

   The browser (or notebook, or bundler) loads Flint at `flint_version` and calls
   `assembleECharts` / `assembleVegaLite` / … then hands the result to that backend's
   renderer.

6. **Framework-agnostic.** Flint's assemblers are ordinary JavaScript functions. They
   take a plain object and return a plain option or spec object. They do not import
   React, Angular, Vue, Svelte, or any other UI library. A React app, an Angular app, a
   Vue app, a Svelte app, Lit, vanilla HTML, or a notebook HTML cell all do the same
   three steps: load the pinned Flint JS, call `assemble*`, pass the JSON to the
   backend (ECharts, Vega-Embed, Chart.js, Plotly.js). Excel is the exception: that
   backend needs an Office.js host, not a general web framework.

   Server-side rasterisation (PNG for a review gate, scheduled digests, thumbnails) is
   a separate decision — not a dependency of the compile path.

### Engine choice (withdrawn 2026-08-22)

The 2026-08-21 table (PythonMonkey default, QuickJS fallback) described a CPython
embedding we no longer ship. MiniRacer was later shown to match Node 705/705 with no
date fix (`docs/research/v8-embed.md`). None of that is a product engine. CI and
façade generation may use Node as a *build* tool; that is not a runtime sidecar.

## Consequences

**What we gain.** Every backend Flint supports today and every backend, chart type and
theme it adds later, for the cost of a version bump — no porting, no catching up. No
JavaScript engine, C extension, isolate pool, or co-load hazard in the Python process.
Sub-millisecond compilation still happens; it happens in the client's JS runtime. The
semantic resolver, layout optimizer, overflow handling, faceting, themes, named views
and recommenders all come along.

**What we accept.** A drawn chart requires a JavaScript runtime on the caller. The
library does not return an ECharts option object or a PNG. Headless jobs (Airflow,
email thumbnails, VLM critique) are not a library compile promise; they wait on the
rasterisation decision. We do not control the compiler's internals — when Flint
changes how axis titles are placed, client output changes with it.

**What this obliges us to build.** A pinned-fixture CI job that re-runs all 705 cases
on every Flint bump (Node is the oracle, as it already was). A generator that derives
the Pydantic façade from the pin. The envelope as the public return type. Date
normalisation in the transform layer. The delete-`x_chartagent` invariant.

**Known hazard, unrelated to where compile runs.** Flint's optimizer filters data when
a discrete channel exceeds the layout budget, and which rows survive depends on canvas
size and row count. In our run, **59 of 705 cases returned a different number of data
rows** than the recorded fixture. Any "refresh is free and stable" claim requires
pinning `baseSize` and `canvasSize` and reading `_warnings`.

**What this cancels.** A context pool, a production engine interface, and in-process
tenant isolation for JavaScript. Multi-tenant isolation for the hosted product is an
ordinary host concern (processes, tenants, quotas) — not a JS-realm concern.

## Evidence

Reproducible via `prototypes/flint-embed/` (embed *works*), `prototypes/flint-frame/`
(unknown sibling is inert), and `docs/research/polyglot-chart-compile.md` (client
compile is how Altair, Bokeh, Plotly display, and Data Formulator actually run).
Measured 2026-08-21 against `flint-chart` 0.5.1 (npm) and `microsoft/flint-chart`
`main` at `34ef451`, unless noted.

**Embed inside CPython works, and we still do not take that route.** `harness.py smoke`
and `parity`: all five backends compile in-process; 705/705 fixtures execute; after
ISO-8601 normalisation PythonMonkey matches Node on all 705; MiniRacer matches Node
705/705 with no date fix (`docs/research/v8-embed.md`). Sharing a QuickJS context
across threads SIGSEGVs. That evidence is why embed was the 2026-08-21 pick, and why
dropping it is a real trade-off rather than a discovery that embed is impossible.

**An unknown top-level key does not throw.** ADR-0002 `probe.mjs transparency`: adding
`x_chartagent` to all 705 fixtures leaves every backend byte-identical, with zero
throws and no change to `_warnings`. Flint's assemblers read `input.data`,
`input.semantic_types`, `input.chart_spec`, `input.options`, `input.theme_spec`. They
do not walk `Object.keys(input)`.

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
removal (`Sparkline.independentYAxis`, `dodge: none`, `Rose.innerRadius`). The typed
frame has only ever grown. **This is the core argument for pinning and not forking:**
the churn lives entirely in the code we would never intend to change.

**`theme_spec` is silently ignored by the ECharts and Chart.js backends.** Not an error,
not a warning — byte-identical output with and without a theme, verified across three
presets. Themes are realised for Vega-Lite and Plotly only. Recorded here because
ECharts is our default web target.

## Alternatives rejected

**Port to Python.** Rejected: the port is partial and always will be lagging by design
(the TypeScript output is the test oracle), themes and pivot are absent, and an ECharts
port is larger than everything ported so far with no oracle to validate it against.

**Node sidecar (`flint-chart-mcp`) as the library runtime.** Rejected, though it stays
useful as a local dev tool. It is *not* a hosted service — `npx flint-chart-mcp` runs
locally over stdio, Microsoft operates nothing in the path, and data never leaves the
host. The objection is a second runtime on every library install, not privacy. Node as
a *CI / façade-generation* tool is not this rejection.

**Embed Flint in CPython (the 2026-08-21 decision).** Rejected 2026-08-22. The route is
measured and viable (QuickJS, PythonMonkey, MiniRacer). It is also how nobody who ships
Python charting at scale *authors* a chart: they emit JSON and let the client run JS.
ADR-0002 already stores the input that `assemble*` consumes. Embedding buys a Python
`assemble_echarts()` for callers with no browser, at the cost of a C extension, isolate
lifecycle, and crash surface we would own. That is not the product. MiniRacer-vs-
PythonMonkey is therefore not a product question.

**Fork the compiler and maintain it.** Rejected. The evidence above shows the compiler's
output moving continuously; a fork that changes little pays the full merge tax for
almost no benefit. Should extension ever become necessary, the additive-seams route in
Decision 4 gets the same result for a fraction of the cost — but nothing in the product
build needs it, so we carry no fork at all.

**Depend on Flint unpinned.** Rejected. Minor releases have removed chart properties,
and compiled output changes between builds at the same version number.

**Store compiled output instead of the input frame.** Rejected in ADR-0002; restated
here because client compile makes it load-bearing: the stored artifact *is* what the
next client compiles.

## Related

- `docs/research/flint-chart-leverage.md` — stale on backend count (three, now five) and
  on `flint-py` scope; superseded here.
- `docs/research/polyglot-chart-compile.md` — how Altair, Bokeh, Plotly, Hex, and Data
  Formulator split spec / compile / rasterise; the evidence for the 2026-08-22 amendment.
- `docs/research/v8-embed.md` — in-process V8 still works; not a product engine.
- ADR-0002 — the assembler argument *is* `input`; `x_chartagent` is the sibling Flint
  ignores.
- How the matching Flint JS is distributed — packaging ticket, not this ADR.
- Server-side PNG / VLM — rasterisation ticket; do not assume an engine in CPython.
