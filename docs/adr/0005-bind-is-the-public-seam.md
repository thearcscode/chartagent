# 5. `bind` is the public seam

- **Status:** Accepted (amended 2026-08-26, 2026-08-27)
- **Date:** 2026-08-23; Decisions 1, 7, 10 and 11 amended 2026-08-26 (ADR-0008); Decisions 3, 8, 10 and 12 amended 2026-08-26 (ADR-0009); Decisions 5, 7 and 11 amended 2026-08-27 (ADR-0010) — **Decision 7's retype deferral is closed**
- **Settled on:** [#25](https://github.com/thearcscode/chartagent/issues/25)
- **Builds on:** ADR-0001 (pin Flint; compile in the client), ADR-0002 (the input frame
  *is* the spec), ADR-0003 (rasterise in a browser — this ADR supplies the `Rasteriser`
  signature it deferred), ADR-0004 (fixture jobs)
- **Amends:** PRD §7.8's public API sketch and P0.11's `chartagent.render(spec, data)` /
  `result.refresh()`. The requirement is unchanged; the names are not.
- **~~Leaves open~~ — closed 2026-08-26 by ADR-0009:** how strictly the generated façade
  validates, and how `chartType` is typed per backend
  ([#36](https://github.com/thearcscode/chartagent/issues/36)). No signature here moved, as
  predicted — but four decisions gained errata, listed in ADR-0009's *What this amends*.

## Context

Two tracks run in parallel — the library here, the hosted product in
`thearcscode/chartagent-studio` — and the entire risk of that parallelism sits in one
place. If the app's needs are unknown when the library's public API is set, the app
blocks on the library and "parallel" becomes "serialised with extra steps". This ADR
fixes the P0 surface: no planner, no LLM, no agent.

The question arrived carrying three premises that the amendments of the last two days
had already voided. All three are recorded because each one, left standing, produces a
different and wrong API.

**There is no sanctioned exception for the app.** The ticket described the app as a
plain consumer *"with process/tenant isolation as the one sanctioned exception"*. That
exception was the JavaScript context pool. ADR-0001's 2026-08-22 amendment deleted the
engine, and with it
[#21](https://github.com/thearcscode/chartagent/issues/21). There is no JS realm, so
there is no isolation seam. The app is a plain public-API consumer, full stop —
which makes dogfooding the only test of this surface, exactly as the ticket hoped, and
Decisions 8 and 11 below are two gaps that test found.

**Python cannot see `_warnings`, and there is no "resolved" `baseSize`.** The ticket
asked what rides along in the return: *"`_warnings` from Flint, the resolved
`baseSize`"*. Both are **compile** outputs, and compile is client-side JavaScript
(ADR-0001 Decision 5). `_warnings` are produced by `assemble*` in the browser;
`baseSize` is an *input*, pinned in the stored spec by ADR-0002 Decision 6, so
"resolved" has no referent. These are not questions this ADR gets to answer — they are
capabilities the library does not have. 71 of 705 upstream fixtures warn on their own,
and none of that reaches CPython unless a client posts it back.

**There are no JavaScript internals to leak.** The ticket asked how an engine-level
failure surfaces *"without leaking JavaScript internals"*. Python executes no
JavaScript at runtime. Node is a build-time tool for `extract.mjs` and the fixture jobs
(ADR-0004) and is never installed with the wheel (#19). The real shape of that concern
is the reverse: everything that fails *after* we hand over the envelope is the client's,
outside our error surface entirely. Decision 11 is the honest Python-side remainder.

What is left is a small, stateless surface. The library takes a stored frame and a data
source, runs the transform, and hands back the document a client compiles.

## Decision

**One entry point, `bind`, returning the ADR-0001 envelope. Everything else on the
public list exists because the hosted app cannot do its job without it.**

### 1. `bind` is the library's one P0 entry point, and it is synchronous

```python
def bind(spec: InputFrame | dict, data: DataSource, *, backend: Backend) -> Envelope
```

`bind` takes a stored frame plus a data source, runs `x_chartagent.transform` through
DuckDB, attaches the resulting rows as `input.data`, and returns the envelope. The
client then loads Flint at `flint_version`, calls `assemble*`, and renders. That is the
whole P0 pipeline.

**`render` is retired with no alias.** PRD P0.11 named `chartagent.render(spec, data)`,
written before ADR-0001's amendment. The library does not render, and it does not
compile — `CONTEXT.md` spends both of those words on jobs the client does. A caller who
writes `render()` and receives JSON they must still compile has been told something
false, and an alias would keep teaching it. `bind` is the new glossary term.

**`result.refresh()` is not P0.** PRD P0.11 names it alongside, but `result` is what
`create_chart_agent()` returns and there is no agent in Phase 0 — P0.11 is a *priority*
label, and §11's phase table puts the agent in Phase 1. When it lands, `result.refresh()`
is sugar over `bind`, so there is one operation and not two.

**Erratum — 2026-08-26 ([#4](https://github.com/thearcscode/chartagent/issues/4),
ADR-0008).** The signature gains one keyword:

```python
def bind(spec, data, *, backend: Backend, timeout: float | None = None) -> Envelope
```

ADR-0006 Decision 9 lists *a DuckDB statement timeout* among four caps "all as
configuration", while Decision 12 below lists *"DuckDB connection handling"* as private —
so Studio had a configured timeout and no way to reach it. Expiry raises `TransformError`.
This is the only one of ADR-0006's four caps that must live inside the library, because it
is the only one guarding *our* execution; the upload limit and the row cap stay Studio's.
`__all__` is unchanged — `timeout` is a keyword on a name already public.

**Synchronous, everywhere, including `Rasteriser`.** PRD §9 already puts the async API in
P1. Playwright ships a sync API, so the reference rasteriser costs nothing; a sync
protocol wraps into a threadpool trivially, whereas an async one poisons every caller
that is not already async. P1 adds `abind` and `arasterise` as siblings — not a
redesign.

### 2. The backend is an argument, not a field on the spec

`backend` is a **required keyword argument with no default**. The envelope's `backend`
key echoes it verbatim; the planner fills the same argument in P1.

It cannot be inferred: `chartProperties` is validated by a model selected by
**(backend, chartType)**, and the pinned bundle ships 48 chart types in union, 11 in
intersection (36 vegalite / 37 echarts / 22 chartjs / 38 plotly / 18 excel). `bind`
cannot validate a spec until it knows the backend.

It is deliberately **not stored on the spec**. One stored frame renders to five
backends; that is a real product argument, and storing the backend would make switching
a document mutation. No ECharts default despite ECharts being the default *web* target,
because 38 of 705 fixtures are unsupported by it — a silent default converts that into a
surprise at the far end of the call.

### 3. What `spec` is, and the two things `bind` refuses

`spec` is `InputFrame | dict`. Both are validated on the way in; the validated model is
always what comes back on the envelope. `InputFrame` is the hand-written 5-key frame
envelope — the one part of the façade that cannot be generated (#17) — whose
`chart_spec.chartProperties` is typed by a *generated* per-(backend, chart type) model.

**Erratum — 2026-08-26 ([#36](https://github.com/thearcscode/chartagent/issues/36), ADR-0009).**
`chartProperties` **cannot be statically typed on `InputFrame` at all**, because the frame
has no backend — Decision 2 above is what makes that so. Property key sets diverge per
backend for 39 of 48 chart types (`Scatter Plot` is 6 keys on vegalite, 1 on echarts, 0 on
excel), so no model keyed on `chartType` alone exists to hang on the field. ADR-0009
Decision 2 splits validation in two: the frame validates what is backend-free (`chartType`,
channel names, encoding objects, `theme_spec`, `semantic_types`), and `bind` validates what
is backend-keyed (chart-type membership in the requested backend, then `chartProperties`
against the generated model). On `InputFrame` the field is an open mapping.

ADR-0009 also splits the first refusal below in two. A key the pin declares **nowhere**
stays `SpecVocabularyError`; a key it declares for **another** backend but not the
requested one is `BackendCapabilityError` naming the keys — 9 of 30 property fixtures are
in that position, and collapsing them would make a portable document indistinguishable from
a stale one.

Two refusals:

- **A spec naming a key the pin does not declare is a hard `SpecVocabularyError`**,
  carrying the key, the chart type, the backend and the pin. No warn-and-strip.
  `Rose Chart.innerRadius` is this failure already sitting in the corpus: valid at 0.2.1,
  removed at 0.5.1, and a stored frame using it today compiles to a chart quietly missing
  its inner radius with no error anywhere in the library, the client or the logs. Surfacing
  that is what the rejection path is *for* — not planner typos, since a planner handed the
  generated schema as a constrained-output contract cannot emit a bad name.
- **A spec arriving with `input.data` inline is a hard `SpecShapeError`.** ADR-0002
  Decision 3 stores the frame without rows, and an inline `data` is ambiguous against the
  `data` parameter. This is also exactly what an `Envelope` round-tripped back into `bind`
  looks like, so the refusal catches a real mistake loudly.

### 4. What `data` is at P0

```python
DataSource = str | os.PathLike | ArrowStreamable | list[dict]
```

Local paths, `s3://` and `https://` URLs (DuckDB reads in place), any object exposing the
Arrow PyCapsule interface (`__arrow_c_stream__` / `__arrow_c_array__` — pyarrow, Polars,
Arrow-backed pandas), and `list[dict]` for the trivial case. That is PRD §7.4's flavours
1 and 3; Arrow is the internal interchange, per `docs/research/python-arrow.md`.

**Flavour 2 — connection-like pushdown — is P1**, where PRD §9 already puts it. It drags
dialect compilation and credential handling into a phase that has neither.

### 5. The envelope is three keys; diagnostics ride on the object, not on the wire

The envelope's serialised form is **exactly** ADR-0001's three keys:

```json
{ "flint_version": "…", "backend": "…", "input": { … } }
```

`Envelope.to_dict()` / `.model_dump()` emit those and nothing else. It is the wire format
the client compiles, and widening it would make it ours instead of Flint's.

The app still needs more than that — how long the transform took, how many rows came
back, what we quietly changed. Those hang off the `Envelope` **object** as attributes
that never serialise into `input`: `.row_count`, `.elapsed`, `.warnings`.

**Erratum — 2026-08-27 ([#42](https://github.com/thearcscode/chartagent/issues/42),
ADR-0010).** A fourth diagnostic joins them: **`.source_schema`**, the referenced-column
bucket map for the source this bind read. Same rule — it hangs off the object and never
serialises into `input`, and the wire format stays exactly three keys. `bind` already reads
this schema for ADR-0008 Decision 4's identifier allowlist and discarded it until now, so it
costs nothing new.

It is a diagnostic and not an accessor on purpose: computing it does **I/O against a
DataSource**, so exposing it as `source_schema(spec, data)` would have made it the second
verb that reads a source, against Decision 1's one-verb P0 surface. `__all__` is unchanged —
`Envelope` was already public and this is an attribute on it.

Name it for what it is: **what *this bind* saw**, never "the stored baseline". The stored
baseline is whatever a save wrote into `x_chartagent.source_schema`, which may be older, and
telling the two apart is the entire point of the comparison.

### 6. `bind` runs the transform in-process. No sandbox at P0

PRD §7.5 puts *"transform queries on both rails (LLM-derived)"* inside the sandbox. At
P0 there is no LLM anywhere: the transform was authored by the caller or by the app's
spec editor, running on the caller's own data in the caller's own process. Requiring a
sandbox would drag P0.6 into the headline call path and stop the app shipping a spec
editor without a sandbox backend.

So DuckDB runs in-process, and **`raw_sql` still gets P0.3's validation
unconditionally** — read-only, single statement, file-like sources only — because a
stored spec can arrive from anywhere, including the editor in
[#27](https://github.com/thearcscode/chartagent/issues/27).

**This is not a precedent for P1.** §7.5's rule is about *model-authored* SQL. When the
planner lands, planner-authored transforms route through the sandbox; that is the rail
work's call, not the seam's. Recorded explicitly, because left implicit someone will read
the P0 seam as permission to skip it.

### 7. Schema drift is two checks with one error, and retype detection is deferred

PRD P0.11 requires a typed `SchemaDriftError` naming renamed, dropped or retyped fields,
ignoring additive drift. Two things fall out that the requirement does not anticipate.

**There are two checks, not one.** Encodings reference *transform output* columns, never
source columns (ADR-0002 Decision 4). The cheap pre-flight schema read therefore covers
only the columns the **transform** reads; the encoding side cannot be checked until the
transform has run. When `raw_sql` is present its input columns are opaque without parsing
SQL, so even the pre-check degrades to a post-check.

One error type, `stage: Literal["source", "transform_output"]`, carrying
`drifted: tuple[DriftedField, ...]` with `name`, `kind: Literal["renamed", "dropped",
"retyped"]`, `expected` and `found`. Pre-check when the transform is declarative; skip
straight to the post-check when `raw_sql` is present.

**Erratum — 2026-08-26 ([#4](https://github.com/thearcscode/chartagent/issues/4),
ADR-0008).** *"Its input columns are opaque without parsing SQL"* is now conditional.
DuckDB will hand us its **own** parse tree — `json_serialize_sql(…)`, from the `json`
extension built into the wheel — which reports referenced column names and reports `STAR`.
ADR-0008 Decision 7 already requires that tree for the `raw_sql` relation allowlist, so the
column set is free once it is parsed. The rule becomes: **run the source-stage pre-check
when the tree yields a definite column set; skip to the post-check only when `STAR` is
present.** The transform-output check is unchanged — it can only ever happen after the
transform runs.

**Retype detection has no baseline, so it does not ship at P0.** Renames and drops need
nothing stored — the referenced names are in the document. A *retype* needs the type the
spec was planned against, and nothing in the frame records source dtypes (`semantic_types`
maps *output* columns to Flint semantic types, which is a different thing). The fix is a
`source_schema` map of referenced source columns, which is a sixth key in `x_chartagent`
and therefore an **ADR-0002 amendment** — graduated as its own ticket rather than smuggled
in here. Until it lands, P0.11's retype clause is unmet and the transform fails loudly
instead.

**Erratum — 2026-08-27 ([#42](https://github.com/thearcscode/chartagent/issues/42),
ADR-0010).** **The deferral is closed and retype detection ships.** ADR-0010 adds
`x_chartagent.source_schema` as the sixth key, over **seven coarse buckets** (`number`,
`string`, `boolean`, `date`, `timestamp`, `timestamptz`, `other`) rather than the raw dtypes
this paragraph imagined — the rule being *collapse where the chart does not change, split
where it does*, so `INTEGER` → `BIGINT` is silent and `VARCHAR` → `DATE` raises.

Two narrowings to the shape above. **`kind: "retyped"` is a `stage: "source"` kind only**:
within a revision the transform is immutable, so if every source bucket holds then every
output bucket holds, and output retype is *implied* rather than separately checkable — there
is no transform-output baseline and there should not be one. And **`expected` and `found`
both hold buckets** for a retype (`expected="string", found="date"`), with DuckDB's logical
type carried in the message instead, since naming `DATE` in a field would imply we compare
logical types when we deliberately do not.

A missing or partial baseline is **never** an error: it raises the `retype_unchecked`
advisory added to Decision 11, and columns that do have an entry are still checked.

### 8. Three accessors are public because the app cannot work without them

Each of these is a gap dogfooding found, not a convenience.

**`canonical_json`.** ADR-0002 Decision 5 makes canonical JSON (nulls omitted) the
spec-diff unit for patch mode.
[#28](https://github.com/thearcscode/chartagent/issues/28) needs the app's version
history to show *the same* diff the library defines. Unexposed, the app writes its own
and the two drift silently, since both produce plausible JSON. Public as
`InputFrame.canonical_json()`, re-exported as `chartagent.canonical_json(spec)`. It is
also what a content-addressed spec id is hashed over.

**`vocabulary`.** [#27](https://github.com/thearcscode/chartagent/issues/27) wants a form
generated from the per-chart-type properties. `model_json_schema()` under-serves it: a
form needs `label`, `step`, the `options` list with its labels,
`encodingActions.dependencies`, and the `data_dependent` flag for the 161 of 317 entries
whose `check()` runs client-side. `chartagent.vocabulary(backend)` returns the chart
types; `chartagent.vocabulary(backend, chart_type)` returns a `ChartVocabulary` — frozen
dataclasses over the committed `vocab.json`. Two things are carried deliberately:
`min`/`max`/`step` are documented in the type itself as **UI slider bounds, not validation
bounds** (#17's correction, so the app cannot repeat the mistake), and `data_dependent` is
exposed so a form can say applicability is the client's call. The generated Pydantic
models stay public too — they are in the signature — but forms are built from
`vocabulary()`.

**Erratum — 2026-08-26 ([#36](https://github.com/thearcscode/chartagent/issues/36), ADR-0009).**
`vocabulary()` carries more than this decision lists, because ADR-0009 demoted three things
from gates to affordances. `ChartVocabulary` also holds the **per-chart-type `channels`
list** — which under-declares by 19 measured pairs Flint honours, so it can inform a form
and must never validate one — and `vocabulary()` additionally exposes the **global channel
export**, the **theme presets** and the **semantic-type names**, all three of which *are*
closed and *are* validated. The rule for a reader: what `vocabulary()` exposes is not the
same set as what the façade rejects on, and ADR-0009 Decision 13 keeps the bump gate
aligned with the second set.

**`flint_bundle`.** The app cannot render without loading Flint at the exact bytes the
envelope's `flint_version` claims. #19 vendored the IIFE as package data under private
`_bundle/`, leaving the app to either reach into a private path or fetch from a CDN — and
a CDN fetch at the same version string is **not equivalent**, because ADR-0001 measured
that compiled output moves between builds at the same version number.
`chartagent.flint_bundle() -> FlintBundle` exposes `.path`, `.read_bytes()`, `.version`
and `.sha256`. The directory stays private; the accessor is the seam. This makes "the
client can load the pin the envelope promises" a library guarantee rather than an app-side
hope, secured by #19's existing IIFE-hash ↔ `vocab.json` ↔ façade-constants test. It does
not make chartagent a web server — serving the bytes is the app's job.

### 9. `Rasteriser` is a `Protocol`; `ReviewReport` is frozen here

ADR-0003 fixed the rasteriser's shape (envelope in, image bytes out, PNG at v1,
implementer owns compile-then-render) and left the signature to this ticket.

```python
class Rasteriser(Protocol):
    def rasterise(self, envelope: Envelope, *, format: Literal["png"] = "png") -> bytes: ...
```

A `typing.Protocol`, not an ABC — ADR-0003 says the library never hard-depends on a
rasteriser, and structural typing lets the app and CI implement it without importing a
base class of ours. Two errors: `RasteriserUnavailableError`, which names the missing
extra, and `RasterisationError` for a render that failed. ADR-0003's *unsupported* case
(Excel, forever) is **not** a rasteriser error — it is a skip the gate decides before
calling.

**No knobs on the protocol.** Timeout, viewport and scale belong on the implementation's
constructor; parameters on a protocol constrain every implementer to honour them.

`ReviewReport` is public and frozen here because the app consumes it, even though the
tier design that fills it is P2 work:

```python
tiers_run: tuple[int, ...]
tiers_skipped: Mapping[int, Literal["unavailable", "unsupported"]]
passed: bool              # scoped to tiers actually run
budget_exhausted: bool    # exhaustion's passed=False is NOT a skip
checks: tuple[CheckResult, ...]
```

`CheckResult` is **named here and defined by the review-gate tier ticket**. The attribute
is `review`, matching PRD §7.8.

### 10. Errors are ours, flat, and `pydantic.ValidationError` never crosses the seam

A flat `errors.py` (#19's layout), base `ChartAgentError`. P0:

| Error | Raised when |
| --- | --- |
| `SpecShapeError` | the frame is malformed, or carries inline `input.data` |
| `SpecVocabularyError` | a key the pin does not declare |
| `BackendCapabilityError` | the chart type is unsupported by the requested backend |
| `SchemaDriftError` | a referenced column was renamed or dropped |
| `DataSourceError` | the source cannot be read (PRD P0.9) |
| `TransformError` | the transform failed to execute |
| `RawSqlRejectedError` | *(under `TransformError`)* writes, multi-statement, or a non-file source |
| `RasteriserUnavailableError` | no rasteriser installed — names the extra |
| `RasterisationError` | the render itself failed |

**Erratum — 2026-08-26 ([#4](https://github.com/thearcscode/chartagent/issues/4),
ADR-0008).** Two rows above gain detail.

`RawSqlRejectedError` carries `reason: Literal["multi_statement", "not_read_only",
"unparseable", "empty", "non_file_source", "foreign_relation"]` — plain strings at runtime,
matching `SchemaDriftError.stage` and `DriftedField.kind` above rather than introducing a
`StrEnum`. `foreign_relation` is new: ADR-0008 Decision 7 requires every relation a
`raw_sql` names to be `source` or one of its own CTEs, with no table functions.
`non_file_source` is **unreachable at P0** — flavour 2 does not exist until P1 (Decision 4
above) — and stays in the union with a placeholder test, because ADR-0008 reads PRD §8's
"file-like sources only" by its stated reason, *no foreign dialect*, which admits flavour 3.

`SpecShapeError` gains three cases beyond the inline-`data` one: `raw_sql` present
alongside any menu slot, a duplicate or colliding transform output name, and an
unrecognised `transform` slot — never ignored, because a silently-dropped `filter` draws a
chart over unfiltered data.

**Erratum — 2026-08-26 ([#36](https://github.com/thearcscode/chartagent/issues/36), ADR-0009).**
Three rows above move again.

`SpecVocabularyError` gains **`kind`**, because it now covers seven rejection sites rather
than one: `Literal["chart_type", "channel", "property", "enum_option", "semantic_type",
"theme_preset", "encoding_key"]` — plain strings, matching `SchemaDriftError.stage` and
`RawSqlRejectedError.reason` above. It is `enum_option` and not `option`, because the
frame's top-level `options` bag is the one place ADR-0009 does **not** reject on and the
collision would read backwards. Each raise carries **every offender of its own kind** as a
tuple, following `DriftedField`; kinds are never mixed on one error, and ADR-0009 Decision
11 fixes the check order that decides which kind wins.

`BackendCapabilityError` is no longer only "the chart type is unsupported by the requested
backend" — it also fires for a **property key the pin declares for another backend**, and
**names the offending keys** when the failure is a knob rather than a chart type.

`SpecShapeError` gains a fourth case: **`theme_spec: null`**, which crashes Flint outright
(`Cannot read properties of null (reading 'extends')`) where an absent `theme_spec`
compiles. It is rejected, never coerced to absent.

`BackendCapabilityError` is deliberately distinct from `SpecVocabularyError`: 38 of 705
fixtures are unsupported by ECharts, 110 by Chart.js, 340 by Excel, and this is the error
#27's backend-switch affordance surfaces.

**Erratum — 2026-08-27 ([#9](https://github.com/thearcscode/chartagent/issues/9),
ADR-0012).** `BackendCapabilityError` gains **`kind`**, because it now has three raise sites
rather than two: `Literal["chart_type", "property", "facet"]` — plain strings, matching
`SchemaDriftError.stage`, `RawSqlRejectedError.reason` and `SpecVocabularyError.kind` above.
The third site is **Excel plus a `column`/`row` encoding** (ADR-0012 Decision 3), which
carries the offending channel names as a tuple. ADR-0009 Decision 11's check order gains it
as step 7, moving `chartProperties` to step 8.

Deferred to P1 because both need the agent:
`UnanswerableInstructionError` (P0.9's second half) and `HistoryReferenceError` (§7.8's
unresolvable VFS reference).

**Pydantic never crosses the seam.** A `ValidationError` may ride as `__cause__`, but the
public type is always ours, with stable field paths — #27's editor renders those paths
into a form and cannot track Pydantic's error shape across versions.

### 11. `Envelope.warnings` is five codes — and one thing we refuse to warn about

Frozen `Advisory` objects with a stable `code` and a `message`, in a tuple. Not
`warnings.warn`: the app has to *render* these, and a stderr warning cannot be rendered.

| Code | Meaning |
| --- | --- |
| `theme_spec_ignored` | `theme_spec` is set and the requested backend discards it silently |
| `dates_normalised` | N columns rewritten to ISO-8601 under ADR-0001 Decision 3 |
| `additive_drift_ignored` | new unreferenced columns were found and ignored |
| `raw_sql_used` | the escape hatch is in play |
| `empty_result` | the transform returned zero rows |

`theme_spec_ignored` earns its place: ECharts and Chart.js ignore `theme_spec` with no
error and no warning (ADR-0001, measured across three presets), and ECharts is the default
web target. This converts the project's most-cited silent failure into a visible one.
`dates_normalised` exists because we rewrote the caller's strings and they should know.

**Erratum — 2026-08-26 ([#4](https://github.com/thearcscode/chartagent/issues/4),
ADR-0008).** Five codes become **six**. `non_finite_nulled` carries the count of non-finite
floats converted to `null`: measured, `SELECT 1/0` returns `inf` in DuckDB — not `NULL`,
not an error — and `json.dumps` emits the bare token `Infinity`, which is invalid JSON that
a browser's `JSON.parse` rejects outright. Left alone it produces an envelope the client
cannot parse, with nothing in this error surface explaining it. It is not folded into
`dates_normalised`; none of the five fit.

**Erratum — 2026-08-27 ([#42](https://github.com/thearcscode/chartagent/issues/42),
ADR-0010).** Six codes become **seven**. `retype_unchecked` fires when a source-stage drift
check runs and **any** referenced column lacks a baseline entry in
`x_chartagent.source_schema`, with the columns and the reason in the message. Absence arises
four ways — the frame predates the key, the frame was hand-authored, a save had no bound
source, or the transform is `raw_sql` with `STAR` — and a *partial* baseline is the same
event at a smaller size, so it is **one code with the cause in the message**, not four codes.
That follows `additive_drift_ignored`, and branching a code on its cause would be a first
here. `STAR` fires it too: a permanent condition should not be a silent one, and
`raw_sql_used` already fires alongside it on every escape bind.

`dates_normalised` also widens. It is no longer only *"rewritten to ISO-8601"* but also
**converted to UTC** — ADR-0008 Decision 9 pins `TimeZone='UTC'` on our connection, because
`current_setting('TimeZone')` is read from the operating system. **N is columns, not
values**, and the message names them: `"3 columns normalised to ISO-8601 (UTC): ts,
created_at, closed_at"`. A `TIMESTAMPTZ` column counts unconditionally, even where its
values were already UTC — that is a data accident, and the caller needs to know the column
is UTC *by policy* to reason about the next refresh. `Advisory` stays `{code, message}`; the
column list lives in the message rather than widening the type. All three serialisation
rules apply to `raw_sql` output too — serialisation is a property of the envelope, not of
how the rows were produced.

**Not a warning: predictive layout row-drop.** ADR-0001's optimiser hazard — 59 of 705
fixtures returned a different row count — is decided by Flint at compile time, in the
client, from `baseSize` and the data. Guessing at it from Python would be a fabricated
warning about work we do not do. If the client wants it surfaced, the client reads
`_warnings` where they are actually produced.

### 12. `__all__` is the contract, and a narrowing pin bump breaks it

Public, and nothing else:

```
bind · Envelope · InputFrame · DataSource · Backend · Advisory
canonical_json · vocabulary · ChartVocabulary · PropertyDef · EncodingActionDef
flint_bundle · FlintBundle · Rasteriser · ReviewReport · CheckResult
the generated chartProperties models · everything in errors
```

`chartagent.errors` is a promised import path too, because catching by module path is
idiomatic. `DriftedField` needs no separate promise — it lives on `SchemaDriftError`.

Private, underscore or not: `_bundle/` contents (reachable only through
`flint_bundle()`), the façade generator (`extract.mjs`, `generate.py`, `check_bump.py` —
repo and CI, never the wheel), `vocab.json`'s on-disk layout (the accessor is the
contract, not the file), DuckDB connection handling, the transform compiler, ISO-8601
normalisation, and `x_chartagent` parsing internals.

**A Flint pin bump is not by itself a library breaking change. A narrowing is.** The five
failures `check_bump.py` already exits non-zero on — chart type removed, property removed,
property retyped, enum option removed, backend export missing — each mean a stored frame
that bound yesterday raises `SpecVocabularyError` today.

**Erratum — 2026-08-26 ([#36](https://github.com/thearcscode/chartagent/issues/36), ADR-0009).**
The breaking surface is **wider than these five**, because ADR-0009 closed four more
vocabularies. A removed **theme preset**, a removed **global channel**, a removed
**semantic type**, or a chart type removed from **one backend's** list each also turn a
frame that bound yesterday into one that raises today, and each is therefore a narrowing
and a major under pre-1.0 SemVer. `backend export missing` stays. Changes to a
per-chart-type `channels` list, to `min`/`max`/`step`, and to `dependencies` are **reported
and not fatal** — the façade does not reject on them, so they cannot break a stored frame.
The rule, in one line: the gate fails on exactly what the façade rejects on; anything the
façade merely exposes is a report. That is the rule tying #19's
SemVer policy to #24's bump gate, and it answers how the pin relates to our version number
without encoding the pin in it (PyPI refuses local versions anyway).

## Consequences

**What we gain.** A surface small enough to hold in one head — one verb, one return type,
three accessors, nine errors — that the app can build against today, in a phase with no
planner and no inference cost. The `$0.00` refresh pillar is demonstrable from this
surface alone. And the two-track parallelism is real: the app has every name it needs, so
it blocks on nothing.

**What we accept.** `bind` is a required-keyword API, which is slightly less friendly than
`render(spec, data)` and deliberately so. P0.11's retype clause is unmet until the
`source_schema` amendment lands. Flint's own `_warnings` are invisible to Python and to
any caller who does not run a client. And `flint_bundle()` makes the vendored IIFE part of
the public promise, so the wheel's 1.63 MB of package data is now load-bearing rather than
an implementation detail.

**What this obliges us to build.** The `InputFrame` hand-written envelope over the
generated models. Two schema-drift checks. The five `Advisory` codes, of which
`theme_spec_ignored` needs a per-backend table of which backends realise themes. Frozen
vocabulary dataclasses over `vocab.json`. And a test that `__all__` matches this ADR,
because a public list that drifts from its ADR is worse than no list.

**What this cancels.** `chartagent.render` as a name, in any form. `result.refresh()` as a
P0 obligation. Connection-like sources, async, and the two agent-era errors, all pushed to
P1 where PRD §9 already had them.

## Alternatives rejected

**Keep `render()` for PRD continuity.** Rejected. The name asserts the library does
something ADR-0001 amended away, and every caller who reads it learns the wrong model of
where compile happens. An alias is the same mistake with a deprecation notice attached.

**Store `backend` on the spec.** Rejected. It reads as convenient — the document knows
what it renders to — but it makes "one stored spec, five backends" a mutation rather than
an argument, and that claim is one of the product's better ones.

**Default `backend="echarts"`.** Rejected for P0. ECharts is the default *web* target and
will likely be the planner's default pick, but 38 of 705 fixtures are unsupported by it,
and a default turns an explicit capability question into a surprise `BackendCapabilityError`.

**Let the app read `_bundle/` directly, or fetch Flint from a CDN.** Rejected. The first
makes a private path load-bearing for the one consumer we control; the second cannot
guarantee the bytes, because output moves between builds at one version number.

**Expose the vocabulary as JSON schema from the generated models.** Rejected. It is free
and it under-serves: no labels, no step, no `dependencies`, no `data_dependent` flag — so
the form the app has to build cannot be built from it.

**Let `pydantic.ValidationError` through.** Rejected. It is the most informative error we
could hand a caller, and it binds every consumer to Pydantic's error shape — including a
spec editor that renders field paths into form fields.

**Warn predictively about row-drop.** Rejected. We would be modelling Flint's layout
optimiser in Python to warn about a decision made in the client. That is the translation
layer ADR-0002 exists to avoid, in miniature, and it would be wrong often enough to be
worse than silence.

**Require a sandbox in `bind`.** Rejected at P0 only. There is no model-authored SQL in
Phase 0, and requiring it would make the sandbox a dependency of the spec editor.

## Related

- ADR-0001 — the envelope, the pin, client-side compile, the `baseSize` hazard, the
  `theme_spec` gap on ECharts and Chart.js.
- ADR-0002 — the frame is the spec; Decision 3 (no stored `data`), Decision 4 (encodings
  reference transform output), Decision 5 (canonical JSON), Decision 6 (pinned `baseSize`).
- ADR-0003 — rasterise in a browser; the `Rasteriser` shape whose signature is Decision 9.
- ADR-0004 — the bump gate whose narrowing verdict Decision 12 promotes to a breaking change.
- ADR-0008 — the transform this seam runs; amends Decisions 1, 7, 10 and 11 here.
- ADR-0009 — what the façade validates, settling
  [#36](https://github.com/thearcscode/chartagent/issues/36); amends Decisions 3, 8, 10 and
  12 here. No signature moved.
- The `source_schema` amendment to ADR-0002 — Decision 7's missing baseline.
- [#26](https://github.com/thearcscode/chartagent/issues/26),
  [#27](https://github.com/thearcscode/chartagent/issues/27),
  [#28](https://github.com/thearcscode/chartagent/issues/28) — the app tickets this surface
  was dogfooded against.
- `prototypes/facade-codegen/` — the 151 generated models, the two-array vocabulary, and
  `check_bump.py`.
