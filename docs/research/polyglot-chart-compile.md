# How others run a JS chart compiler from Python — without “forcing JS into CPython”

- **Status:** Research notes. Decision landed in ADR-0001 (amended 2026-08-22): compile in the client, emit the envelope, do not embed. See [issue #34](https://github.com/thearcscode/chartagent/issues/34).
- **Date:** 2026-08-21
- **Question:** Are we the first to need a JavaScript visualization compiler from a Python product, and what do the systems that already operate at scale actually do?
- **Not re-opened:** porting Flint to Python as a product plan, and Node-as-a-required-runtime-for-every-library-install. Those remain rejected in ADR-0001 on their own evidence. This note asks a different question: *must compile happen inside CPython at all?*

Measured / cited 2026-08-21.

## Summary

Nobody who ships Python charting at scale embeds a general-purpose JS engine to *author* the chart spec. They do one of three things:

1. **Python (or the server) emits JSON; JavaScript runs in the user's browser.** Bokeh, Altair display, Plotly figures, and Microsoft's own Flint consumer (Data Formulator) all work this way. The Python process never evaluates the compiler.
2. **Python *is* the compiler**, for a grammar they own. Altair builds Vega-Lite JSON in pure Python. Matplotlib/Seaborn never touch JS. Microsoft's `flint-py` is this route for Flint — Vega-Lite only, still source-only, still “PyPI planned.”
3. **When they truly must run JS on the server** (Vega-Lite → Vega, PNG without a browser), they **embed V8 inside a purpose-built native module**, not MiniRacer-vs-PythonMonkey. That is `vl-convert`: Deno's V8, inlined JS, PyO3. Altair, VegaFusion, and Hex adopted it because Node and Chrome were worse operationally.

The “creative way out” that already exists in production is **(1)**: store the compact spec, compile in the client. Data Formulator is the existence proof for Flint itself. The place (1) fails is headless refresh / VLM critique / CLI — the same place Altair reaches for `vl-convert` and Plotly reaches for Chrome.

---

## 1. The actual industry split: spec vs compile vs rasterise

Three jobs get conflated in ADR-0001:

| Job | What it produces | Who usually runs it |
| --- | --- | --- |
| **Author the chart** | A compact, stored spec | Python (Altair, Bokeh, Plotly.py) |
| **Compile** | Backend-native option JSON (Vega-Lite, ECharts, …) | Browser JS, *or* a Python port of the compiler |
| **Rasterise** | PNG/SVG bytes | Browser, or an embedded JS runtime, or Chrome |

Flint is unusual because **compile is a substantial JS program** (layout optimiser, 33 types, five backends). Altair moved compile into Python by *being* a Vega-Lite authoring library. Bokeh moved compile into Python by *owning* a parallel TypeScript runtime (BokehJS) whose models match the Python models, then serialising JSON. Flint did not ship that Python compiler; Microsoft shipped JS + MCP + a VL-only preview port.

So “JS with Python” is not one problem. It is “who owns compile.”

---

## 2. Pattern A — JSON from Python, JS only in the browser

This is the dominant production architecture for interactive Python charting.

### Bokeh

Bokeh's own docs: Python serialises plot models to JSON; **BokehJS in the browser** deserialises and renders
([Contributing to BokehJS](https://docs.bokeh.org/en/latest/docs/dev_guide/bokehjs.html)).
The Python process does not execute BokehJS. Scale (large/streaming data) is handled by keeping data on the server and sending JSON, not by embedding V8 in CPython.

### Altair (display path)

Altair's fundamental output is a Vega-Lite **JSON string** (`Chart.to_json()`, `Chart.save('chart.json')`). HTML export is a page that loads Vega/Vega-Lite/vegaEmbed from a CDN and calls `vegaEmbed` in the browser
([Saving Altair Charts](https://altair-viz.github.io/user_guide/saving_charts.html)).
No JS engine in the Python interpreter is required to *show* a chart in Jupyter or a web app. The notebook *is* the browser.

### Plotly.py (figure path)

A Plotly figure is a Python dict that serialises to the Plotly.js schema. Rendering interactive charts is Plotly.js in the browser. Server-side PNG is a *separate* product (Kaleido), and they moved **away** from bundling a runtime: Kaleido v1 requires system Chrome because bundling Chromium “is huge now and that doesn't work”
([plotly/Kaleido](https://github.com/plotly/kaleido), [v1.0.0 notes](https://github.com/plotly/Kaleido/releases/tag/v1.0.0),
[Plotly.py 6.1 migration](https://plotly.com/python/static-image-generation-changes/)).
For throughput they tell you to **reuse one long-lived Chrome** (`start_sync_server()`), i.e. a worker, not an in-process engine.

### Data Formulator — Flint's own host

Microsoft's Data Formulator is a **Python package** (`pip install data_formulator` / `uvx data_formulator`) that opens a browser at localhost:5567
([README](https://github.com/microsoft/data-formulator/blob/main/README.md)).
Charts are “built on Flint.” The Flint compiler lives in the **TypeScript frontend** (`src/lib/agents-chart/…/assemble.ts` in the history that led to 0.7/0.8), not as a CPython extension. The Python side is agents, DuckDB, data loaders. They solved “Python product + Flint” by **not compiling Flint in Python**.

That is the closest analogue to chartagent's hosted app, and it is the opposite of ADR-0001's in-process embed.

---

## 3. Pattern B — Python *is* the compiler (no JS at compile time)

### Altair (authoring)

Altair is a Python API that *constructs* Vega-Lite JSON. The grammar lives in Python. They never run the Vega-Lite *compiler* until you need Vega (not Vega-Lite) or a PNG.

### Matplotlib / Seaborn

Scene graph in Python, draw via C++ AGG (or a GUI toolkit). No JavaScript anywhere
([Matplotlib backends](https://matplotlib.org/stable/users/explain/figure/backends.html)).
This is the scientific-Python default at national-lab scale. It is also what the map already ruled out as a Flint backend: different capability surface, different fidelity suite (map **Out of scope**).

### `flint-py`

Microsoft's stated Python strategy: a **port**, same input shape, TypeScript as ground truth, fixture equality tests
([packages/flint-py/README.md](https://github.com/microsoft/flint-chart/blob/main/packages/flint-py/README.md)).
Still **Vega-Lite only**, **source-only**, “PyPI publishing is planned for a later release.”
That is Pattern B for Flint, unfinished. Waiting on it is a product bet on another team's roadmap, which ADR-0001 already rejected as a *blocking* dependency. It remains a *deferral* option: if `flint-py` grows ECharts, in-process JS becomes optional for that backend.

---

## 4. Pattern C — When server-side JS is unavoidable: embed V8 in a native module

This is the path the Vega ecosystem took when they hit our exact sentence.

Jon Mease, shipping VegaFusion 1.0 (now BSD-3, adopted by **Hex** for their Vega-Lite chart cell):

> Both the new mime renderer and the `transformed_data()` function require the ability to convert Vega-Lite specifications (as produced by Altair) to Vega specifications (as consumed by VegaFusion). This functionality is provided by the Vega-Lite JavaScript library, which presents a challenge: **How can we perform this conversion in Python without a web browser?**
>
> To meet this challenge, we developed … **VlConvert**. … it embeds the Deno JavaScript runtime in a Python library for the purpose of running the Vega-Lite JavaScript library.
>
> ([VegaFusion 1.0 announcement](https://vegafusion.io/posts/2023/2023-01-21_Release_1.0.0.html))

Altair then made `vl-convert` the default for PNG/SVG/PDF and offline HTML
([Saving Altair Charts — Additional Dependencies](https://altair-viz.github.io/user_guide/saving_charts.html)).
The library inlines minified Vega-Lite JS and uses `deno_runtime` / V8; “no dependency on an external web browser or Node.js”
([vl-convert README](https://github.com/vega/vl-convert)).

So at Altair/Hex scale, “don't use Node, don't use Chrome, do run this JS” **is** embedding V8 — but as a **single-purpose PyO3 crate**, not as a swappable MiniRacer/QuickJS/PythonMonkey stack. The JS is an implementation detail of one native wheel.

VegaFusion's other half is the *creative* part: they **reimplemented Vega transforms in Rust** so the heavy data work is not JS at all. JS remains only for the leftover encode/compile. That is “move work off JS,” not “avoid JS for the compiler you don't own.”

---

## 5. Pattern D — Build-time JS, none in production (Rails)

Ruby historically embedded V8 (`mini_racer`, which PyMiniRacer copies) via ExecJS for the asset pipeline. Production Rails often **precompiles assets in CI** and deploys **without a JS runtime**
([rubyonrails-talk: production without Javascript runtime](https://discuss.rubyonrails.org/t/production-deployment-without-javascript-runtime/80465)).
`react_on_rails` moved **off** `mini_racer` as default toward Node because Node was faster and easier to install
([shakacode/react_on_rails#1438](https://github.com/shakacode/react_on_rails/issues/1438)).

This pattern only works if compile is **not a function of live data**. Flint's layout optimiser *is* a function of live data (ADR-0001: 59/705 fixtures change row count with canvas size). Zero-LLM refresh cannot be a precompiled asset. Rails does not save us.

PyMiniRacer's original job at Sqreen/Datadog was evaluating **user JS rules** in-process, not compiling a visualization language
([Reviving PyMiniRacer](https://bpcreech.com/post/mini-racer/)). Different problem.

---

## 6. What this means for chartagent (mapping, not deciding)

ADR-0002 already stores Flint's **input frame**, not compiled output. That is exactly the Bokeh/Altair/Formulator stored artifact. Compile-in-CPython is therefore a *choice about where refresh and review run*, not a requirement of the spec.

| Need | Pattern that already scales | JS in CPython? |
| --- | --- | --- |
| Interactive hosted app | Data Formulator, Bokeh, Altair in Jupyter | **No** — compile in the client |
| Notebook `chart.show()` | Altair HTML / Jupyter renderer | **No** — the notebook is a browser |
| Library returns a spec another system renders | Altair `.to_json()`, Plotly figure | **No** |
| Headless PNG / VLM critique | Altair → vl-convert; Plotly → Chrome | **Yes, or a browser** |
| Zero-LLM refresh *without* a client | Nobody in this survey does Flint-class compile in pure Python except the unfinished `flint-py` | **Yes, unless refresh is “push new data to a client that already has Flint”** |

The gap ADR-0001 filled — “Python library, no Node, compile here” — is real for **embedders who are not a web app** (Airflow job, FastAPI that returns ECharts JSON to a mobile client that is not a browser, etc.). It is **not** how Microsoft runs Flint in Data Formulator, and not how Bokeh/Altair show charts.

Two designs that are “creative” relative to MiniRacer vs PythonMonkey, and that are already in production elsewhere:

1. **Client compile (Formulator/Bokeh).** `chartagent` Python owns profile, plan, validate, store. The hosted UI (and notebook HTML helper) loads the pinned Flint IIFE and calls `assemble*`. Refresh is new data + same spec, no model, no CPython JS. Rasterisation stays the #23 question (vl-convert / ECharts SSR / Playwright).
2. **vl-convert-shaped native module.** If compile-in-process stays a library promise, copy Altair/Hex: one PyO3+`deno_core` crate that inlines `flint.iife.js`, not a general JS embedding with two fallback engines. Same JS, one V8, one wheel story. That is still JS-in-process, but it is the *standard* way the Vega world ships it.

Keeping PythonMonkey+QuickJS *and* calling it “how people do this at scale” is the part the survey does not support. Nobody in this set runs that architecture for a chart compiler.

---

## Sources (primary)

- [BokehJS contribution guide](https://docs.bokeh.org/en/latest/docs/dev_guide/bokehjs.html) — Python JSON ↔ browser BokehJS
- [Altair: Saving Charts](https://altair-viz.github.io/user_guide/saving_charts.html) — JSON/HTML in Python; PNG via vl-convert
- [vl-convert README](https://github.com/vega/vl-convert) — Deno/V8 embedded in Rust/PyO3, no Node
- [VegaFusion 1.0](https://vegafusion.io/posts/2023/2023-01-21_Release_1.0.0.html) — why vl-convert exists; Hex adoption
- [Plotly Kaleido](https://github.com/plotly/kaleido) / [v1.0.0](https://github.com/plotly/Kaleido/releases/tag/v1.0.0) — Chrome worker, not in-process V8
- [Data Formulator README](https://github.com/microsoft/data-formulator/blob/main/README.md) — Python package, browser UI, Flint-powered charts
- [flint-py README](https://github.com/microsoft/flint-chart/blob/main/packages/flint-py/README.md) — VL-only port, TS is oracle
- [flint-chart README](https://github.com/microsoft/flint-chart/blob/main/README.md) — JS library + MCP; Python “to be released”
- [Matplotlib backends](https://matplotlib.org/stable/users/explain/figure/backends.html) — AGG, no JS
- [react_on_rails#1438](https://github.com/shakacode/react_on_rails/issues/1438) — embed V8 vs Node in Ruby
- [PyMiniRacer revival](https://bpcreech.com/post/mini-racer/) — ctypes V8; Node sidecar mentioned as the alternative if you want Node's stdlib
