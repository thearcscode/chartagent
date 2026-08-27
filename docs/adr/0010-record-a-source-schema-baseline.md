# 10. Record a `source_schema` baseline so retype drift is detectable

- **Status:** Accepted
- **Date:** 2026-08-27
- **Settled on:** [#42](https://github.com/thearcscode/chartagent/issues/42)
- **Builds on:** ADR-0002 (the input frame *is* the spec; our grammar lives only in
  `x_chartagent`), ADR-0005 (`bind` is the public seam; the error taxonomy; schema drift is
  two checks), ADR-0007 (what Studio stores; revisions are immutable and content-addressed),
  ADR-0008 (the transform menu; the identifier allowlist reads the source schema)
- **Amends:** ADR-0002 Decision 1, ADR-0005 Decisions 5, 7 and 11, ADR-0007 Decision 8, and
  ADR-0008 Decision 4 — all recorded as dated errata in place, and listed under
  *What this amends*

## Context

ADR-0005 Decision 7 found that **PRD P0.11's retype clause is not deliverable against the
frame as ADR-0002 defines it.** Renames and drops need nothing stored: the referenced column
names are already in the document, in `x_chartagent.transform` and
`chart_spec.encodings[*].field`. A **retype** needs the type the spec was planned against,
and nothing in the frame records source dtypes.

`semantic_types` is not that baseline and cannot be made into one. It maps *transform
output* columns to Flint semantic types (`"revenue_sum": "Revenue"`) — a statement about
meaning, for the compiler, about columns the source does not have. The source column's
storage type is a different fact about a different column.

So `SchemaDriftError`'s `kind: "retyped"` has had no baseline to compare against. ADR-0005
shipped rename and drop detection at P0 and deferred retype to here rather than smuggling a
sixth key into `x_chartagent`.

### The failure this exists to catch

A retype is the one drift that draws a chart instead of raising. A renamed or dropped column
fails at the identifier allowlist (ADR-0008 Decision 4) — loudly, with a field path. A
retyped column resolves, binds, compiles, and renders a chart that is quietly wrong.

Measured (`prototypes/source-schema-buckets/day_boundary.py`, DuckDB 1.5.5): under
ADR-0008's pinned `TimeZone='UTC'`, a source column that changes from `TIMESTAMP` to
`TIMESTAMP WITH TIME ZONE` moves **50 of 240** hourly rows across a `date_trunc('day')`
boundary — but only **two bars change height**, because a fixed offset shifts every row
uniformly and the interior days keep their 24. The damage lands at the edges: the first bar
drops 24 → 19, and an **eleventh bar appears where there were ten**. Across a real DST
transition (`America/New_York`, 2026-03-08) it is 44 of 240 and an interior bar moves too,
24 → 25.

That is the shape of the whole problem. A retype adds a category to a categorical axis and
truncates another, while every bar in the middle stays identical — so the chart looks
correct to anyone who checks it the way people actually check charts.

### What is being amended, and what is not

ADR-0002 Decision 1 fixes `x_chartagent` at five keys. Adding a sixth is an amendment to the
decision that defines our grammar's shape, so it earns its own ADR rather than a footnote.

What is *not* reopened: `SchemaDriftError` and `DriftedField` are already public and named in
ADR-0005 Decision 7, and this ADR changes what can *fill* `kind`, never the error's shape.
The two-check structure (`stage: "source" | "transform_output"`) is settled and stays.

## Decision

**Record the planning baseline as `x_chartagent.source_schema`: a map of referenced source
columns to coarse type buckets, computed by the library, persisted by the caller at save,
and compared where the chart would change rather than where the storage differs.**

```json
"x_chartagent": {
  "spec_version": "1.1",
  "transform": { "…": "…" },
  "annotations": [],
  "interactions": {},
  "escape": null,
  "source_schema": { "quarter": "date", "revenue": "number", "region": "string" }
}
```

### 1. A sixth key in `x_chartagent`, not a `bind` argument and not a sidecar

The baseline must not be able to drift out from under the frame it describes. ADR-0007
content-addresses a revision on `sha256(canonical_json)` and makes it immutable, so a
baseline **inside** the frame has that property by construction — and every caller gets it,
not only Studio.

Three alternatives were weighed and rejected.

**A caller-supplied previous schema passed to `bind`** widens ADR-0005 Decision 1's frozen
P0 surface — one verb, three parameters — and a baseline the caller has to remember to pass
is absent exactly when it matters.

**A sidecar column Studio stores** collapses into that same option. `SchemaDriftError` is a
*library* error in a library-owned taxonomy (ADR-0005 Decision 10). A column the library
never sees means either Studio writes a second comparison — the silent-drift hazard ADR-0005
Decision 8 refused for `canonical_json`, one level down — or Studio passes the value back
in, which is the `bind` argument wearing a database column.
[#28](https://github.com/thearcscode/chartagent/issues/28)'s offer was real; it buys storage,
not a checker.

**A field under `x_chartagent.transform`** would dodge this amendment entirely, since
Decision 1 fixes the five top-level names and not their internals. It is rejected on
ownership: the baseline describes the *source*, which the transform reads and does not own.
ADR-0008 spent its authority closing `transform` at eight slots, and a ninth non-slot field
reopens the menu it just shut. It also fights `raw_sql`'s exclusive-or with the menu — both
modes need the same baseline, which a sibling of `transform` gives and a field inside it does
not.

**This amends the grammar, not existing bytes.** No stored frame is rewritten; old frames
simply lack the key (Decision 7).

### 2. Referenced source columns only

"Referenced" means the columns the transform names **on the source** — every `col(name)` in
the menu, or the column set the `raw_sql` parse tree reports. It is not encoding fields
(those are transform *output*, ADR-0002 Decision 4) and not `derive`/`bin` output names.

PRD P0.11 already ignores additive drift. A whole-source-schema baseline would therefore
store precisely the columns we have committed never to look at, and it would start to
resemble `data_sources.schema_snapshot` — which ADR-0007 Decision 15 deliberately split from
the planning baseline. They are different objects: a source's schema changes when the source
changes; a spec's baseline is what the spec was planned against, and must not move when the
data does.

**On `STAR`.** ADR-0005 Decision 7's erratum has `json_serialize_sql` reporting `STAR` when a
`raw_sql` query's column set is indefinite. There, **omit the key** — do not write `{}`.
Under `STAR` "referenced" and "whole schema" converge, so snapshotting the source would be
the whole-schema answer arrived at by accident.

**On an empty referenced set.** A transform that names no source column at all (`{"limit":
100}` alone) writes `{}`. The two states are different statements and the distinction is
load-bearing for Decision 7: **`{}` means we looked and there was nothing to record; an
absent key means we do not know what was there.**

### 3. Seven coarse buckets, and the rule that draws the lines

`number` · `string` · `boolean` · `date` · `timestamp` · `timestamptz` · `other`

**The line is drawn where the chart changes, not where the storage differs.**

That rule is the whole vocabulary. `INTEGER` → `BIGINT` → `DOUBLE` share `number` because a
sum is a sum and a bar is a bar. `VARCHAR` → `DATE` splits because a categorical axis becomes
a temporal one. And `TIMESTAMP` → `TIMESTAMP WITH TIME ZONE` splits — despite both being
"a timestamp" in every other vocabulary — because the measurement above shows it silently
adding and truncating categories on a daily chart.

Two alternatives were rejected on evidence.

**DuckDB logical types** are a dependency's vocabulary, and too fine to compare. Measured
(`prototypes/source-schema-buckets/reported_types.py`): `numeric` and `dec` both report
`DECIMAL(18,3)` while `decimal(10,2)` reports `DECIMAL(10,2)`, so a logical-type baseline
raises a false drift the first time anyone widens a column. Worse, the vocabulary belongs to
something we bump: a DuckDB upgrade that refines or renames a logical type retypes every
stored baseline at once, with no Flint involvement and nothing in the frame to blame. That is
the same artifact ADR-0004 refused when it rejected an allowlist of forgiven diffs for the
bump gate — a per-widening exceptions list is what a logical-type baseline would need to
become usable.

**Arrow types** are worse still. PRD §7.4 adopts Arrow as *internal* interchange; putting
Arrow types in the stored document exports an internal implementation choice into public
grammar.

This vocabulary also discharges a debt. ADR-0008 Decision 4 deferred exactly one type
question — *"When schemas are written, DATE/TIMESTAMP versus string-literal compatibility is
defined explicitly, so the editor and DuckDB cannot disagree"* — and these are the schemas.
One bucket set serves both the drift comparison and the literal-vs-column rule, rather than
two type systems that must be kept in step.

### 4. The mapping is head-based on the reported type

> **Erratum — 2026-08-27 (#5, ADR-0011).** This table is **one engine's mapping, not the
> vocabulary.** The seven buckets are drawn where the *chart* changes, so they are
> engine-neutral; PRD §7.4's flavour-2 sources report their own type names
> (`NUMBER(38,0)`, `TIMESTAMP_NTZ`, `VARIANT`) and get their own head tables when they
> land. Read the table below as the DuckDB mapping.

DuckDB *accepts* 82 type names in 1.5.5 but *reports* far fewer: 21 aliases spelled every
legal way collapse to 9 reported strings (`int4`/`int32`/`integer`/`int` → `INTEGER`;
`string`/`text`/`varchar`/`nvarchar` → `VARCHAR`; `datetime` → `TIMESTAMP`). The table keys on
what `DESCRIBE` reports, so it needs no alias column.

But reported types carry parameters, so the mapping matches the **constructor head before its
parameters** — never the whole string. `DECIMAL(10,2)` and `DECIMAL(18,3)` are one bucket;
so are `STRUCT(…)`, `MAP(…)`, `UNION(…)` and the timestamp precisions.

> **Erratum — 2026-08-27 ([#5](https://github.com/thearcscode/chartagent/issues/5),
> ADR-0011).** This decision named `LIST(…)` and `ARRAY[n]` as reported heads. **DuckDB
> emits neither.** Measured (`prototypes/data-profile/reported_composites.py`, 1.5.5), lists
> and arrays are reported **postfix** — `INTEGER[]`, `BIGINT[]`, `INTEGER[3]`,
> `VARCHAR[][]` — so a prefix-head rule buckets `BIGINT[]` as **`number`** and
> `VARCHAR[][]` as **`string`**. `STRUCT(…)`, `MAP(…)` and `UNION(…)` are prefix-formed and
> were always right; `STRUCT(…)[]` is right for the wrong reason.
>
> The consequence lands inside this ADR's own failure mode: a `BIGINT[]` column records
> `number`, so unnesting it to plain `BIGINT` reads `number` → `number` and raises **no**
> `SchemaDriftError`, while ADR-0008 Decision 4's allowlist stays quiet because the name did
> not change.
>
> **The rule is amended: any reported type ending in `]` is `other`, tested before any
> prefix head.** `LIST` and `ARRAY` are struck from the table below. No implementation was
> affected — this ADR landed the same day, against a repo with no `pyproject.toml`.

| bucket | reported type heads |
| --- | --- |
| `number` | `TINYINT`, `SMALLINT`, `INTEGER`, `BIGINT`, `HUGEINT`, all `U*` unsigned forms, `FLOAT`, `DOUBLE`, `DECIMAL`, `VARINT`, `BIGNUM` |
| `string` | `VARCHAR`, `ENUM`, `UUID` |
| `boolean` | `BOOLEAN` |
| `date` | `DATE` |
| `timestamp` | `TIMESTAMP`, `TIMESTAMP_S`, `TIMESTAMP_MS`, `TIMESTAMP_NS` |
| `timestamptz` | `TIMESTAMP WITH TIME ZONE` |
| `other` | any reported type ending in `]` (lists and arrays), `TIME`, `TIME WITH TIME ZONE`, `INTERVAL`, `BLOB`, `BIT`, `STRUCT`, `MAP`, `UNION`, `JSON`, `GEOMETRY`, `VARIANT`, `NULL` |

Three placements are judgement calls and are recorded as such.

**`UUID` and `ENUM` are `string`** because both chart as their text does; a DuckDB `ENUM` is
a dictionary-encoded string, and `ENUM` → `VARCHAR` moves no bar.

**`DECIMAL` is `number`** for the reason the probe shows: parameter changes must not raise.

**`other` → `other` is not drift, even `STRUCT` → `BLOB`,** because neither was chartable in
the first place. A `derive` that reached into the struct fails as `TransformError` at execute
with our node path attached (ADR-0008 Decision 4), which is the right error for that mistake —
raising `SchemaDriftError` instead would blame the data for a spec problem.

### 5. The library computes it; the caller persists it. `bind` only ever reads

Studio must not invent its own bucketing. Two bucketings of the same source are the
`canonical_json` hazard again — both produce plausible JSON and they drift silently.

So the bucket map rides out on the envelope as a **diagnostic**, beside `.row_count`,
`.elapsed` and `.warnings`: **`Envelope.source_schema`**, which never serialises into
`input`. `bind` already reads exactly this schema for ADR-0008 Decision 4's identifier
allowlist and currently discards it, so the value costs nothing new.

It is deliberately **not** a new public function. A `source_schema(spec, data)` accessor
would do **I/O against a DataSource**, making it the second verb that reads a source and
widening ADR-0005 Decision 1's one-verb P0 surface. `canonical_json` and `vocabulary` are
pure; this is not, and it does not belong beside them. A direct caller who wants a baseline
calls `bind` once — which they were going to do anyway — and copies the field.

**`__all__` is unchanged.** No new public name, no new error type, no new verb: `Envelope`
was already public and this is an attribute on it. This ADR adds a grammar key without
widening the seam at all.

**The field is named for what it is: what *this bind* saw.** It is not the stored baseline
and must never be documented as one. The stored baseline is whatever a save wrote into the
frame, which may be older, and telling them apart is the entire point of the comparison.

**Writing it is the save path's job**, alongside `content_hash` and
`authored_flint_version`. `authored_flint_version` is the exact precedent and it is already
in ADR-0007's schema: a fact captured at save time from ambient request context, recorded and
never a gate.

A bind-written back-fill was rejected because there is nowhere to put it. `bind` is a pure
function returning an envelope (ADR-0005), so a written key could only ride out on
`envelope.input`, making the returned frame differ from the stored one — and Studio cannot
persist that: ADR-0007 Decision 5 is *"a revision is created by an explicit save and by
nothing else"*, and [#27](https://github.com/thearcscode/chartagent/issues/27)'s lock
specifies refresh as *"one `bind` against a new source. Empty document diff, the spec version
does not bump."* A bind-written baseline is either silently discarded or it writes a revision
on every refresh.

**The source as of the save *is* the planning baseline**, by definition rather than by
approximation. The ticket's worry — that an editor-written baseline is *"only as good as the
editor's last look at the data"* — dissolves under the save-path framing: what the spec was
planned against is what was there when it was saved.

The real failure mode is different and is handled by Decision 7: **a save with no bound
source** has no schema to record and writes no key, rather than fabricating one.

### 6. Values are a closed `Literal`; `SpecShapeError` on anything else

The seven buckets are a closed `Literal`. An unrecognised value is `SpecShapeError` — the
same family as ADR-0008 Decision 13's unrecognised `transform` slot, and deliberately **not**
`SpecVocabularyError`, which means *"the pin does not declare this"* and has no bearing here.
Column names stay plain `str`, matching Decision 2's scope.

ADR-0009's governing tension does not apply. Its permissive cases exist where an upstream
vocabulary can widen underneath us — `options` is `extra='allow'` because no runtime array
declares it, and a hand-written union would be a parallel vocabulary maintained by grep. Here
we **are** the declaring authority: this is `x_chartagent`, not Flint's half of the frame.
There is no pin bump that can invalidate the list, so a vocabulary we author and cannot
mistype is free to close.

**What this does not settle: unknown *keys* inside `x_chartagent` generally.** That question
is live and is deliberately left open — answering `extra='forbid'` on the whole block here
would decide the grammar's extensibility policy as a side effect of a retype amendment. It
graduates to the map's *Not yet specified*, alongside the `escape`-placement entry it
resembles. **This ADR closes `source_schema` values only.**

### 7. Absent and partial are one event: the `retype_unchecked` advisory

An absent baseline must never be a hard error. Every frame stored before this lands, every
hand-authored frame, and every upstream fixture has none.

Absence arises four ways — the frame predates the key; the frame was hand-authored; a save
had no bound source; the transform is `raw_sql` with `STAR`. A **partial** baseline (present,
but missing a referenced column) is unreachable from Studio's save path and trivially
reachable in a hand-authored frame.

**One new `Advisory` code, `retype_unchecked`**, fired when a source-stage check runs and
**any** referenced column lacks a baseline entry. The message names the columns and the
reason. Absent and partial are the same event at different sizes, which is what they are;
columns that *do* have an entry are still checked, so a hand-authored frame naming three of
five columns is better off than one naming none — not worse.

The code does not branch on cause. ADR-0005 Decision 11's advisories are flat `{code,
message}` by design, and `additive_drift_ignored` is the precedent: one code for a fact that
arises many ways, with the detail in the message. Four codes for four origins would be the
first time we branched a code on its cause.

`STAR` fires it too, with the reason in the message. A permanent condition should not be a
silent one, and `raw_sql_used` already fires on every escape bind, so the pair reads
correctly together.

A present `{}` whose transform *does* name source columns is partial with every entry
missing, and fires it.

### 8. `kind: "retyped"` is a `stage: "source"` kind only

There is no transform-output baseline, and there should not be one.

Within a revision the transform is immutable, so if every source bucket holds, every output
bucket holds: an output column's type is a function of the transform and its inputs, and the
transform cannot move without a new revision. Output retype is therefore *implied* by source
retype rather than separately checkable.

`semantic_types` is not the missing half — it is Flint meaning, not storage type (see
*Context*).

This is recorded so that a later reader does not try to supply the "missing" output baseline.
The `transform_output` stage keeps its `renamed` and `dropped` kinds unchanged.

### 9. `expected` and `found` hold buckets; the logical type rides in the message

`DriftedField.expected` and `.found` are both buckets: `expected="string", found="date"`.

They are already polymorphic by `kind` — they hold column *names* for `renamed` — so *one
vocabulary per kind, both sides* is the consistent rule rather than a new one. Putting
`DATE` in `found` while `expected` could only ever hold a bucket would mix two vocabularies
in one frozen object, and would imply we compare logical types, which Decision 3 rejects.

The message stays free to carry the detail a reader actually wants when debugging:
*"bucket `string` → `date` (DuckDB `VARCHAR` → `DATE`)"*. That costs nothing and widens no
frozen type.

### 10. `spec_version` becomes 1.1, and the bump is a weaker promise than ADR-0008's

ADR-0008 Decision 13 sets the precedent: *"Adding `window` in P1 is a `spec_version` MINOR
bump."* A sixth key is the same kind of move, so new frames default to **1.1**.

**But the two bumps do not carry equal force, and conflating them would be a mistake.**
ADR-0008's MINOR bump is backed by a **closed** slot vocabulary, so an old reader meeting
`window` fails loudly at `SpecShapeError`. Decision 6 deliberately left `x_chartagent`'s key
set open, so an old reader meeting `source_schema` does something currently undefined. The
version number here signals that the grammar moved **without guaranteeing anyone notices**.
That gap is the fog entry Decision 6 graduated, not a hole to patch inside this ADR.

Existing `1.0` frames stay valid: absent key, `retype_unchecked`, no rewrite. **Opening an
old chart does not rewrite `spec_version`** — only a save does. A save that copies
`source_schema` onto a `1.0` frame writes `1.1` in the same act, because the frame now uses
the sixth key.

## What this amends

Recorded as dated errata in place, so a reader of each original decision is not required to
find this ADR to learn what changed.

- **ADR-0002 Decision 1** — `x_chartagent` holds **six** keys, not five. The sixth is
  `source_schema`, specified here.
- **ADR-0005 Decision 5** — the envelope's diagnostics gain `.source_schema` beside
  `.row_count`, `.elapsed` and `.warnings`. The wire format is unchanged at three keys.
- **ADR-0005 Decision 7** — retype detection **ships**; its deferral is closed. `kind:
  "retyped"` is a `stage: "source"` kind only.
- **ADR-0005 Decision 11** — the advisory table goes from six codes to **seven** with
  `retype_unchecked`.
- **ADR-0007 Decision 8** — the save-writes-the-cache test gains one exception: when the
  only difference between the frame being saved and the frame the cache was built from is
  `source_schema` copied from that same bind's envelope, **write the cache anyway.** The key
  changes `canonical_json`, so the byte-identical test would otherwise fail on the first
  honest save of every pre-existing chart — while the cached rows remain perfectly valid,
  since neither Flint nor the transform reads the key.
- **ADR-0008 Decision 4** — its deferred type vocabulary is supplied by Decision 3 here.
  DATE/TIMESTAMP versus string-literal compatibility is decided on buckets.

## Consequences

**What we gain.** P0.11's retype clause becomes deliverable, closing the last unmet line in
the requirement. The one drift that draws a wrong chart instead of raising now raises. And
the frame carries its own baseline, so the guarantee holds for every caller rather than only
for callers who happen to have a database.

**What we accept.** `x_chartagent` grows a key, and a document that predates it can never
retroactively acquire one — the source it was planned against is gone. Those frames get
`retype_unchecked` forever, or a baseline as of their next save, which is honest rather than
accurate. The coarse buckets also mean some genuine retypes go unreported: `VARCHAR` →
`ENUM`, `STRUCT` → `BLOB`, `DECIMAL(10,2)` → `DECIMAL(18,3)`. That is the deliberate trade —
Decision 3's rule buys silence on widenings by accepting silence on same-bucket changes, and
the alternative was an exceptions list.

**What this obliges us to build.** A bucket mapper over DuckDB's reported types, head-based.
The `Envelope.source_schema` diagnostic. The comparison itself, at the source stage only.
`retype_unchecked`. And in Studio: the save path copying the field, plus ADR-0007 Decision
8's cache exception.

**One obligation lands outside the library.** `prototypes/flint-frame/probe.mjs`'s `PROBE`
literal is a **hand-maintained mirror of ADR-0002 Decision 1's key list, with nothing binding
them.** The delete-`x_chartagent` invariant (ADR-0004 Decision 1) synthesises its block from
that literal, so it exercises whatever keys someone last typed there. `source_schema` survives
the invariant *by construction* — Flint never reads inside `x_chartagent` — but it is not
**exercised** by it unless `PROBE` names it. Updated in the same commit as this ADR. The job's
pass/fail rule is unchanged; this is a coverage fact, not a new gate.

## What this feeds

**[#28](https://github.com/thearcscode/chartagent/issues/28) is answered without being
changed.** Its bounded offer — a column on `spec_revisions` if this ticket chose the sidecar
route — is declined, and `data_sources.schema_snapshot` keeps its own meaning. ADR-0007
Decision 15's split between the source's snapshot and the spec's baseline stands exactly as
written; this ADR puts the baseline in the frame, which `spec_revisions` stores anyway.

**The planner (P1) inherits a filled-in slot rather than a question.** When a planner exists
it writes `source_schema` from the same envelope field at plan time, and the save path stops
being the only writer. Nothing in this decision has to change for that to happen.

## Alternatives rejected

**A caller-supplied previous schema passed to `bind`** — Decision 1. Widens the frozen seam,
and is absent exactly when it matters.

**A sidecar column on `spec_revisions`** — Decision 1. Collapses into the above, or into a
second checker.

**A field under `x_chartagent.transform`** — Decision 1. Dodges the amendment at the cost of
reopening ADR-0008's closed slot list, and describes the source from inside the thing that
merely reads it.

**Narrowing P0.11 to rename/drop permanently** — held open through the session as the honest
fallback if no writer could be named, and unnecessary once the save path could. Withdrawing a
requirement because the first-choice writer was unavailable would have been the wrong reason.

**A public `source_schema(spec, data)` function** — Decision 5. A second verb that reads a
source.

**DuckDB logical types, or Arrow types, as the vocabulary** — Decision 3. A dependency's
vocabulary, and an internal interchange choice, respectively.

**Four advisory codes for the four causes of absence** — Decision 7. Branches a code on its
cause for the first time.

## Evidence

Probes in `prototypes/source-schema-buckets/`, DuckDB 1.5.5.

**`day_boundary.py`** — why `timestamp` and `timestamptz` are separate buckets. Under
`TimeZone='UTC'`, 240 hourly instants bucketed by `date_trunc('day')`:

| | rows moved | bars changed |
| --- | --- | --- |
| fixed `-05:00` offset | 50 / 240 | 2 (first bar 24 → 19; an 11th bar appears) |
| `America/New_York`, across 2026-03-08 DST | 44 / 240 | 3 (an interior bar moves, 24 → 25) |

**`reported_types.py`** — why the mapping is head-based on reported types. DuckDB accepts 82
type names; 21 aliases collapse to 9 reported strings. `numeric` and `dec` report
`DECIMAL(18,3)` while `decimal(10,2)` reports `DECIMAL(10,2)` — same bucket, different
string, which is what makes exact-string matching wrong and a logical-type baseline
false-positive on any widening.

## Related

- [#42](https://github.com/thearcscode/chartagent/issues/42) — the ticket this settles.
- [#25](https://github.com/thearcscode/chartagent/issues/25) / ADR-0005 Decision 7 — where
  the deferral was made.
- [#28](https://github.com/thearcscode/chartagent/issues/28) / ADR-0007 Decision 15 — the
  offer declined, and the snapshot-versus-baseline split it drew.
- [#4](https://github.com/thearcscode/chartagent/issues/4) / ADR-0008 Decision 4 — the
  identifier allowlist that already reads this schema, and the type vocabulary it deferred.
- [#36](https://github.com/thearcscode/chartagent/issues/36) / ADR-0009 — the façade's
  strictness rules for Flint's half of the frame; this is the first stated rule for content
  inside `x_chartagent`.
- Open, on the map: what the façade does with an unknown *key* inside `x_chartagent`.
