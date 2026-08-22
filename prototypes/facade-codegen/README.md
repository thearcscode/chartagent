# facade-codegen — risk probe for [#17](https://github.com/thearcscode/chartagent/issues/17)

**Question.** Can the typed Python façade over Flint's frame be *generated from the
pinned bundle*, or can it only be hand-written?

**Answer: generated — yes, from the IIFE, no TypeScript source needed.** But the
metadata it generates from is a **UI-affordance registry, not an input schema**, so
ADR-0002 Decision 7 stands on *what* is generated and needs amending on *how strictly
the result may validate*.

This is a throwaway probe. It reuses `../flint-embed/build/flint.iife.js` and its
fixture corpus; it does not rewrite the loading logic.

```bash
./run.sh          # extract -> generate -> assert -> version-bump gate
```

## What is reachable from the bundle

All of it, at runtime, from the IIFE — nothing needed from `src/` or the `.d.ts`:

| Export | Gives |
| --- | --- |
| `vlAllTemplateDefs` and its `ec` / `cjs` / `pl` / `excel` siblings | per-backend chart types, each with `channels`, `markCognitiveChannel`, `properties` |
| `def.properties[]` | `ChartPropertyDef`: `key`, `type`, `label`, `defaultValue`, `min`/`max`/`step`, `options`, `check` |
| `channels`, `channelGroups` | the 26 channels and their 5 groups |
| `SemanticTypes` | 44 semantic type names |
| `THEME_PRESETS` | 10 preset names |

At flint-chart@0.5.1 that is **48 distinct chart types across 5 backends** (36 vl,
37 ec, 22 cjs, 38 pl, 18 excel; union 48, intersection 11) and **296 properties**,
generating **151 Pydantic models**.

> ⚠️ **ADR-0002 Decision 7 says "33 strings".** The pinned bundle ships 48, and there
> is no single flat list — the vocabulary is per backend. A `Literal` of 33 cannot be
> right for any backend. Decision 7 needs the number and the shape corrected.

## What `properties[]` actually is

The probe's real finding. `properties[]` describes **a control panel**, not an accepted
input. Four pieces of evidence, all from the corpus and the pinned bundle:

1. **It under-declares.** `Heatmap.colorScheme` appears in **no** version's
   `properties[]`, yet a fixture sets it and the compiled Vega-Lite spec *changes*.
   Flint honours properties it does not advertise.
2. **`min`/`max` are slider bounds, not validation bounds.** `Bar Table.maxRows`
   declares `min: 5`, but the corpus uses `maxRows: 0` as a live "no limit" sentinel
   and Flint honours it — the compiled spec differs from both `5` and `20`.
3. **Removed keys are silently ignored, never rejected.** `Rose Chart.innerRadius`
   (dropped after 0.2.1) and `Strip Plot.jitterWidth` still sit in the corpus; Flint
   accepts both and does nothing with them.
4. **Flint never rejects an unknown key at all.** So "the façade admits exactly what
   the bundle admits" is unachievable as literally stated: Flint's admit-set is
   *everything*. The useful target is narrower — admit everything Flint honours, and
   still catch what Flint would silently swallow.

### The two modes, so the trade-off is priced

`generate.py` emits both. The tests run both.

| | `strict` (what Decision 7 assumed) | `advisory` (what the evidence supports) |
| --- | --- | --- |
| unknown keys | `extra='forbid'` | `extra='allow'` |
| `min`/`max` | `ge=` / `le=` | `json_schema_extra` |
| real fixtures admitted | **26 / 30** | **30 / 30** |
| invented enum value | rejected | rejected |
| wrong type | rejected | rejected |

Strict rejects four fixtures Flint compiles happily. Advisory keeps the two checks
Flint itself lacks — enum membership and type — which is the whole value the façade
adds over a bare `dict`.

## The residue that cannot be generated

- **`check(ctx)` — 140 of 296 properties (47%).** A JS closure over `ctx.encodings`,
  `ctx.channelSemantics` **and the data rows** (the `logScale` checks iterate rows
  looking for non-positives). It cannot cross into Python, and it should not try:
  applicability is a *client* concern, and since ADR-0001's amendment the client is
  where Flint already runs. The façade must admit what it cannot judge.
- **Required-ness.** There is no `required` flag anywhere in the metadata — the field
  set is `check, defaultValue, key, label, max, min, options, step, type`. Every
  property is optional. Nothing to derive, nothing to hand-write.
- **The frame envelope** (`data`, `semantic_types`, `chart_spec`, `options`,
  `theme_spec`) is not in the runtime metadata. It is 5 keys, stable across 0.2.1 to
  0.5.1, and is the one part worth hand-writing.

## Where generation runs

A checked-in build script producing **committed** generated code. `extract.mjs` needs
Node; it runs at build time only, never at install or import — which satisfies the
no-Node-at-install constraint from the toolchain ticket and keeps the wheel pure
Python. `build/vocab-*.json` is the reviewable intermediate: a Flint bump shows up as
a readable JSON diff before any Python changes.

## Failing loudly on a bump

`check_bump.py` diffs two extracted vocabularies and exits non-zero on any
**narrowing** — chart removed, property removed, property retyped, enum option
removed, backend export missing. Additions are reported but pass.

Run against the real 0.2.1 → 0.5.1 bump it catches six breaks:

```
PROPERTY REMOVED    vegalite|Heatmap|showTextLabels
PROPERTY REMOVED    vegalite|Rose Chart|innerRadius
PROPERTY REMOVED    vegalite|Sparkline|independentYAxis
PROPERTY REMOVED    vegalite|Waterfall Chart|showTextLabels
OPTION REMOVED      echarts|Stacked Bar Chart|stackMode: lost "layered"
OPTION REMOVED      vegalite|Stacked Bar Chart|stackMode: lost "layered"
```

Two of those are the removals the ticket already knew about; two are not. The
`stackMode: layered` pair is the enum-option analogue of the ticket's `dodge: none` —
the exact silent-widening case, caught.

## Gotchas found the hard way

- **The fixture corpus and the bundle are pinned independently, and have drifted.**
  `FIXTURE_COMMIT=34ef451` still exercises `Rose Chart.innerRadius`, which
  flint-chart@0.5.1 removed. Any CI job asserting façade-vs-corpus needs the two pins
  moved together, or it will report a break that is really a stale checkout.
- **`defaultValue: undefined` is present-but-unset, and `JSON.stringify` drops
  undefined-valued keys** — so the key vanishes from the extracted JSON entirely.
  `Map.projectionCenter` is the case. Coerce with `?? null` and record presence
  separately.
- **Options are `{value?, label}`, and `value` may be an array** (`[105, 35]` for
  `Map.projectionCenter`). Flattening them with `join()` makes `[0,0]` and `"0,0"`
  collide and reports phantom removals — canonicalise with `JSON.stringify` per
  option. This produced a false positive before it was caught, the same way the
  key-order bug did in `flint-embed`.
- **The def key is `properties`, not `chartProperties`.** `chartProperties` is the
  *input frame* key; `properties` is the metadata describing it.
- **`d.chart` is the chart type string** ("Scatter Plot"), and it matches the
  fixtures' root `chartType` exactly.

## Files

| | |
| --- | --- |
| `extract.mjs` | bundle → `vocab.json`. Node, build time only. |
| `generate.py` | `vocab.json` → Pydantic models, `strict` or `advisory`. |
| `test_facade.py` | the assertion, both modes, against the 30 real fixtures. |
| `check_bump.py` | the fail-loud narrowing gate between two vocabularies. |
