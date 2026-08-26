# 9. What the façade validates

- **Status:** Accepted
- **Date:** 2026-08-26
- **Settled on:** [#36](https://github.com/thearcscode/chartagent/issues/36)
- **Builds on:** ADR-0001 (pin Flint; compile in the client), ADR-0002 (the input frame *is*
  the spec; Decision 7's generated façade), ADR-0005 (`bind` is the public seam; the error
  taxonomy)
- **Amends:** ADR-0002 Decisions 4, 5 and 7, and ADR-0005 Decisions 3, 8, 10 and 12 — all
  recorded as dated errata in place, and listed under *What this amends*

## Context

ADR-0002 Decision 7 committed to a typed Pydantic façade **generated from the pinned
bundle, never hand-written**. That claim survives intact. Two specifics inside it did not.

The façade-generation probe ([#17](https://github.com/thearcscode/chartagent/issues/17))
proved generation works from the bundled IIFE alone, and in doing so falsified the shape:
`chartType` is not a flat `Literal` of 33 strings. The pinned bundle ships **48 chart types
in union and 11 in intersection**, and the vocabulary is **per backend** — 36 vegalite, 37
echarts, 22 chartjs, 38 plotly, 18 excel. One flat list is wrong for every backend at once.

The probe's own first answer on strictness was then withdrawn. It had read one of the two
arrays Flint's vocabulary lives in, concluded Flint "under-declares", and recommended a
permissive façade on that basis. `encodingActions[]` sits alongside `properties[]` — 21
entries to 296 — and reading both moves the count to **317 declared entries** and removes
the argument. The corrected recommendation was to forbid unknown *names* while treating
declared `min`/`max` as metadata. This ADR confirms that and settles the rest.

### What the rejection path is for

Not planner typos. A planner handed the generated schema as a constrained-output contract
cannot emit a bad name, and producing that schema is the façade's primary job. The
rejection path exists for the callers with **no schema in front of them**: **zero-LLM
refresh** replaying a stored frame across a pin bump, direct callers of the public API, and
the spec editor in [#27](https://github.com/thearcscode/chartagent/issues/27).

`Rose Chart.innerRadius` is that failure already sitting in the corpus — valid at 0.2.1,
removed at 0.5.1, and a stored frame using it today compiles to a chart quietly missing its
inner radius, with no error anywhere in the library, the client or the logs.

### The test every decision below is measured against

Flint **never raises on an unknown key** — it ignores it. So "does Flint accept this?" is
not a question with any information in it, and the useful test is two-part:

- **Declared** — the pin's runtime arrays name it.
- **Honoured** — adding or removing it changes the compiled chart, with the assembler's
  `_`-prefixed metadata (`_options`, `_transform`, `_pivot`, `_width`, `_height`) stripped
  before comparison.

That stripping is load-bearing. An unknown encoding flips `applicable` flags inside
`_options` without touching the chart, so a naive whole-output diff reports capability that
does not exist. Two channel names outside the pin's export appeared honoured until the
metadata came off, and then did not.

### The ticket asked about one key; the failure lives in six

[#36](https://github.com/thearcscode/chartagent/issues/36) asks how strictly the façade
validates `chart_spec.chartProperties`. The same silent-ignore failure lives in
`encodings`, in the encoding objects themselves, in `theme_spec`, in `semantic_types` and
in `options` — and measured against the test above, **they do not all answer the same
way**. A strictness decision covering one key of six would have left the document half
open.

## Decision

**Forbidding is free exactly where the pin declares the vocabulary, and nowhere else.**

Six sites, one test, six answers:

| site | verdict | measured basis |
| --- | --- | --- |
| `chart_spec.chartType` | generated `Literal` of the pin's union | 48 union / 11 intersection, per backend |
| `chart_spec.chartProperties` **keys** | **forbid** | both undeclared corpus keys change nothing compiled |
| declared `min` / `max` / `step` | metadata, never bounds | `Bar Table.maxRows: 0` is honoured under a declared `min: 5` |
| `chart_spec.encodings` **channel names** | **forbid** against the global export | 0 corpus uses outside it; 0 honoured outside it |
| per-chart-type `channels` list | affordance metadata, **not** a gate | 19 undeclared pairs Flint honours |
| encoding **objects** | `str \| {field, type?}`, **forbid** extras | `field` ×1830, `type` ×3, 12 shorthand strings |
| `theme_spec` | closed presets, loose custom object, never `null` | unknown preset throws; object compiles; `null` crashes |
| `semantic_types` **values** | generated `Literal` | a bogus name is silently ignored today |
| `options` | **`extra='allow'`** — the exception | three honoured keys the pin declares nowhere |

### 1. `chartType` is a generated `Literal` of the pin's union; the backend narrows at `bind`

One `InputFrame`, whose `chartType` is a `Literal` generated from the union of every
backend's chart types at the pin — 48 today, and **the number is not frozen by this ADR**.
The per-backend lists stay data in `vocab.json`, surfaced by `vocabulary(backend)` and
checked at `bind`.

A name in **no** backend's list is `SpecVocabularyError`. A name in some backend's list but
not the requested one is `BackendCapabilityError`. Flint itself throws in both cases —
`Unknown chart type: Bogus Chart`, and `Unknown Chart.js chart type: Regression` — but it
throws **in the browser**, where ADR-0001's amendment put the compile. That is not an error
surface we own, and a caller of a Python library should not learn about a bad chart type
from a JavaScript stack trace at the far end of a round trip. Python raises first.

Five per-backend frame classes were the obvious alternative and are rejected under
*Alternatives*: they collide with ADR-0005 Decision 2, which keeps one stored frame
renderable to five backends.

### 2. Validation is two-phase, because the frame has no backend

Property key sets are **not** shared across backends. Only **9 of 48** chart types carry an
identical key set on every backend that ships them; `Scatter Plot` is 6 properties on
vegalite, 1 on echarts, 1 on chartjs, 1 on plotly and 0 on excel. Three keys go further and
change *type or options* between backends — `Area Chart.stackMode` loses `normalize` on
chartjs, and `Radar Chart.filled` is `binary` on vegalite and `discrete` everywhere else.

So a model keyed on `chartType` alone cannot exist, the generated models are per
**(backend, chart type)**, and `InputFrame` — which has no backend, by ADR-0005 Decision 2
— cannot statically type `chartProperties`. The split:

- **The frame validates what is backend-free**: `chartType` against the pin union, channel
  names, encoding objects, `theme_spec`, `semantic_types`.
- **`bind` validates what is backend-keyed**: chart-type membership in the requested
  backend, then `chartProperties` against the generated model for (backend, chartType).

The generated models stay public, for a caller who already knows the backend and wants the
check earlier.

A validation *context* — `model_validate(spec, context={"backend": …})` with a dispatching
model validator — was the tidier-looking alternative and is rejected: a directly
constructed `InputFrame(...)` skips dispatch entirely, `mypy` cannot see through the
context, and it puts a `pydantic.ValidationError` on precisely the path ADR-0005 Decision
10 closed.

### 3. Unknown keys in a declared vocabulary are forbidden — one mode, no switch

`extra='forbid'` wherever the pin declares the vocabulary. Once both arrays are read, every
key the corpus uses **and Flint honours** is declared. The only two undeclared keys in 705
fixtures are `Rose Chart.innerRadius` and `Strip Plot.jitterWidth`, and both were measured:
**neither changes the compiled output**. Rejecting them loses no capability — it reports
drift, which is the entire point.

The probe generated three modes so the choice was priced rather than argued:

| mode | unknown keys | `min`/`max` | property fixtures admitted | catches a misspelling |
| --- | --- | --- | --- | --- |
| `strict` | forbid | `ge`/`le` | 27 / 30 | yes |
| **`keys`** ← shipped | **forbid** | **metadata** | **28 / 30** | **yes** |
| `advisory` | allow | metadata | 30 / 30 | **no** |

**`keys` ships, and the generator emits it only.** No mode argument survives into the
build. A build-time knob that changes what the library rejects is the second grammar
ADR-0002 exists to prevent; `strict` and `advisory` stay priced in this table and nowhere
else.

This confirms rather than establishes: ADR-0005 Decision 3 already shipped
`SpecVocabularyError` as a hard error with no warn-and-strip. Choosing `advisory` here
would have required reopening it — to buy a façade that catches no misspelling at all, and
is therefore no safer than handing Flint a bare `dict`.

### 4. Declared `min` / `max` / `step` are metadata, never validation bounds

They are slider bounds for a UI, and treating them as a contract rejects working charts.
`Bar Table.maxRows` declares `min: 5`; the corpus uses `maxRows: 0` as a live "no limit"
sentinel, and the compiled spec differs from both `5` and `20`.

They are emitted into the generated model's `json_schema_extra` as custom keys — **never**
as Pydantic `ge`/`le`, and never as JSON Schema `minimum`/`maximum`, either of which would
reject that sentinel. They are also carried on `vocabulary()` for
[#27](https://github.com/thearcscode/chartagent/issues/27)'s form. Two carriers is not
duplication: `vocabulary()` is the form's source of truth, and `json_schema_extra` keeps
the constrained-output schema self-describing for a planner that never calls `vocabulary()`.

### 5. Channel names are forbidden globally, and **not** narrowed per chart type

The two halves of the channel vocabulary answer in opposite directions, and this is the
finding [#36](https://github.com/thearcscode/chartagent/issues/36) did not have.

**The global export is closed.** 26 channel names. No fixture in 705 uses a name outside
it. Sweeping 33 vegalite chart types, no name outside it was honoured once metadata was
stripped. A misspelled `colour` or a hallucinated `zzz` is silently ignored by Flint today
and rejected by the façade after this — free, by the same argument as Decision 3.

**The per-chart-type list under-declares.** Sweeping every chart type against every channel
it does not declare found **19 pairs that change the compiled chart** — `Area Chart.detail`,
`Pyramid Chart.column`/`row`/`group`, `Ranged Dot Plot.column`/`row`/`group`, `Pie Chart.x`,
`Heatmap.group`, `Streamgraph.detail` among them — against 797 that are ignored. Narrowing
the type to that list would forbid capability Flint ships.

So `def.channels` is exactly what `properties[]`'s `min`/`max` turned out to be: an
affordance registry for a UI, carried by `vocabulary()` so
[#27](https://github.com/thearcscode/chartagent/issues/27)'s form can grey out what a chart
type does not advertise, and **not** a validation gate.

The corpus's one vegalite counter-example is not one: `Grouped Bar Chart` sets an
undeclared `color`, and removing it changes nothing in the compiled chart — it moves an
`applicable` flag in stripped metadata. Excel's 104 `column`/`row` fixtures are a different
error entirely; see Decision 10.

### 6. Encodings are `str | {field, type?}` with extras forbidden — and `aggregate` is the one deliberate narrowing

No runtime array declares the shape of an encoding *value*, so this type is hand-written,
against measurement. Across 705 fixtures: **1842 channels — 1830 objects and 12 shorthand
strings** (all on `Choropleth` and `Map`). Inside the objects, exactly two keys: `field`
×1830 and `type` ×3, every `type` being `"temporal"`.

- `Encoding = str | EncodingObject`. The 12 shorthand strings are admitted and
  **normalised to `{field}` on validation**, so canonical JSON has one shape — the same
  reason ADR-0002 Decision 5 omits nulls.
- `EncodingObject` is `field` required, `type` optional, `extra='forbid'`.
- `type` stays an optional `str`, **not** a `Literal`. The bundle exports predicates
  (`isOrdinalType`, `resolveEncodingType`), not a type vocabulary, and a union synthesised
  from one observed value would be exactly the hand-written vocabulary Decision 7 forbids.
- **Array-valued channels are not admitted.** 0 of 705, never verified to route at all, and
  layers are out of scope by ADR-0002 Decision 8. Admitting them is a new decision, not an
  oversight here.

**`aggregate` inside an encoding is forbidden, and it is the single deliberate narrowing in
this ADR.** It is measured as *honoured* — adding it changes the compiled chart — so
Decision 3's "forbidding is free where the pin declares" does not license rejecting it.
ADR-0002 Decision 4 does: encodings reference transform output and never aggregate, because
the transform is the only place derivation happens. Flint does not enforce that rule for
us, as Decision 4 claimed it did. The façade does. `extra='forbid'` is the mechanism, and
this paragraph is the record, so the next person who measures `aggregate` reads a decision
rather than a bug.

The same `extra='forbid'` will reject other encoding keys nobody has swept — `bin`,
`timeUnit`, whatever else the templates read. Finding one that is honoured is a new
decision about that key, not a defect in forbidding.

### 7. `theme_spec` is a closed preset list, a loose object, or absent — and never `null`

Three measurements, three clauses:

- **Presets are closed at 10**, and Flint *throws* on an unknown one — *Unknown theme
  `notatheme`. Flint ships: nyt, economist, …* — a generated `Literal` catches in Python
  what would otherwise be a browser throw — the same argument as Decision 1.
- **A custom theme object compiles.** `{name, colors}` is accepted, so a bare `Literal`
  would forbid real capability. `ThemeSpec` is hand-written, `extra='allow'`, and stays
  loose, because its shape is in no metadata array.
- **`theme_spec: null` crashes Flint** — `Cannot read properties of null (reading
  'extends')`. It is rejected as `SpecShapeError`, not coerced to absent. ADR-0002 Decision
  5's omit-nulls rule is therefore load-bearing for this field and not merely a diff
  convention.

The type is `Literal[<pin's presets>] | ThemeSpec`, omitted when unset.

### 8. `semantic_types` values are generated; its keys are not

Values get a `Literal` generated from the pin's semantic-type export — 44 names today. A
bogus name is silently ignored by Flint and changes nothing, which is precisely the
silent-ignore class this ADR closes; a real name changes the compiled chart.

Keys are transform **output** column names and stay `str`. Whether a named column exists is
ADR-0005 Decision 7's two-check schema-drift problem, which already owns it, and an unknown
key is measured as inert.

### 9. `options` is the exception, and it is `extra='allow'`

The frame's top-level `options` bag has **no declared vocabulary anywhere in the bundle**.
`getChartOptions()` looks like one and is not — it returns the resolved *properties* for a
chart, which is what `_options` carries in the assembler's output.

The corpus uses five keys (`addTooltips`, `elasticity`, `maxStretch`, `facetElasticity`,
`maintainContinuousAxisRatio`). Measurement found at least three more that **change the
compiled chart** and appear in no fixture: `defaultBandSize`, `facetGap`,
`facetFixedPadding`. So the namespace is genuinely wider than anything we can enumerate,
and forbidding here would reject working charts while asserting a closed set the pin does
not give us.

`options` is `extra='allow'`. A misspelled `addTooltip` stays silent, and that is the
accepted cost. **No hand-written union of measured names** — that would be a parallel
vocabulary maintained by grep, drifting at the first bump, which is the failure mode
Decision 7 was written to prevent.

### 10. Two levels, one test: what the pin knows nowhere versus what it knows elsewhere

The test from Decision 1 applies unchanged one level down, at the property site. The lookup
is **this key × this chart type × any backend at the pin** — not "this key anywhere".

| the pin declares it… | error | example |
| --- | --- | --- |
| nowhere | `SpecVocabularyError`, `kind="property"` | `Rose Chart.innerRadius`, `Strip Plot.jitterWidth` |
| for another backend, not this one | `BackendCapabilityError`, naming the keys | `Rose Chart.padAngle` — vegalite yes, echarts/chartjs/plotly no |

This is not a corner. **9 of the 30 property-carrying fixtures** are rejected by at least
one other backend that ships the same chart type. Collapsing both into
`SpecVocabularyError` would make a *portable* document indistinguishable from a *stale*
one, and would silently rewrite ADR-0005 Decision 10's "a key the pin does not declare"
into "a key this backend's model does not declare". Warn-and-strip is not available;
ADR-0005 Decision 3 refused it.

`BackendCapabilityError` therefore **names the offending keys** when the failure is a knob
rather than a chart type. And when one document carries both kinds at the property site,
`SpecVocabularyError` wins — Decision 11's order — carrying every nowhere-key as a tuple;
the next `bind` reports the portable keys as `BackendCapabilityError`.

None of this weakens ADR-0005 Decision 2. "One stored frame, five backends" was never "every
knob works on every backend" — 38 of 705 fixtures already fail at chart-type grain on
ECharts, 110 on Chart.js, 340 on Excel. This makes the same fact legible one level finer.

### 11. First failing site wins, and it carries every offender of its own kind

`kind` is singular (Decision 12), so one error cannot mix a bad channel with a bad property.
The order is fixed, and backend-free checks run before backend-keyed ones so that a bogus
channel is never hidden behind "this backend cannot draw this chart type":

1. shape — the 5-key envelope, inline `data`, `theme_spec: null` → `SpecShapeError`
2. `chartType` ∈ the pin union
3. channel names ∈ the global export
4. encoding-object keys — `kind="encoding_key"`, including `aggregate`
5. `theme_spec` preset / `semantic_types` values
6. `chartType` ∈ **this** backend → `BackendCapabilityError` (no property model exists yet)
7. `chartProperties` against the (backend, chartType) model → `SpecVocabularyError` for
   nowhere-keys and bad enum options, `BackendCapabilityError` for portable keys

Step 6 sits immediately before step 7 because step 7 *selects its model* by (backend,
chartType) and cannot run without it.

Each error carries **all** offenders of its own kind as a tuple, following
`SchemaDriftError.drifted`. Three misspelled property keys are one `SpecVocabularyError`
naming three — not three refresh round-trips, which matters most on the zero-LLM path,
where every raise costs a human a cycle.

### 12. `SpecVocabularyError` gains a `kind`

It now covers seven rejection sites, and a caller that wants to special-case theme drift
should not have to match on message text:

```python
kind: Literal["chart_type", "channel", "property", "enum_option",
              "semantic_type", "theme_preset", "encoding_key"]
```

Plain strings at runtime, not a `StrEnum` — the house style ADR-0005 set with
`SchemaDriftError.stage` and `RawSqlRejectedError.reason`. Alongside the key, chart type,
backend and pin that Decision 10 of that ADR already names.

Two names are deliberate. It is `enum_option`, not `option`, because `options` is the one
bag this ADR does **not** reject on and the collision would be read backwards. And
`encoding_key` is required rather than convenient: Decision 6's `extra='forbid'` rejects
both `zzz` and `aggregate` inside an encoding object, and without it that path has no
discriminant — `key="aggregate"` with `kind="encoding_key"` is the Decision 6 narrowing as
a caller sees it.

### 13. The bump gate fails on exactly what the façade rejects on

`check_bump.py` exits non-zero on a **narrowing**, and the vocabulary it guards is now
bigger than the properties #17 measured. Six narrowings, plus the export check it already
had:

| narrowing | why it breaks a stored frame |
| --- | --- |
| chart type removed from a backend's list | that frame no longer binds on that backend |
| global channel removed | a channel name that validated now raises |
| theme preset removed | `theme_spec` that validated now raises |
| semantic type removed | a `semantic_types` value that validated now raises |
| enum option removed | a property value that validated now raises |
| property removed or retyped | the key or its type no longer validates |
| **backend export missing** | kept from #17 — the extraction itself is unsound |

Reported, **non-fatally**: per-chart-type `channels` changes, `min`/`max`/`step` moves, and
`dependencies` changes. The façade does not reject on any of them, so none can break a
stored frame — but each changes what `vocabulary()` hands
[#27](https://github.com/thearcscode/chartagent/issues/27)'s form, which a reviewer should
see in the diff.

The rule, stated once: **the gate fails on exactly what the façade rejects on; anything the
façade merely exposes is a report.**

This widens what ADR-0005 Decision 12 and
[#19](https://github.com/thearcscode/chartagent/issues/19) count as a breaking release. A
removed theme preset, global channel, semantic type or per-backend chart type each means a
frame that bound yesterday raises today, which is a major under pre-1.0 SemVer exactly as a
removed property already was.

### 14. `encodingActions.dependencies` is exposed, not enforced

`colorScheme` declares a dependency on the `color` channel; `sort` on `x` and `y`. 21
entries, 6 carrying dependencies per backend, and **0 of 705 fixtures violate one**.

Enforcement would cost nothing measured, and is still refused. `dependencies` lives in the
same `control` block that carries the slider bounds Decision 4 just demoted — it is an
affordance-*enablement* hint, and promoting it to a validity rule repeats that mistake in
new clothes. A `colorScheme` set with no `color` channel is a **declared key with no
effect**: that is applicability, which is the client's `check()` / `isApplicable()` — 161 of
317 entries, reading the data rows — and not the vocabulary class this ADR closes.

It is carried on `vocabulary()`, where ADR-0005 Decision 8 already put it for the form that
actually needs it. Growing a third "statically checkable applicability" class would only
give [#9](https://github.com/thearcscode/chartagent/issues/9) something else to route
around.

### 15. The seam with [#9](https://github.com/thearcscode/chartagent/issues/9)

This ADR owns what the pin **declares** — per-backend chart-type lists, property keys, enum
options, types, channel names, theme presets, semantic types — and the errors raised when a
document names something outside them.

[#9](https://github.com/thearcscode/chartagent/issues/9) owns what the backend and the data
can **do** — routing and backend choice, unsupported-as-a-routing-signal, the 161 of 317
data-dependent entries, the `theme_spec` gap on ECharts and Chart.js, and phase-2 field and
cardinality validation.

`BackendCapabilityError` sits on the line, so the line is drawn through it: **this ADR fixes
when it is raised — a pin-derived fact — and #9 decides what a router does with it.** P0
`bind` raises and does not re-route. That is `bind` having no router, not a decision taken
here on #9's behalf.

Excel's 104 faceting fixtures are the clean illustration. `column` and `row` are in the
global 26, so they pass Decision 5's gate; Flint's own Excel assembler throws *"Excel
backend does not support faceting in one native Excel chart"*; and
`bind(..., backend="excel")` raising `BackendCapabilityError` is correct. It is capability,
not vocabulary, and it stays #9's.

## What this amends

Recorded as dated errata in place, so a reader of the original decision is not required to
find this ADR to learn what changed.

| Document | What moved |
| --- | --- |
| **ADR-0002** D4 | "Flint enforces it for us" is false — `aggregate` on an encoding is honoured; the façade forbids it (Decision 6). The fate-table row *"Kept, and now enforced upstream"* is wrong on the same fact, and its denominator is 1842, not 1830 |
| **ADR-0002** D5 | Omit-nulls is load-bearing, not only a diff convention — `theme_spec: null` crashes Flint |
| **ADR-0002** D7 | The vocabulary is per backend and 48 wide, not a flat 33; strictness is this ADR |
| **ADR-0005** D3 | `chartProperties` cannot be statically typed on `InputFrame` — the frame has no backend (Decision 2) |
| **ADR-0005** D8 | `vocabulary()` also carries the per-chart-type `channels` list and the global channel, theme-preset and semantic-type lists |
| **ADR-0005** D10 | `SpecVocabularyError` gains `kind` (Decision 12); `theme_spec: null` is `SpecShapeError`; `BackendCapabilityError` names offending keys |
| **ADR-0005** D12 | The breaking-bump surface widens to themes, global channels, semantic types and per-backend chart types (Decision 13) |

## Consequences

**A stored frame can bind on one backend and raise on another, by design.** 9 of 30
property fixtures are in that position. The app's backend switcher
([#27](https://github.com/thearcscode/chartagent/issues/27)) must present
`BackendCapabilityError` as a capability conversation — *this chart uses vegalite-only
knobs* — rather than as corruption.

**Two of the corpus's fixtures are rejected by design, and that is ADR-0004's dirty-input
count of 2.** `Rose Chart.innerRadius` and `Strip Plot.jitterWidth` are already the two
dirty inputs ADR-0004 names, present inside the 0.5.1 cookbook itself: the tag's own
`input.json` is stale relative to its templates, so pairing `FLINT_VERSION` with
`FIXTURE_COMMIT` does not clear them. They are the `SpecVocabularyError` positive tests, not
corpus the façade failed to admit. **No allowlist of forgiven keys ships in the library** —
[#24](https://github.com/thearcscode/chartagent/issues/24) already owns the dirty count
(fail if it grows, never an exceptions file) and the pairing rule.

**The library's corpus assertions become:** 28 of 30 property fixtures admit; the 2 raise
`SpecVocabularyError` by name; Excel faceting raises `BackendCapabilityError` on that
backend only.

**A misspelled `options` key stays silent forever**, or until Flint declares that bag.
Accepted in Decision 9, and it is the only silent-ignore path this ADR leaves open.

**Every generated `Literal` is a pin-shaped hazard.** Chart types, channels, themes,
semantic types and enum options are now all things a bump can narrow, and each narrowing
turns a frame that bound yesterday into one that raises today. That is why Decision 13
exists, and why the count in it is deliberately not written into any type as a magic number.

**`mypy --strict` sees less than it looks like it does.** `chartProperties` is an open
mapping on `InputFrame` and only sharpens at `bind`, so the static story for a caller who
never names a backend is `chartType`, channels and encodings — not properties.

## What this feeds

- [#9](https://github.com/thearcscode/chartagent/issues/9) inherits `BackendCapabilityError`
  fully specified — when it raises, and what it names — and owes only the routing answer.
- [#27](https://github.com/thearcscode/chartagent/issues/27)'s form now has a complete
  metadata contract: per-chart-type channels, `min`/`max`/`step`, `dependencies`, option
  labels and `data_dependent`, all on `vocabulary()`, none of them gates.
- [#24](https://github.com/thearcscode/chartagent/issues/24) gains the expected-rejection
  set, and Decision 13 gives its bump job the fatal/report split.
- The planner-output contract inherits a constrained-output schema that is now closed over
  the whole document rather than one key of it.

## Alternatives rejected

**Five per-backend frame classes** (`VegaLiteFrame.chartType: Literal[36]`, …). Static
narrowing at `mypy` time, and it collides head-on with ADR-0005 Decision 2: a
`VegaLiteFrame` that cannot be handed to `backend="echarts"` makes the 11-type intersection
unexpressible without a cast, and turns "switch the backend" into a document mutation.

**`chartType: str`, membership checked elsewhere.** Gives up the closed membership Decision
7 exists for, and hands the planner a schema that constrains nothing.

**`advisory` mode** (`extra='allow'`, bounds as metadata). Admits all 30 fixtures and catches
no misspelling, which makes the façade no safer than a bare `dict`. It also rested on the
withdrawn under-declaration finding, and adopting it would have required reopening ADR-0005
Decision 3.

**`strict` mode** (`extra='forbid'` plus `ge`/`le`). Rejects 3 of 30, including
`Bar Table.maxRows: 0`, which Flint honours. It enforces a UI's slider as a contract.

**Narrowing channels per chart type.** Rejected on 19 measured pairs Flint honours.

**A hand-written union of measured `options` names.** A parallel vocabulary maintained by
grep, drifting at the first bump — the exact failure ADR-0002 Decision 7 forbids.

**Enforcing `encodingActions.dependencies`.** Free on the corpus and still wrong: it
promotes an affordance hint to a validity rule, and applicability is the client's.

**A validation context on `model_validate`.** Skipped by direct construction, invisible to
`mypy`, and puts `ValidationError` on the seam path ADR-0005 Decision 10 closed.

**Shipping the generator's three modes behind a flag.** A build-time knob that changes what
the library rejects is a second grammar.

## Evidence

Measured 2026-08-26 against **`flint-chart@0.5.1`** — the pinned IIFE at
`prototypes/flint-embed/build/flint.iife.js` — and the 705-fixture corpus at
`FIXTURE_COMMIT`. Comparisons strip the assembler's `_`-prefixed metadata keys, without
which several results invert.

- 48 chart types in union, 11 in intersection; 36 vegalite / 37 echarts / 22 chartjs / 38
  plotly / 18 excel. 317 declared entries — 296 `properties[]` plus 21 `encodingActions[]`
  — generating 151 models (#17, `prototype/facade-codegen`).
- Property key sets identical across the backends shipping them: **9 of 48**. Same key,
  divergent type or options: 3 — `Area Chart.stackMode`, `Stacked Bar Chart.stackMode`,
  `Radar Chart.filled`.
- Undeclared property keys in the corpus: 2, neither honoured. Mode pricing 27 / 28 / 30 of
  30 (#17's correction).
- Channels: 26 exported; **0** corpus uses outside the export; **0** names outside it
  honoured. Per-chart-type sweep across 33 vegalite types: **19 undeclared pairs honoured**,
  797 ignored. `Lollipop Chart.stroke` and `.series` appear honoured until `_options` is
  stripped, then do not.
- Corpus channel names undeclared for their chart type: 1 vegalite (no compiled effect), 3
  echarts, 3 chartjs, 3 plotly, **104 excel** — all `column`/`row`, and Flint's Excel
  assembler throws on them by name.
- Encoding values: **1842 channels — 1830 objects, 12 shorthand strings**; keys inside
  objects are `field` ×1830 and `type` ×3, every value `"temporal"`. `zzz` and `typo` inert;
  **`aggregate` honoured**.
- `theme_spec`: 10 presets; unknown → Flint throws naming the ten; `{name, colors}` object
  → compiles; `null` → `Cannot read properties of null (reading 'extends')`.
- `semantic_types`: 44 names; a bogus value inert; a real value changes the chart; an
  unknown column key inert.
- `options`: corpus uses 5; `defaultBandSize`, `facetGap` and `facetFixedPadding` change the
  chart and are declared nowhere; `getChartOptions()` returns resolved properties, not a
  frame-option vocabulary.
- Chart-type errors: `Unknown chart type: Bogus Chart` (vegalite); `Unknown Chart.js chart
  type: Regression` — both thrown in the client, not reachable from Python.
- Cross-backend property rejection: **9 of 30** property fixtures rejected by at least one
  other backend shipping the same chart type; `Rose Chart.padAngle` is the clean case.
- `encodingActions.dependencies`: 21 entries, 6 with dependencies per backend
  (`sort`←`x,y`, `colorScheme`←`color`); **0 of 705** corpus violations.

These were exploratory probes over the pinned bundle, not committed fixtures. The ones that
guard a rejection — the two undeclared property keys, the channel export, the `aggregate`
narrowing, `theme_spec: null`, and the 9 cross-backend property cases — should become tests
when the façade is built, because each encodes an assumption about the pin that a bump can
move.

## Related

- ADR-0001 — the pin, and the amendment that put the compile in the client, which is why a
  Flint throw is not an error surface we own.
- ADR-0002 — Decision 4 (no aggregate at the encoding, amended here), Decision 5 (canonical
  JSON and omit-nulls, amended here), Decision 7 (the generated façade, amended here),
  Decision 8 (layers out of scope, why array-valued channels stay out).
- ADR-0004 — the fixtures invariant, the pin-pairing rule, and the dirty-input count of 2
  that Decision 3's two rejects are.
- ADR-0005 — `bind`'s signature, `backend` as a required kwarg, the error taxonomy and
  `vocabulary()`; amended here in four places.
- [#17](https://github.com/thearcscode/chartagent/issues/17) — the generation probe, its
  correction, and `prototype/facade-codegen`.
- [#9](https://github.com/thearcscode/chartagent/issues/9) — capability and routing; see
  Decision 15 for the line.
- [#24](https://github.com/thearcscode/chartagent/issues/24) — owns the dirty count and the
  pin pairing this ADR leans on.
- Not decided here: routing behaviour on `BackendCapabilityError` (#9); array-valued
  channels; any encoding key beyond `aggregate` that proves honoured; whether `options` ever
  gains a declared vocabulary upstream.
