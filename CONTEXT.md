# chartagent

An embeddable agentic chart-creation library for Python, plus a hosted product that consumes its public API.

## Language

**chartagent**:
The Python library (singular). Also the product name and the `x_chartagent` namespace.
_Avoid_: chartagents (abandoned plural), ChartSpec-as-the-stored-document

**Hosted product**:
The separate application that consumes chartagent's public API only.
_Avoid_: the app as a second compiler, sidecar

**Input frame**:
Flint's assembler argument — the document we store and return. It is `data` (at render time), `semantic_types`, `chart_spec`, `options`, `theme_spec`, plus `x_chartagent`.
_Avoid_: ChartSpec (retired grammar), compiled spec, option object

**Envelope**:
The library's last object: `{ flint_version, backend, input }`. `input` is the input frame. `backend` is the planner's recommended assembler; the caller may ignore it.
_Avoid_: compiled ECharts option, Vega-Lite spec, PNG as the library return

**x_chartagent**:
The one top-level sibling on the input frame that holds our grammar (`spec_version`, `transform`, `annotations`, `interactions`, `escape`). Flint ignores it.
_Avoid_: putting our grammar in `chartProperties`

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
The exact `flint-chart` version the façade, CI oracle, and client `assemble*` must share.
_Avoid_: unpinned npm resolve, a Python port as the compiler
