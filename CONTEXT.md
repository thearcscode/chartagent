# chartagent

An embeddable agentic chart-creation library for Python, plus Chartagent Studio, the hosted application that consumes its public API.

## Language

**chartagent**:
The Python library (singular). Also the product name and the `x_chartagent` namespace.
_Avoid_: chartagents (abandoned plural), ChartSpec-as-the-stored-document

**Chartagent Studio**:
The hosted application, and its name. A separate product in a separate repo
(`thearcscode/chartagent-studio`) that consumes chartagent's public API only. In speech it
is **Studio** against **the library**. Its server binds; its browser compiles (ADR-0006).
_Avoid_: the app as a second compiler, sidecar, "the hosted product" as a name

**Input frame**:
Flint's assembler argument — the document we store and return. It is `data` (at render time), `semantic_types`, `chart_spec`, `options`, `theme_spec`, plus `x_chartagent`.
_Avoid_: ChartSpec (retired grammar), compiled spec, option object

**Envelope**:
The library's last object. Its wire format is exactly three keys: `{ flint_version, backend, input }`. `input` is the input frame. `backend` is `bind`'s required argument — the planner fills it from P1 on — and the caller may ignore it and pass the same `input` to a different assembler. Diagnostics (`row_count`, `elapsed`, `warnings`) ride on the object and never serialise into `input`.
_Avoid_: compiled ECharts option, Vega-Lite spec, PNG as the library return; widening the wire format

**x_chartagent**:
The one top-level sibling on the input frame that holds our grammar (`spec_version`, `transform`, `annotations`, `interactions`, `escape`). Flint ignores it.
_Avoid_: putting our grammar in `chartProperties`

**Bind**:
What the library does: take a stored input frame plus a data source, run `x_chartagent.transform`, attach the rows as `input.data`, and return the envelope. `chartagent.bind(spec, data, *, backend)`. It neither compiles nor rasterises.
_Avoid_: render (retired — the library does not render), `chartagent.render`, calling bind a compile step

**Bind cache**:
Studio's, not the library's. The last *successful* transform output for a saved chart, written to object storage as `{ revision_id, rows }` JSON by a user-initiated bind, and pointed at by one `bind_caches` row. A Library load fetches it and compiles in the client instead of binding; a stale or missing pointer shows *Refresh to bind*. Rows only — never the envelope, the backend, or an advisory, because `theme_spec_ignored` is backend-dependent (ADR-0007).
_Avoid_: thumbnail, stored render, caching the envelope; treating a cache read as a refresh, or a Library load as a reason to re-read the source

**Advisory**:
A frozen `{ code, message }` object on `Envelope.warnings`, describing something the library did or ignored — not a Python warning, because the caller has to render it. Distinct from Flint's `_warnings`, which are produced at compile time in the client and never reach CPython.
_Avoid_: `warnings.warn`, conflating these with Flint `_warnings`

**Compile**:
Flint turning an input frame plus rows into a backend-native document (`assembleECharts`, `assembleVegaLite`, …). Happens in the client, not in CPython.
_Avoid_: embed, in-process engine, sidecar as the compile path

**Rasterise**:
Turning a compiled backend document into PNG or SVG bytes. A separate job from compile.
_Avoid_: treating rasterise as what the library returns

**Zero-LLM refresh**:
Re-running `x_chartagent.transform` for new rows and compiling the same stored input frame, with no model call.
_Avoid_: storing compiled output, storing rows in the spec

**Flint pin**:
The exact `flint-chart` version the façade, the fixture jobs, and client `assemble*` must share. Paired with a fixture commit: `FIXTURE_COMMIT` must resolve to the git tag named by `FLINT_VERSION`.
_Avoid_: unpinned npm resolve, a Python port as the compiler, "CI oracle" (there is none — see **Bump gate**)

**Fixture invariant**:
The per-commit assertion that adding and then deleting `x_chartagent` leaves compiled output and `_`-prefixed metadata unchanged across the fixture corpus. Self-relative, so it needs no reference output. Its failure means our architecture broke.
_Avoid_: calling it a parity or regression test

**Bump gate**:
The differential job that runs when the Flint pin moves: the same fixture inputs compiled by the IIFE we shipped and the IIFE we are about to ship. It asks what changed between two pins, never whether output is correct.
_Avoid_: an oracle, upstream `expected.json` as a reference, an allowlist of forgiven diffs, re-fetching the old pin from npm

**Dirty input**:
A fixture `input.json` that names a property the pin's vocabulary does not declare. Tracked as a count: existence is upstream dirt, a rising count on a bump is a failure.
_Avoid_: an exceptions file, treating any dirty input as a failure by itself
