# 18. A custom-rail result is a recipe, not a Flint frame

- **Status:** Accepted
- **Date:** 2026-08-28
- **Errata:** 2026-09-26 ([#189](https://github.com/thearcscode/chartagent/issues/189)) —
  Decision 2's `theme_spec` type, recorded in place.
- **Settled on:** [#60](https://github.com/thearcscode/chartagent/issues/60)
- **Builds on:** ADR-0002 (the input frame is the spec; `x_chartagent`; canonical JSON is the
  diff unit), ADR-0005 (`bind` is the public seam; `canonical_json`; diagnostics ride on the
  object), ADR-0007 (the five tables; the frame as one opaque column; the Library reads a
  cache), ADR-0008 (the transform menu), ADR-0010 (`source_schema` as a sixth key),
  ADR-0013 (the escape-reason vocabulary), ADR-0016 (the fourth bucket; code must be stored),
  ADR-0017 (the interactive web document; `ChartDocument` / `BoundDocument`; `build_shell`)
- **Amends:** ADR-0002 Decision 1's key set and its open *Related* question (**closed**);
  ADR-0005 Decision 8 (`canonical_json` widens to a union); ADR-0007 Decisions 2, 4, 6 and 14
  and the schema in Decision 14; ADR-0016 Decision 15 (its `assemble*` clause is **withdrawn**);
  ADR-0017 Decision 18 (`__all__` grows by three more). Errata on PRD §7.3, §7.7, §8 and
  §9 P0.5, and on `CONTEXT.md`.
- **Leaves open:** *Unknown keys inside `x_chartagent`*, which this ADR hands its first live
  case and deliberately does not decide (Decision 4).

## Context

The map has carried *where `escape` goes* since `prototypes/chartspec-v1/`, where the README
asked it in one line: *"Does `escape` belong on ChartSpec at all, or is it a sibling result
type? Current draft makes an escape spec carry encodings that nothing reads, which the
`E_ESCAPE_CONFLICT` rule half-admits."* ADR-0002 recorded it as still open. ADR-0013
Decision 11 fixed the reason's *vocabulary* and left placement fog. ADR-0016 Decision 8 found
that the entry carries **two payloads, not one** — the reason and the generated code — and that
it now **blocks P0.5**, because *"re-invoking with new data requires no LLM call"* is
unsatisfiable if the code was never stored, and ADR-0007's five tables have no column for it.

ADR-0017 replaced the code payload with a `ChartDocument` and left placement explicitly not
minted. This ADR places both.

Four things were found by reading rather than argued, and each decided something.

### The frame is not merely unnecessary — it is unconstructible

ADR-0002's probe over 705 fixtures: `chart_spec` 705, `chartType` 705, `encodings` 705,
`baseSize` 705. ADR-0009 Decision 1 types `chartType` as a **generated `Literal` of the pin's
union**, with no null member and no escape value.

So an escape frame cannot merely carry a dead `chart_spec` — it must **name a chart type Flint
never draws**, in a required, closed-vocabulary field, in the one place ADR-0009 Decision 3
shipped `extra='forbid'` with no warn-and-strip. The cost is not a wasted key. It is a lie one
level up from ours, in the half of the frame we do not own.

Two further consequences follow the same way. **ADR-0002 Decision 2's fixture invariant stops
protecting anything**: delete `x_chartagent` from an escape frame and Flint compiles the result
perfectly, as some unrelated chart, so the invariant passes *vacuously* — which is worse than
failing. And **`bind` would refuse its own carrier**: ADR-0005 Decision 3 and ADR-0009
Decision 2 have it validate chart-type membership in the requested backend, so either the frame
path rejects the artifact it exists to carry, or a backend-shaped exception is cut into a hard
error two ADRs deliberately left with none.

### `ChartDocument` is not the whole stored artifact

ADR-0017 Decision 8 defines it as `module` + `styles` + pins + `contract_version` — the **code**.
A refreshable custom-rail chart also needs the `transform` (or refresh has no rows) and
`source_schema` (or `SchemaDriftError` cannot fire on this rail). Three of `x_chartagent`'s six
keys carry over; `annotations` and `interactions` do not, because the agent draws them inside
the module.

So the sibling is a **wrapper around** `ChartDocument`, not `ChartDocument` promoted.

### ADR-0017 never said where the rows come from

ADR-0017 contains no mention of `transform`, `source_schema`, drift, `spec_revisions` or the
bind cache. `BoundDocument.rows` has no producer anywhere in the ADR that introduced it. The
gap is wider than *"`bind` requires a backend"*: nothing at all binds a document today.

### ADR-0016 Decision 15's "Studio's P2 hole" was closed by ADR-0017, and nobody said so

Its words are that a custom-rail card *"cannot `assemble*` those rows."* Under ADR-0017 nothing
on this rail calls `assemble*` at all — the paint path is `build_shell` plus a sandboxed iframe
plus `postMessage`, and `bind_caches` already holds `{revision_id, rows}`, which is exactly what
the channel wants. The hole closed as a side effect of a correction aimed at something else, and
both ADR-0016 and the map still record it as open.

## Decision

**A custom-rail result is a `ChartRecipe` — a sibling to the input frame, not a frame with a
flag — stored in the same column behind a discriminator, bound by a second verb, and refreshed
without ever reading the code.**

### 1. `ChartRecipe` is a sibling result type

Not a field on `x_chartagent`. The frame is unconstructible without corrupting `chartType`, and
the two costs of trying — a vacuous fixture invariant, and `bind` refusing its own carrier —
are both paid in the half of the frame Flint owns and we do not.

The name is the house's own prose: ADR-0007 Decision 11 already says *"when the served pin
cannot render a stored recipe."* It collides with nothing — not `frame` (Flint's word for its
assembler argument), not `spec` (`CONTEXT.md` avoids ChartSpec-as-the-stored-document), not
`document` (ADR-0017 spent it on the code).

### 2. Six fields, and four the PRD named that are gone

```python
@dataclass(frozen=True)
class ChartRecipe:
    spec_version:  str                 # one grammar line with the frame — Decision 4
    transform:     Transform           # ADR-0008's eight slots, or raw_sql
    source_schema: Mapping[str, Bucket] # ADR-0010's referenced-column map
    escape_reason: EscapeReason        # ADR-0013 D11 / ADR-0016 D3 — Decision 11
    theme_spec:    ThemeSpec | None    # Decision 3
    document:      ChartDocument       # ADR-0017 D8, unchanged
```

PRD §8 describes the escape as `mode: custom_code` + `reason` + chosen `library` +
`runtime_profile`. **All four parts are superseded**, and the erratum is owed:

| dropped | why |
| --- | --- |
| `mode: custom_code` | the **type** is the discriminator; a field would be a second copy of it |
| `library` | it is `document.libraries` — pins with sha256s, which the PRD's field never had |
| `runtime_profile` | P2 is web-only (ADR-0017 D2); the field names a choice that no longer exists |
| `annotations` / `interactions` | the module draws them; they are Flint-directed grammar |

`contract_version` is **not** lifted to the recipe. It is already on `ChartDocument`, where
ADR-0017 Decision 16 put it, and a second copy is a second thing to keep in step.

### 3. `theme_spec` is carried, and never validated against the pin

ADR-0007 Decision 6 stores it on the frame because *"it is the document's intended colours, not
an engine setting"* — and stores it knowing ECharts discards it and raises `theme_spec_ignored`.
That argument transfers exactly. ADR-0017 Decision 14's *best effort* is a statement about
**enforcement**, not about whether the intent is recorded, and it says tokens ride the channel
without saying whose. Omit the field and a user who chose `economist` loses that choice **at the
moment they escape**, silently, which is the rail's worst possible time to lose something.

The price is accepted and named: `theme_spec`'s preset list is **Flint's vocabulary**
(ADR-0009 Decision 7), so this puts a pin-versioned vocabulary onto an artifact Flint never
sees — a narrow instance of the coupling ADR-0007 Decision 2 refused for the frame.

It is paid down by refusing to check it. **`bind_recipe` does not validate `theme_spec` against
the pin.** A stale or unknown preset **falls back to the org default and never errors**, so a
pin bump that retires a preset name cannot make a stored recipe unbindable. This is deliberately
unlike the frame path, where `SpecVocabularyError` is a hard error with no warn-and-strip: there
the value reaches an assembler that will silently mis-draw, and here it reaches a palette
lookup that has a defined default.

**Erratum — 2026-09-26 ([#189](https://github.com/thearcscode/chartagent/issues/189)).**
Decision 2's sketch types `theme_spec` as `ThemeSpec | None`. The frame's field is
`ThemePresetName | ThemeSpec | None`, and copying that closed literal onto a recipe would
make a retired preset unconstructable — the failure Decision 3 exists to prevent. The type
is `str | ThemeSpec | None`, on `ChartRecipe` and on the `theme_spec` `bind_recipe` copies
onto `BoundRecipe`. `bind_recipe` still does not validate it against the pin.

### 4. `escape` leaves `x_chartagent`; `spec_version` becomes 1.2; the line is shared

The key set returns to five: `spec_version`, `transform`, `annotations`, `interactions`,
`source_schema`. A key that would be `null` in 100% of frames forever is a grammar promise
maintained for nothing, and its presence is what keeps inviting the field answer back.

**Nothing is migrated.** ADR-0002 Decision 9's canonical JSON omits nulls, so `escape: null`
was never in stored bytes; ADR-0010 Decision 1's rule holds — this amends the grammar, not
existing bytes.

The bump is **MINOR under ADR-0008 Decision 13**, taking `spec_version` to **1.2**.

**One grammar line, shared with the recipe.** `transform` and `source_schema` are not merely
similar across the two artifacts — they are the *same* objects, validated by the same models
and produced by the same planner. Two lines would make `transform`'s version depend on which
artifact holds it, and the next menu change (`pivot` or `window`, both cut to P1 by ADR-0008)
would have to bump twice for one change.

**So recipes are born at 1.2, and the archaeology is named here rather than discovered: 1.0
and 1.1 are frame-only history a recipe never lived through. A 1.2 recipe with no 1.0 ancestor
is not a bug.** ADR-0007 Decision 4 already accepted `spec_version` as a compatibility field
with the document counter housed separately in `revision_number`, and ADR-0010 Decision 10
already recorded that this bump *"signals the grammar moved without guaranteeing anyone
notices."* Both readings hold unchanged.

**This ADR does not decide what the façade does with `escape` on an arriving frame.** Dropping
the key gives the parked *unknown keys inside `x_chartagent`* entry its **first live case** — a
1.0 or 1.1 frame may legitimately name a key the 1.2 set no longer declares — and deciding it
here would settle the grammar's extensibility policy as a side effect of a placement ticket,
which is the exact mistake ADR-0010 Decision 6 refused to make.

### 5. `bind_recipe` is a second verb, and `BoundRecipe` has no wire format

```python
def bind_recipe(recipe: ChartRecipe, data: DataSource) -> BoundRecipe: ...
```

`bind(spec, data, *, backend)` cannot serve this: `backend` is required and there is no
vocabulary to validate against. Widening it with a required-except-sometimes kwarg is worse
than a second name.

Studio must not run the transform itself. ADR-0008 spent its authority on three independent
locks around `raw_sql`, and ADR-0010 Decision 1 already refused the shape where the app writes
a second comparison. The transform run, the drift check and ADR-0017 Decision 9's JSON
serialisation are **library-owned and identical on both rails**; only the Flint half differs.

**`BoundRecipe` does not return `BoundDocument`, and it is not paintable.** `BoundDocument`
carries `theme` and library **bytes**, which are paint-time inputs — `bind` does not take the
Flint IIFE as a keyword argument, and this verb does not take blobs. The composition happens
at paint time: **Studio** calls `build_shell` and pushes rows and theme on the channel; the
**`Rasteriser`** composes a `BoundDocument`. A refresh that only writes `bind_caches` must
never be forced to fetch a 4 MB blob to do it.

**`BoundRecipe` has no serialised form.** `Envelope`'s three-key wire exists for exactly one
reason — the client compiles it (ADR-0001 Decision 5, ADR-0005 Decision 5) — and nothing
compiles a `BoundRecipe`. What crosses to the browser is `build_shell`'s `Shell` plus the
channel payload, already specified. The recipe serialises; the bound recipe does not. Recorded
so no one adds a wire later out of symmetry with `Envelope`.

Diagnostics ride on the object exactly as ADR-0005 Decision 5 established: `.row_count`,
`.elapsed`, `.warnings`, `.source_schema`.

### 6. `bind_recipe` never reads the code

It touches `transform`, `source_schema` and `theme_spec`. It does **not** read `module`,
`styles` or `libraries`.

Three things follow, and they are the point rather than a side effect:

- **A refresh cannot fail on the code.** Its failure modes are the deterministic rail's —
  `SchemaDriftError`, the transform's errors, `retype_unchecked` when the baseline is absent or
  partial (ADR-0010 Decision 7).
- **`contract_unsupported` stays at `build_shell`**, where ADR-0017 Decision 16 put it. It is a
  paint-time refusal, not a bind-time one.
- **`bind`'s inline-`data` refusal has no analogue.** A recipe has no `data` slot at all; rows
  attach to the bound object. There is nothing to be ambiguous with.

### 7. One column, discriminated — not a sixth table

`spec_revisions` keeps holding the stored artifact, and the artifact is now a frame **or** a
recipe.

ADR-0007 Decision 2's argument for one opaque column — *"a storage layer that owns no copy of
the library's grammar"* — applies to the recipe word for word. Shredding `module`, `styles` or
pins into columns is the same rejected move, one rail over, and it drifts on the first contract
bump.

The column is renamed **`frame` → `content`**, which pairs with the column already beside it:
`content_hash = sha256(canonical_json(content))` is now one sentence. *`artifact`* was the
runner-up and is rejected because ADR-0007 already spends that word on the **row** — *"the
stored artifact is an app-owned wrapper"* of identity, title, timestamps and owner. The jsonb is
the thing inside the wrapper.

`kind` is `'frame'` | `'recipe'`, as `text` + `CHECK` under ADR-0007 Decision 13's rule.

### 8. The migration is four items, and D4's retention argument is restated

Additive on ADR-0007 Decision 14's schema, in full:

```sql
ALTER TABLE spec_revisions RENAME COLUMN frame TO content;

ALTER TABLE spec_revisions
  ADD COLUMN kind text NOT NULL DEFAULT 'frame'
    CHECK (kind IN ('frame','recipe')),
  ALTER COLUMN authored_flint_version DROP NOT NULL;

ALTER TABLE runs ALTER COLUMN backend DROP NOT NULL;
```

- **`kind`** discriminates. The `DEFAULT` exists for the migration and every insert writes it.
- **`content`** — Decision 7.
- **`authored_flint_version` becomes nullable.** It is a recorded fact about which pin authored
  a frame (ADR-0007 Decision 11) and is meaningless for a recipe. **No `contract_version` column
  is added** — that value is already on `ChartDocument`, inside `content`.
- **`runs.backend` becomes nullable.** It is `NOT NULL CHECK (backend IN (five))` today, and a
  custom-rail bind has no backend. `runs.error_code` is unaffected: a recipe's bind raises the
  same typed transform and drift errors.

**`bind_caches` is unchanged.** Its `{revision_id, rows}` object and its guard key are
rail-independent — see Decision 12.

**ADR-0007 Decision 4's retention argument is restated on measured sizes.** It set retention
unbounded on *"a frame is single-digit kilobytes, so a thousand revisions is a couple of
megabytes."* A recipe carries a JavaScript module and optional CSS and is realistically
**10–20 KB**, so a thousand revisions is tens of megabytes, not two. Still cheap, still
unbounded at v0 — but the sentence that justified it no longer describes the payload, and the
bound is restated rather than inherited.

### 9. `canonical_json` widens; it is the content address, and it is not the review diff

**The accessor takes the union.** `canonical_json` is `InputFrame.canonical_json()` re-exported
as `chartagent.canonical_json(spec)` (ADR-0005 Decision 8). Both types keep the method and the
module-level accessor accepts either. Decision 7 puts both artifacts in one column addressed one
way; Studio must not learn two functions to hash two things it stores in one place.

**Omit nulls, never empties.** ADR-0002 Decision 9's rule is about nulls. `libraries=[]` is a
first-class outcome (ADR-0017 Decision 4) — the from-scratch document saying so — and stays
present and empty. Stated because the rule is otherwise read loosely by the next person to
optimise it.

**It stays the content address for both rails.** ADR-0007 Decision 3's `sha256(canonical_json)`,
the `UNIQUE (chart_id, content_hash)` dedup and the no-op unchanged save all work on a recipe
unchanged.

**It is not the review diff for a recipe.** ADR-0007 Decision 2 makes canonical JSON the diff
unit and Decision 4 leans on it — `5a`'s patch-mode review *"assumes a revision is a deliberate
act with a diff worth approving."* A canonical-JSON diff of a recipe is **one changed line
containing an entire JavaScript program**, and PRD §7.7 promises the opposite for exactly this
rail: *"custom rail: targeted code edits, not rewrite,"* reviewed in light mode. So `module` and
`styles` diff as **text** and the rest as JSON.

**What that surface renders is not designed here.** It belongs to `5a` and the review-gate work.
What is decided here is only that ADR-0007 Decision 2's sentence does not cover this case, so
nobody inherits it as though it did.

### 10. A chart's history may mix frame and recipe revisions

`kind` is per revision, so this is decidable, and it is how a rail change is recorded.

**Escalation does not, by itself, produce a mixed history.** ADR-0007 Decision 4 is explicit
that *"a revision is created by an explicit save and by nothing else. No autosave in v0."* The
gate's escalation (bucket 4) happens inside one generation, before any save — the expressible
frame that failed review was never a revision. An escalated chart's revision 1 is a recipe.

What produces mixed history is PRD §7.7's **regenerate**, across two explicit saves, in both
directions.

Forbidding it costs more than allowing it. A rail change would have to be a **new chart** — new
id, new URL, history abandoned, the bookmark ADR-0007 Decision 3 exists to protect broken — and
there is no principled site for the ban, since nothing at save time knows the previous
revision's rail was meant to be sticky. Allowing it leaves `charts.current_revision_id` pointing
at whichever, `revision_number` monotonic across both, and `bind_caches`' guard key doing
exactly the right thing: a rail change makes the pointer stale, and the card says *Refresh to
bind*, honestly.

**`charts.title`'s default rule gains a branch.** ADR-0007 Decision 14 defaults it from the
chart type and the source name — `"Bar chart · q3_revenue.csv"` — and a recipe has no chart
type. A recipe's default is **`"Custom · {source name}"`**, with the same URL-source rule (last
path segment, else host). The column stays `NOT NULL` and non-blank: Decision 14 refused a
nullable title because every listing surface would grow its own fallback and they would
disagree, and that reason is untouched.

### 11. The escape reason is required on every recipe, and carried forward

A recipe exists **because** of an escape, and a bucket is always determinable: the planner
writes 1–3 at plan time, the gate writes 4 at escalation (ADR-0016 Decision 3). So
`escape_reason` is required, not nullable.

**It reconciles to the four buckets and mints nothing.** ADR-0013 Decision 11's promise —
*"when it lands it reconciles to this list; it does not mint a second vocabulary"* — is
discharged here. Buckets 1 and 2 carry ADR-0016 Decision 4's single closed lever-naming field;
3 and 4 carry none. Bucket 2's field is still not the menu lever; that is `raw_sql_used`.

**A patch-mode edit carries the reason forward.** Editing the module does not change *why* the
chart escaped, so revision N+1 holds the same reason. Nothing recomputes it on a save.

**ADR-0013 Decision 12's histogram reads the corpus scorer's records, not Postgres.** ADR-0013
puts the scorer outside the library with a committed report, and nothing here licenses a jsonb
analytics query over `spec_revisions`. The field's presence in the store is for the chart, not
for the number.

### 12. ADR-0016 Decision 15's `assemble*` hole is closed; the backend switcher is absent

**Withdrawn**: *"that a custom-rail card cannot `assemble*` those rows is Studio's P2 hole."*
Under ADR-0017 nothing on this rail calls `assemble*`. The paint path is `build_shell` plus the
sandboxed iframe plus `postMessage`, and `bind_caches`' `{revision_id, rows}` is precisely the
channel's payload — backend-independent, and already ISO-8601-normalised by ADR-0001
Decision 3 before caching (ADR-0007 Decision 6).

So a custom-rail card **participates in the Library exactly as a Flint card does**: pointer
match on `revision_id` and `source_id`, cache fetch, render; pointer miss, *Refresh to bind*.
The guard key's argument is unchanged and rail-independent — a new revision means a new artifact,
so pairing the previous recipe with new rows is a wrong chart, not merely an early one.

**Decision 15's other two claims survive.** Refresh is zero inference cost and **not** zero
infrastructure — ADR-0017 restates the boundary as a browser rather than a Python sandbox — and
there is still no artifact caching on the refresh path, because unchanged rows are a Library
load and a real refresh has new rows.

**One consequence, named rather than discovered: the backend switcher is absent on a custom-rail
card.** ADR-0007 Decision 6 has the card *"reconstruct the envelope locally — `flint_version`
from the served bundle, `backend` from the current UI switch."* None of that exists here.
Therefore ADR-0007 Decision 7's `backend_switch` trigger — a user action, a bind, a cache
replacement and a run row — **never fires for these charts**, and `runs.trigger_kind` keeps all
four values only because the frame rail still uses them.

### 13. A custom-rail Library card is cheap, but not free

ADR-0007 Decision 6's claim is *"one object fetch per card — no bind, no DuckDB read, no run
row,"* resting on ADR-0006 Decision 12's *"nothing on the server."* On this rail the second half
is **literally false**, and it is the first server work a Library load has ever done:

- `build_shell` is **Python, in the base wheel** (ADR-0017 Decision 11), so it runs on Studio's
  server, on ADR-0006 Decision 3's threadpool.
- It **never fetches** (ADR-0017 Decision 12), so the caller pulls every pin's bytes from the
  blob store first.
- Those bytes are not small: measured minified, ECharts ≈ **1,009 KB**, Plotly ≈ **4,451 KB**.

`6e`'s six-card page of ECharts-based custom-rail charts therefore moves ~6 MB through the
server that a Flint page moves none of.

**v0's answer is an in-process cache of library blobs keyed by sha256.** They are globally
content-addressed and immutable (ADR-0017 Decision 10), which makes them the easiest cache in
the system, and cards on one page overwhelmingly share pins — which collapses N fetches to
roughly one per distinct library per process.

**Shell caching is named and not required.** The assembled `Shell` is rows-free and theme-free
(ADR-0017 Decision 11), so it is deterministic in `(document, pin bytes)` and identical for the
user path and the review path — exactly content-addressable. It is not required at v0 because
the string assembly is not the cost; the bytes are.

**Client-side assembly is refused.** `build_shell` **is** the security boundary — ADR-0017
Decision 11's whole argument for making it public — and a second implementation in JavaScript is
the one thing that decision forbids.

### 14. What `__all__` gains

`ChartRecipe`, `BoundRecipe`, `bind_recipe` — three names on top of ADR-0017 Decision 18's
seven. ADR-0005 Decision 12's contract widens accordingly.

`EscapeReason` is a field type on `ChartRecipe`, exported with it.

## What this amends

- **ADR-0002** — Decision 1's key set drops `escape` and returns to five; the **open question in
  *Related* is closed** by Decision 1 here. Decision 2's fixture invariant is untouched and is
  part of the argument (an escape frame would have satisfied it vacuously). Decision 9's
  null-omission rule is clarified, not changed: nulls, never empties.
- **ADR-0005** — Decision 8: `canonical_json` widens to `InputFrame | ChartRecipe`.
  Decision 12: `__all__` grows by Decision 14's three names. Decisions 1, 3 and 5 are
  **untouched** — `bind` keeps its signature, its refusals and its three-key wire.
- **ADR-0007** — Decision 2 gains the discriminator and no longer claims canonical JSON as the
  review diff for every stored artifact; Decision 4's retention argument is restated on measured
  recipe sizes; Decision 6's *"nothing on the server"* is corrected for this rail (Decision 13)
  and the backend switcher is recorded as absent (Decision 12); Decision 14's `charts.title`
  default gains a custom-rail branch and its SQL takes Decision 8's migration. **Decisions 3, 5,
  9, 10, 11, 12, 13 and 15 stand unchanged.**
- **ADR-0013** — Decision 11's *"`escape` placement stays fog"* is **discharged**, and the
  vocabulary is reconciled to, not replaced (Decision 11 here).
- **ADR-0016** — Decision 8's requirement is **met**: the code has a home. Decision 15's
  `assemble*` clause is **withdrawn**; its refresh and no-caching clauses stand. Decisions 3 and
  4 stand and are consumed.
- **ADR-0017** — Decision 18's `__all__` list grows by three. Decision 8's `ChartDocument` is
  unchanged and is now **contained** rather than stored bare; `BoundDocument` is unchanged and
  stays the paint-time type.
- **PRD §8** — the escape's four-part shape (`mode` + `reason` + `library` + `runtime_profile`)
  is superseded in all four parts (Decision 2), and *"whether it is a field inside
  `x_chartagent` or a sibling result type is still open"* is **closed**.
- **PRD §7.3** — the `x_chartagent` key list drops `escape` and reads five.
- **PRD §7.7** — custom-rail refresh is `bind_recipe` plus the channel; the review diff for a
  recipe is a text diff of the module, not a spec diff.
- **PRD §9 P0.5** — *"re-invoking with new data requires no LLM call"* is **satisfiable**: the
  recipe is stored, and `bind_recipe` re-runs the transform without a model call.

## Consequences

- **P0.5 is unblocked, and so is ADR-0007's schema.** The thing ADR-0016 Decision 8 recorded as
  blocking both now has a type, a column and a verb.
- **The last of `chartspec-v1`'s open questions is closed.** The README's *"escape spec carries
  encodings that nothing reads"* is answered by deleting the encodings, not by explaining them.
- **The library has two bind verbs and three bound types.** `Envelope` (a bound frame),
  `BoundRecipe` (a bound recipe — **cannot paint**), `BoundDocument` (**can**). The distinction
  between the last two is the one a reader will get wrong, which is why the glossary states it
  in those words.
- **Refresh is now genuinely rail-symmetric.** Same verb shape, same failure modes, same cost —
  because `bind_recipe` never reads the code (Decision 6). The rails diverge only at paint.
- **A custom-rail Library card costs server work**, which no Library card did before
  (Decision 13). It is the first retreat from ADR-0006 Decision 12's per-card claim.
- **A pin-versioned vocabulary now rides an artifact Flint never sees** — `theme_spec` on a
  recipe (Decision 3). Priced, and paid down by never validating it.
- **The parked fog entry gets harder, not easier.** Dropping `escape` means a stored 1.0 or 1.1
  frame can name a key the 1.2 grammar no longer declares — the first live case *unknown keys
  inside `x_chartagent`* has had. Pointed at, not decided.
- **`__all__` grows by three**, the second widening in two ADRs.

## Alternatives rejected

- **`escape` as a field on `x_chartagent`.** The frame is unconstructible without naming a
  `chartType` it never draws; the fixture invariant passes vacuously; `bind` refuses its own
  carrier. Rejected on the first of these alone.
- **Promoting `ChartDocument` to the stored artifact.** It has no `transform`, so refresh has no
  rows, and no `source_schema`, so drift cannot be detected. The stored thing is a wrapper.
- **A sixth table, `chart_documents`.** Buys queryability of parts nothing queries, and breaks
  ADR-0007's *"the frame lives in exactly one place"* property to do it.
- **A second nullable `document jsonb` column on `spec_revisions`.** Produces a row that is
  legally both, which the `CHECK` then has to forbid — a discriminator wearing a worse shape.
- **`bind_recipe` returning `BoundDocument`.** It would force theme and library bytes into a
  verb that binds rows, so a refresh writing only `bind_caches` would have to fetch a 4 MB blob
  to do it. `bind` does not take the Flint IIFE either.
- **A wire format for `BoundRecipe`.** `Envelope`'s wire exists because the client compiles it.
  Nothing compiles a `BoundRecipe`; the browser gets a `Shell` and a channel payload.
- **Widening `bind` with an optional `backend`.** A required-except-sometimes keyword on the one
  verb ADR-0005 Decision 1 froze, to avoid a second name.
- **A separate `spec_version` line for recipes.** `transform` and `source_schema` are the same
  grammar on both artifacts; two lines would record one menu change as two versions.
- **A `contract_version` column on `spec_revisions`.** Already on `ChartDocument`, inside the
  jsonb.
- **Validating `theme_spec` against the pin in `bind_recipe`.** A retired preset would make a
  stored recipe unbindable, on a rail where the value only ever reaches a palette lookup with a
  defined default.
- **Forbidding mixed frame/recipe history on one chart.** Makes a rail change a new chart, which
  loses the URL and the history, with no principled place to site the ban.
- **Client-side shell assembly to spare the server.** `build_shell` is the security boundary;
  ADR-0017 Decision 11 forbids a second implementation.
- **Shredding `module`, `styles` or pins into queryable columns.** ADR-0007 Decision 2's
  rejected move, one rail over.

## What this feeds

- **Unknown keys inside `x_chartagent`** (fog) inherits its first live case — a 1.0/1.1 frame
  naming the dropped `escape` key — and is otherwise untouched.
- **Review-gate tier design** (fog) inherits the recipe as the artifact a light-mode patch review
  diffs, with `module` and `styles` as text (Decision 9), and bucket 4 as a reason it writes onto
  a recipe at escalation (Decision 11). `CheckResult` is still its to define.
- **`5a`'s patch-mode surface** inherits the text-versus-JSON diff split, and designs it.
- **Studio** inherits the four-item migration, the `"Custom · {source name}"` title default, the
  absent backend switcher, the in-process blob cache, and the user-facing assembly-failure
  vocabulary ADR-0017 Decision 15 left it.
- **The python widening** inherits `ChartRecipe` unchanged in shape: a different `document`, the
  same `transform`, `source_schema` and `escape_reason`.

## Related

- ADR-0002 — the frame and `x_chartagent`; its *Related* question is closed here.
- ADR-0007 — the five tables; Decisions 2, 4, 6 and 14 carry errata dated to this ADR.
- ADR-0016 — Decision 8 stated the requirement; Decision 15's `assemble*` clause is withdrawn.
- ADR-0017 — `ChartDocument`, `BoundDocument`, `build_shell`, and the rows this ADR supplies.
- `prototypes/chartspec-v1/README.md` — where the question was first asked, and the
  `E_ESCAPE_CONFLICT` rule that half-admitted it.
- PRD §7.3, §7.7, §8, §9 P0.5.
