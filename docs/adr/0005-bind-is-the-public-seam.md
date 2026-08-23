# 5. `bind` is the public seam

- **Status:** Accepted
- **Date:** 2026-08-23
- **Settled on:** [#25](https://github.com/thearcscode/chartagent/issues/25)
- **Builds on:** ADR-0001 (pin Flint; compile in the client), ADR-0002 (the input frame
  *is* the spec), ADR-0003 (rasterise in a browser — this ADR supplies the `Rasteriser`
  signature it deferred), ADR-0004 (fixture jobs)
- **Amends:** PRD §7.8's public API sketch and P0.11's `chartagent.render(spec, data)` /
  `result.refresh()`. The requirement is unchanged; the names are not.
- **Leaves open:** how strictly the generated façade validates, and how `chartType` is
  typed per backend — [#36](https://github.com/thearcscode/chartagent/issues/36). That is
  behaviour behind these names, and no signature here moves whichever way it lands.

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

**Retype detection has no baseline, so it does not ship at P0.** Renames and drops need
nothing stored — the referenced names are in the document. A *retype* needs the type the
spec was planned against, and nothing in the frame records source dtypes (`semantic_types`
maps *output* columns to Flint semantic types, which is a different thing). The fix is a
`source_schema` map of referenced source columns, which is a sixth key in `x_chartagent`
and therefore an **ADR-0002 amendment** — graduated as its own ticket rather than smuggled
in here. Until it lands, P0.11's retype clause is unmet and the transform fails loudly
instead.

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

`BackendCapabilityError` is deliberately distinct from `SpecVocabularyError`: 38 of 705
fixtures are unsupported by ECharts, 110 by Chart.js, 340 by Excel, and this is the error
#27's backend-switch affordance surfaces. Deferred to P1 because both need the agent:
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
that bound yesterday raises `SpecVocabularyError` today. That is the rule tying #19's
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
- [#36](https://github.com/thearcscode/chartagent/issues/36) — façade strictness and
  per-backend `chartType`. Behaviour behind these names; no signature here depends on it.
- The `source_schema` amendment to ADR-0002 — Decision 7's missing baseline.
- [#26](https://github.com/thearcscode/chartagent/issues/26),
  [#27](https://github.com/thearcscode/chartagent/issues/27),
  [#28](https://github.com/thearcscode/chartagent/issues/28) — the app tickets this surface
  was dogfooded against.
- `prototypes/facade-codegen/` — the 151 generated models, the two-array vocabulary, and
  `check_bump.py`.
