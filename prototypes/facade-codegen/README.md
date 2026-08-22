# facade-codegen — risk probe for [#17](https://github.com/thearcscode/chartagent/issues/17)

**Question.** Can the typed Python façade over Flint's frame be *generated from the
pinned bundle*, or can it only be hand-written?

**Answer: generated — yes, from the IIFE, no TypeScript source needed.** ADR-0002
Decision 7 stands. Two specifics in it need correcting: the chart-type vocabulary is
**per backend and 48 wide, not a flat 33**, and Flint's declared `min`/`max` are
**slider bounds, not validation bounds**.

This is a throwaway probe. It reuses `../flint-embed/build/flint.iife.js` and its
fixture corpus; it does not rewrite the loading logic.

```bash
./run.sh          # extract -> generate -> assert -> version-bump gate
```

## What is reachable from the bundle

All of it, at runtime, from the IIFE — nothing needed from `src/` or the `.d.ts`:

| Export | Gives |
| --- | --- |
| `vlAllTemplateDefs` and its `ec` / `cjs` / `pl` / `excel` siblings | per-backend chart types, each with `channels`, `markCognitiveChannel`, `properties`, `encodingActions` |
| `def.properties[]` | `ChartPropertyDef`: `key`, `type`, `label`, `defaultValue`, `min`/`max`/`step`, `options`, `check` |
| `def.encodingActions[]` | `EncodingActionDef`: `key`, `label`, `dependencies`, `isApplicable`, and a `control` block of the same shape. **The second half of the vocabulary** — 21 entries, keys `colorScheme` and `sort` |
| `channels`, `channelGroups` | the 26 channels and their 5 groups |
| `SemanticTypes` | 44 semantic type names |
| `THEME_PRESETS` | 10 preset names |

At flint-chart@0.5.1 that is **48 distinct chart types across 5 backends** (36 vl,
37 ec, 22 cjs, 38 pl, 18 excel; union 48, intersection 11) and **317 declared entries**
— 296 from `properties[]` plus 21 from `encodingActions[]` — generating **151 Pydantic
models**.

> ⚠️ **Read both arrays.** An earlier pass of this probe read only `properties[]` and
> concluded Flint "under-declares" because `Heatmap.colorScheme` was missing. It is not
> missing; it lives in `encodingActions`. Reading one array under-reports by 21 entries
> and produces a wrong verdict on how strict the façade may be.

> ⚠️ **ADR-0002 Decision 7 says "33 strings".** The pinned bundle ships 48, and there
> is no single flat list — the vocabulary is per backend. A `Literal` of 33 cannot be
> right for any backend. Decision 7 needs the number and the shape corrected.

## How strict may the façade be?

Only one of the two strictness knobs turns out to cost anything.

**Unknown keys — forbid them. It is free.** Once `encodingActions` is read, every key
the corpus uses *and Flint honours* is declared. The only two undeclared keys are
`Rose Chart.innerRadius` (removed in 0.5.1) and `Strip Plot.jitterWidth`, and the probe
measured both: **neither changes the compiled output**. Flint accepts and ignores them.
Rejecting them loses no capability — it reports corpus drift.

**`min`/`max` — do not enforce them. They are slider bounds.** `Bar Table.maxRows`
declares `min: 5`, yet the corpus uses `maxRows: 0` as a live "no limit" sentinel and
the compiled spec differs from both `5` and `20`.

`generate.py` emits three modes so the split is visible rather than argued:

| | unknown keys | `min`/`max` | real fixtures admitted | catches `logScale` typo |
| --- | --- | --- | --- | --- |
| `strict` | forbid | `ge`/`le` | 27 / 30 | yes |
| **`keys`** ← recommended | **forbid** | **metadata** | **28 / 30** | **yes** |
| `advisory` | allow | metadata | 30 / 30 | **no** |

`keys` loses only the two drifted fixtures. `advisory` admits everything, including
every misspelling, which makes it no safer than passing a bare `dict` to Flint.

### Why a misspelling matters at all

Flint never raises on an unknown key — it ignores it. Measured on a real Scatter Plot
fixture, with `logScale_y` the correct name:

| written into `chart_spec` | Flint raises | compiled spec changes |
| --- | --- | --- |
| `logScale_y` | no | **yes** |
| `logScale` | no | no |
| `logscale_y` | no | no |
| `logScaleY` | no | no |

A wrong name produces a chart that silently ignores the instruction, with no error
anywhere in the library, the client or the logs. **This is not primarily a planner
risk** — a planner handed the generated schema as a constrained-output contract cannot
emit a bad name. It is a risk for the paths with no schema in front of them: a stored
input frame replayed on **zero-LLM refresh** after a Flint pin bump, a direct caller of
the public API, and the hosted product's spec editor.

`Rose Chart.innerRadius` is that failure, already in the corpus: it was valid at 0.2.1,
Flint removed it, and a stored frame using it now compiles to a chart quietly missing
its inner radius.

## The residue that cannot be generated

- **`check(ctx)` / `isApplicable(ctx)` — 161 of 317 entries (51%).** A JS closure over `ctx.encodings`,
  `ctx.channelSemantics` **and the data rows** (the `logScale` checks iterate rows
  looking for non-positives). It cannot cross into Python, and it should not try:
  applicability is a *client* concern, and since ADR-0001's amendment the client is
  where Flint already runs. The façade must admit what it cannot judge.
- **Required-ness.** There is no `required` flag anywhere in the metadata — the field
  set is `check, defaultValue, key, label, max, min, options, step, type`. Every
  property is optional. Nothing to derive, nothing to hand-write.
- **`encodingActions.dependencies`** (e.g. `colorScheme` depends on the `color`
  channel) is extracted but not yet enforced; it is a cross-field rule, not a type.
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

- **The vocabulary lives in two arrays**, `properties` and `encodingActions`. Reading
  one is the single easiest way to get this wrong, and it produces a confident,
  wrong answer about how strict the façade may be.
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
| `generate.py` | `vocab.json` → Pydantic models: `keys` (recommended), `strict`, `advisory`. |
| `test_facade.py` | the assertion, both modes, against the 30 real fixtures. |
| `check_bump.py` | the fail-loud narrowing gate between two vocabularies. |
