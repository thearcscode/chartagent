# 7. What Studio stores

- **Status:** Accepted (amended 2026-08-27, 2026-08-30)
- **Date:** 2026-08-25; Decision 8 amended 2026-08-27 (ADR-0010) — one exception to the byte-identical cache test; Decisions 3 and 7 amended 2026-08-30 ([#81](https://github.com/thearcscode/chartagent/issues/81))
- **Settled on:** [#28](https://github.com/thearcscode/chartagent/issues/28)
- **Builds on:** ADR-0002 (the input frame *is* the spec; canonical JSON is the diff
  unit), ADR-0005 (`canonical_json` is public precisely so this schema does not write its
  own), ADR-0006 (Clerk identity, object storage, no rasterisation)
- **Amends:** ADR-0006 Decision 2 — an erratum is appended there, dated 2026-08-25.
  *"Separate services added later"* meant *not inside the web image*, not *after v0*.
- **Governs code that lives elsewhere.** Studio is
  [`thearcscode/chartagent-studio`](https://github.com/thearcscode/chartagent-studio) —
  private. The ADR landed in the library repo for ADR-0006's reason: the sequence should
  not fork before the second repo held a file. **New Studio ADRs, `CONTEXT.md`, and
  tickets land in the Studio repo** as of 2026-08-30. This ADR stays here as the decision
  record.
- **Leaves open:** where the *spec's* planning baseline for retype drift lives —
  [#42](https://github.com/thearcscode/chartagent/issues/42), which this ADR deliberately
  does not pre-empt (Decision 13). The host and object-store vendors stay unchosen, as
  ADR-0006 left them.

## Context

The library is stateless by design — PRD §7.8 is explicit that the caller owns state.
Studio cannot be, and this is exactly where it stops being a thin wrapper.

**Four of #28's six original questions arrived already answered.** ADR-0006 made accounts
real via Clerk and put `owner_id` on every saved record from the first schema; put
uploaded bytes in object storage behind a narrow interface and rejected Postgres `bytea`;
cut warehouse connectors, which removed customer credentials from the application
entirely; and declined thumbnails. What remained was the schema itself, the storage
engine, revision history, and scheduled refresh.

**Two collisions were found by reading rather than by deciding, and both change what the
schema is allowed to say.**

*`spec_version` is not a document revision.* `prototypes/chartspec-v1` D7 defines it as
grammar/adapter compatibility — same MAJOR, and `spec.MINOR <= adapter.MINOR` — and
ADR-0002 D7 kept it verbatim. But `design/`'s `5b` showed a drift remap bumping *"spec
version 1.0 → 1.1"*, and #27's resolution spoke of *"a document's version bumps on edits
and not on runs."* Those are two counters wearing one name, and a document counter riding
the compatibility field breaks D7 the first time a user edits a chart twice. The mockup
was a label error and was corrected in the resolving session; Decision 4 gives the
document counter a home of its own.

*The Library is not a bind-per-card page.* ADR-0006 Decision 12 declined thumbnails on the
grounds that a card *"costs one more `assemble*` and nothing on the server"* — true of the
compile, false of the rows. `Chartagent Studio.dc.html`'s `6e` renders **six saved
documents, every card a live compile**, and every card needs bound rows. Under the
schema as first drafted that is six `bind` calls, six DuckDB reads and six `runs` rows per
page load, for a page on which nothing was refreshed. Decision 6 removes them.

## Decision

**A real database from day one; five tables; the frame stored in exactly one place as one
opaque column; and a Library that reads a cache instead of binding.**

### 1. Managed Postgres in v0, as a second service

Not SQLite on a disk, not a directory of JSON. ADR-0006 Decision 11's own argument
decides it: a shared deployment secret was rejected because *"retrofitting identity means
migrating every stored record, and #28 writes its first schema next."* `owner_id` is a
query predicate, not merely a column, and a directory of JSON means hand-rolling listing,
filtering, atomic writes and cascade deletes — a database, written badly.

SQLite on a persistent disk was the real alternative and is recorded as rejected below: it
keeps v0 at one service, but it trades a *deferred* host-vendor decision for a hard
"must offer persistent volumes" requirement, which is the worse deferral while the vendor
is still open.

**v0's deployment shape is therefore two services, not one.** ADR-0006 Decision 2's
"separate services added later" was an argument about image composition — keeping the
~0.98 GB Playwright image out of the web service's image and cold start — and has been
read as a schedule. The erratum there corrects it. The Playwright worker is unchanged and
remains P2.

### 2. Five tables, and the frame lives in exactly one of them

`charts` · `spec_revisions` · `data_sources` · `bind_caches` · `runs`.

The stored artifact is an **app-owned wrapper**: identity, title, timestamps, owner and
source pointer are columns the app owns; the Flint frame is one opaque `jsonb` column
holding `canonical_json()` output **verbatim**. Chart type, backend and referenced fields
are deliberately **not** shredded into queryable columns — that is a second, partial copy
of a grammar the library already defines, and it drifts on the first pin bump.
`CONTEXT.md` spends the word *compile* on a job the client does; a queryable projection of
the frame is that mistake one layer down.

**Erratum — 2026-08-28 ([#60](https://github.com/thearcscode/chartagent/issues/60),
ADR-0018).** The column holds **a frame or a recipe**, and it is renamed to say so. ADR-0018
places the custom rail's stored artifact — `ChartRecipe`: `spec_version`, `transform`,
`source_schema`, `escape_reason`, `theme_spec` and a `ChartDocument` — **in this same column**,
discriminated by a new `kind` (`'frame'` | `'recipe'`). The argument above is what decides it:
*"a second copy of a grammar the library already defines"* applies word for word to shredding
`module`, `styles` or library pins into columns, and it drifts on the first contract bump. A
sixth table was rejected for buying queryability of parts nothing queries, at the cost of the
one-place property below.

`frame` becomes **`content`**, which pairs with the column already beside it —
`content_hash = sha256(canonical_json(content))` is now one sentence. *`artifact`* was the
runner-up and lost because this ADR already spends that word on the **row**: the stored
artifact is the app-owned wrapper, and the jsonb is the thing inside it.

**One clause here does not survive.** Canonical JSON stays the **content address** for both
rails, and stays the diff unit for a *frame* — but a canonical-JSON diff of a recipe is one
changed line holding an entire JavaScript program, and PRD §7.7 promises *"targeted code edits,
not rewrite"* on exactly that rail. So a recipe's review diff is **text** over `module` and
`styles` and JSON over the rest. What renders it is `5a`'s and the review gate's; ADR-0018
decides only that this sentence does not reach that case.

The frame lives **only** in `spec_revisions`. `charts.current_revision_id` is an FK to the
live one. Storing a current copy on `charts` as well would create two rows that can
disagree, and "the bytes on disk are byte-identical to what the diff is computed over"
stays true by construction rather than by a synchronisation rule nobody will remember.

### 3. Two ids: a stable chart id, and a content address within a chart

The **chart id** is an app-generated UUIDv7. It is what the URL carries and what a user
bookmarks. The **content address** is `sha256(canonical_json)`, and an unchanged save is a
no-op: the hash matches an existing revision, so nothing is written and nothing is
repointed.

`spec_revisions.id` is nevertheless a **surrogate UUIDv7 primary key**, with
`UNIQUE (chart_id, content_hash)` carrying the dedup. The hash cannot be the row's name:
duplicate a chart, or two users independently build the same frame, and it collides across
charts that must not share history. The content address is the identity of *content within
a chart*; single-column foreign keys everywhere else are worth more than the literal
reading. ADR-0005 noted `canonical_json` is *"what a content-addressed spec id is hashed
over"* — that remains true, and this is where it is scoped.

`charts.current_revision_id` and `spec_revisions.chart_id` reference each other, so the
constraint is `DEFERRABLE INITIALLY DEFERRED` and a chart's first save writes both rows in
one transaction with app-generated ids, checked at commit. Deriving *current* as
`max(revision_number)` is rejected: it is only accidentally right, and it forecloses
revert-to-revision.

**Erratum — 2026-08-30 ([#81](https://github.com/thearcscode/chartagent/issues/81)).**
Two completions of the pointer this decision already required.

**Revert is a pointer move.** It repoints `charts.current_revision_id`. It writes **no**
new `spec_revisions` row. A copy collides with `UNIQUE (chart_id, content_hash)` — the same
constraint that makes an unchanged save a no-op — so a copy-based revert would need an
exception to the dedup. Every revision stays in place; a revert is itself revertible. The
bind cache pointer goes stale (*Refresh to bind*). A revert writes no run: runs are bind
attempts, and a revert binds nothing.

**The diff is server-side, structural, over `canonical_json` output.** One implementation,
sitting next to the hash it must agree with. Hunks are added, removed and changed paths —
not a text diff of pretty-printed JSON, because canonical JSON has no formatting to
diff. Identical revisions diff to zero hunks. A diff whose only change is
`x_chartagent.source_schema` is labelled as such (Decision 8's erratum is why that shape
is ordinary).

### 4. The app owns a revision integer; `spec_version` stays a compatibility field

`x_chartagent.spec_version` keeps chartspec-v1 D7's meaning exactly — MAJOR.MINOR, for
adapter compatibility — and Studio never writes it. The document counter is
`spec_revisions.revision_number`, monotonic per chart, `UNIQUE (chart_id,
revision_number)`.

**A revision is created by an explicit save and by nothing else.** No autosave in v0: an
autosaving editor over append-only history produces a revision list no one can read, and
`5a`'s patch-mode review assumes a revision is a deliberate act with a diff worth
approving. Retention is unbounded — a frame is single-digit kilobytes, so a thousand
revisions is a couple of megabytes — and a cap is revisited only if a chart ever gets a
scripted editor.

**Erratum — 2026-08-28 ([#60](https://github.com/thearcscode/chartagent/issues/60),
ADR-0018).** The retention argument is **restated on the payload it now describes**. A recipe
carries a JavaScript module and optional CSS and is realistically **10–20 KB**, not
single-digit, so a thousand revisions is tens of megabytes rather than two. Retention stays
unbounded at v0 and the conclusion is unchanged — but the sentence that justified it no longer
describes what is stored, and the bound is restated rather than inherited.

`spec_version` also moves: dropping `escape` from `x_chartagent` takes it to **1.2**
(ADR-0002's erratum), and a `ChartRecipe` shares that one line rather than opening a second.
Recipes are **born at 1.2**; 1.0 and 1.1 are frame-only history. Studio still never writes it,
and `revision_number` is still the document counter.

`design/`'s `5b` showed a drift remap as "spec version 1.0 → 1.1". That was a mockup
label error, corrected on 2026-08-25 to show `revision 1 → 2` with `spec_version` holding
at 1.0. **`5b` is not to be rebuilt from the pre-correction canvas.**

### 5. Sources are first-class rows, and a chart remembers a default

#27 locked that the source is *"a bound object at request time, never stored in the
frame"* with *"its own lifetime"* — ADR-0002 Decision 3 expressed as a screen. So sources
are rows, not fields.

`charts.default_source_id` is nullable and is what refresh uses. A bind request may name a
different source; doing so updates the default. Storing nothing and re-picking a source
every time is rejected — refresh with no remembered pointer is just "upload again", which
is the `$0.00` pillar switched off.

An **upload** row carries the object key, original filename, content type, byte size and
`sha256`. A **URL** row carries the URL. Both carry `owner_id` and a **schema snapshot of
the source, read at registration time** — which is what `5b`'s spec-vs-snapshot field
table actually renders against.

Object keys are **content-addressed, owner-scoped and write-once**:
`{owner_id}/{sha256}.{ext}`, with a partial `UNIQUE (owner_id, sha256)` on upload rows
enforcing the dedup rather than hoping for it. Owner-scoping means dedup never crosses a
tenant boundary, which keeps this from quietly becoming a multi-tenancy decision the map
holds in fog.

### 6. The Library reads a cache; it does not bind

After a **user-initiated** bind, the transform output is written to a sibling object in
the same store — `{owner_id}/charts/{chart_id}/last_bind.json` — and the slot is
overwritten each time. `bind_caches` holds the pointer: `cache_key`, `revision_id`,
`source_id`, `row_count`, `elapsed_ms`, `bound_at`.

A normal load compares the pointer's `revision_id` and `source_id` against the chart's
current values. **On a match** the client fetches the cache, attaches it as `input.data`,
and calls `assemble*` — no bind, no DuckDB read, no run row; the picture and the
cost-and-latency line are that earlier bind. **On a miss or a missing row** the card is
empty and says *Refresh to bind*. There is no silent bind behind a page load.

**The cache object holds transform output and one guard key, and nothing else.** It is
`{revision_id, rows}`, where `rows` is exactly the `input.data` payload. No envelope, no
`flint_version`, no `backend`, no `theme_spec`, no advisory list. The guard key exists
because the slot is overwritten in place: a reader can otherwise pair the previous frame
with the new rows, or the reverse, and a new revision means a new frame — so the mismatch
is not a display being merely early, it is a wrong chart. The client discards the object
when `revision_id` disagrees with the `bind_caches` pointer. Versioned keys plus a reaper
remain available and are not a v0 requirement.

**JSON, not Parquet.** The only consumer is a browser, and a Parquet-to-JSON conversion
per Library card is server CPU this decision exists to remove. Types come from the frame's
`semantic_types`, and ADR-0001 Decision 3's ISO-8601 normalisation has already run by the
time rows are cached. Serving the bytes from a signed URL later is available for the same
reason — they are already JSON — and is not locked in v0.

**The card reconstructs the envelope locally**: `flint_version` from the **served** bundle
(never `authored_flint_version`), `backend` from the current UI switch, the frame from the
current revision, the rows from the cache.

**Erratum — 2026-08-28 ([#60](https://github.com/thearcscode/chartagent/issues/60),
ADR-0018).** Three corrections, all on this decision's reach rather than its rule.

**The cache is rail-independent, and ADR-0016 Decision 15's *Studio's P2 hole* is closed.**
That decision recorded that a custom-rail card *"cannot `assemble*` those rows"*; under
ADR-0017 nothing on that rail calls `assemble*` at all — the paint path is `build_shell` plus a
sandboxed iframe plus `postMessage`, and this decision's `{revision_id, rows}` object is
exactly the channel's payload, backend-independent and already ISO-8601-normalised. So a
custom-rail card participates in the Library on the same pointer-match rule, with the same
guard key, for the same reason: a new revision means a new artifact, so pairing the previous
recipe with new rows is a wrong chart rather than an early one.

**The paragraph above does not apply to a recipe.** There is no envelope to reconstruct, no
served `flint_version` in play, and **no backend switch** — so ADR-0018 records the switcher as
absent on these cards, and Decision 7's `backend_switch` trigger, with its bind, its cache
replacement and its run row, **never fires for them**.

**And *"nothing on the server"* is literally false on that rail.** `build_shell` is Python in
the base wheel (ADR-0017 Decision 11), so it runs on Studio's server, and it never fetches
(ADR-0017 Decision 12), so the caller pulls every pin's bytes first — measured minified,
ECharts ≈ 1,009 KB, Plotly ≈ 4,451 KB. `6e`'s six cards therefore move megabytes through the
server that a Flint page moves none of. A custom-rail Library card is **cheap, not free**, and
it is the first server work a Library load has ever done. v0's answer is an **in-process cache
of library blobs keyed by sha256** — they are globally content-addressed and immutable
(ADR-0017 Decision 10) and cards on one page overwhelmingly share pins. Caching the assembled
shell is available and not required; client-side assembly is refused, because `build_shell`
*is* the security boundary.

**Source kind does not change the rule.** Uploads, HTTPS URLs and any later table cache
the same thing, and a Library load never re-reads the source. Bytes changing behind a URL
are not a refresh. A **backend switch is a user action and therefore a bind** — it
replaces the cache, writes a run, and moves `bound_at`, which for a URL source may pick up
new bytes. That is intentional and user-initiated; opening the Library must never do it.
A URL-backed cache is *as of `bound_at`*, the card says so, and there is no conditional GET
per card load. That is a stated limit of the cache, not a defect to fix later.

**`theme_spec` stays on the frame** — it is the document's intended colours, not an engine
setting, and switching backend is a view that must not strip it. Whether it *applies* is
live from the current switch: an engine that discards it (ECharts, Chart.js) surfaces
`theme_spec_ignored` and gets the house palette through post-`assemble*` option defaults;
an engine that realises it (Vega-Lite, Plotly) raises no such advisory. That advisory is
**not** persisted on the cache, and neither are the other `Envelope.warnings` — they come
back on the next user-initiated bind, from the backend that actually produced them.

### 7. `runs` records user-initiated bind attempts, and the editor's previews are not among them

Editing a transform changes the rows, so the editor re-binds to preview, repeatedly,
against a frame that is not yet a saved revision. **Preview binds write neither a cache
nor a run** — including a preview of a spec that happens to match the current revision.
The cache is keyed to a `revision_id`, and an unsaved frame has none.

**Every user-initiated bind writes a run**, success or failure. On success: `status = ok`
and the cache is replaced. On failure: `status = error` with `error_code` set from the
typed error, and **the cache is left untouched** — a failed refresh must not blank a card
that was rendering a moment ago. This is what keeps `error_code` live rather than
decorative.

`trigger_kind` is `refresh` · `open` · `backend_switch` · `save`. The `save` value is
Decision 8's reuse path. The column is `trigger_kind` and not `trigger` because `TRIGGER`
is reserved in SQL and would need quoting forever.

**Erratum — 2026-08-30 ([#81](https://github.com/thearcscode/chartagent/issues/81)).**
The four values stay the closed set through Studio's P1 history-and-recovery work. A
generate run will need a fifth; its name is
[#79](https://github.com/thearcscode/chartagent/issues/79)'s. Widening the `CHECK` now
would guess a verb the planner output contract has not named. The column is `text` +
`CHECK` so that widening later is one drop-and-add.

So: **runs are the history of user-initiated bind attempts plus that save path; the cache
is the last successful transform.** They are not the same set, and neither is derivable
from the other.

Structured stdout logs (ADR-0006 Decision 13) stay exactly as they are. They are not the
product trail — a log line cannot be rendered into `6e`'s cost-and-latency line.

### 8. A save writes the cache when it honestly can

Save creates revision N+1, which makes the pointer stale, which would leave the card the
user *just edited* reading *Refresh to bind* — the worst-looking cell on the page always
being the one they last touched.

So: **if the frame being saved is byte-identical (by `canonical_json`) to the frame the
editor's current bound result came from, that result is written as the new revision's
cache in the same request path**, with a `save` run. If the user edited after the last
preview bind, no cache is written and the card says *Refresh to bind* honestly. A cache
is **never fabricated for a frame that was never bound**, and a save succeeds even if the
cache object write fails — the cache is an optimisation, and the revision is the record.

**Erratum — 2026-08-27 ([#42](https://github.com/thearcscode/chartagent/issues/42),
ADR-0010).** The byte-identical test gains **one exception**. ADR-0010 has the save path copy
`Envelope.source_schema` into `x_chartagent.source_schema`, which changes `canonical_json` —
so on the first honest save of every chart that predates the key, the frame being saved is
*never* byte-identical to the one the bound result came from, and every such save would
report *Refresh to bind* for a result that is perfectly good.

So: **when the only difference between the frame being saved and the frame the cache was
built from is `source_schema` copied from that same bind's envelope, write the cache
anyway.** The rows remain valid because neither Flint nor the transform reads the key — it is
a recorded fact, not an input. Every other difference still fails the test, and a cache is
still never fabricated for a frame that was never bound. Such a save also writes
`spec_version` `1.1`, since the frame now uses the sixth key.

### 9. Deletes are hard; Postgres names the keys, the app empties the bucket

No soft deletes and no tombstones in v0 — recovery is a multi-tenancy-era feature and
sits with the fog.

Deleting a chart cascades to its revisions, its runs and its cache row. Deleting a source
does **not** delete the charts built on it: `charts.default_source_id` is
`ON DELETE SET NULL`, so the chart becomes *pick a source* rather than disappearing, and
`runs.source_id` / `runs.revision_id` are `ON DELETE SET NULL` so history survives its
referents.

`bind_caches.source_id` is `ON DELETE CASCADE` — deliberately unlike
`charts.default_source_id` — because a cache whose source is gone is not stale, it is
meaningless. **Postgres does not empty the bucket.** The cascade removes the row; app code
removes the object, and removes the source's bytes when the last `(owner_id, sha256)` row
referencing them is gone. Shipping a delete that leaves a user's uploaded data sitting in
a bucket is a bad default even in a demonstrator.

### 10. `owner_id` is denormalised onto all five tables, deliberately

`spec_revisions`, `bind_caches` and `runs` could all reach it through `chart_id`. They
carry it anyway, copied by the app on insert.

ADR-0006 Decision 11's argument is that retrofitting identity means migrating every stored
record — and a join is precisely the thing that becomes a migration when
`WHERE owner_id = ?` has to be pushed down to every query, which is what multi-tenancy in
the fog will want. It costs one text column per row and makes every table independently
ownable. It is recorded here so that nobody later "normalises" it away as an oversight.

### 11. `authored_flint_version` is a recorded fact, never a gate

`spec_revisions.authored_flint_version` is written from the pin at save time. Nothing
branches on it in v0: no load gate, no compatibility check, no refusal.

It exists because a frame authored under one pin can raise `SpecVocabularyError` under a
later one — that is what ADR-0004's bump gate detects — and it is the only way to answer
*"this chart used to work"* without guessing. Whoever owns the pin-bump migration story
later needs it to exist retroactively, which is the same argument that put `owner_id` in
the first schema.

When the served pin cannot render a stored recipe, the outcome is #27's amber path: **this
app does not support this chart**. The UI may mention the revision was saved under another
pin; it must **not** tell the user to load that Flint. Serving historical IIFEs would
reopen the one-pin lock and turn this recorded fact into a gate.

### 12. Scheduled refresh is out of v0

`design/`'s `1f` lifecycle console shows scheduled refreshes; v0 does not have them. Three
independent reasons, any one sufficient: a timer needs a runtime the one-web-service shape
does not have, and the first background service is pencilled in at P2; for upload-backed
sources a schedule has nothing new to fetch, so it only ever applies to the URL slice; and
on-demand refresh already demonstrates the `$0.00` pillar completely.

`1f` stays a P1 surface. The deferral is safe in a way identity was not: adding it later
is one nullable column and one table, not a migration of every stored record.

### 13. The persistence stack

**SQLAlchemy 2.0 ORM (sync) + psycopg 3 + Alembic**, with `jsonb` via
`sqlalchemy.dialects.postgresql.JSONB`. Sync because ADR-0006 Decision 3 puts anything
touching `bind` in a sync `def` on Starlette's threadpool; mixing two concurrency models
under one request is a cost with no matching benefit at v0 scale.

Alembic because Decision 1's whole argument was that a real schema beats a directory — and
a real schema without versioned migrations is the directory with extra steps. Rejected:
**SQLModel** (a second modelling layer over the same SQLAlchemy, in an app that already
generates Pydantic models from a Flint pin — two Pydantic-flavoured model sources is one
too many), and **raw SQL with hand-rolled migrations**.

Enumerated columns are `text` + `CHECK`, not Postgres `ENUM`: `data_sources.kind` will
gain `'table'`, and a `CHECK` is one `DROP`/`ADD CONSTRAINT` where an enum value addition
is version-sensitive inside a transaction.

### 14. The schema

Presentation order is not creation order — Alembic creates the tables, then adds the two
cross-references on `charts`.

```sql
-- ids are app-generated UUIDv7; no database default, because the object key
-- needs the chart id before the row exists. owner_id is the Clerk user id,
-- denormalised onto every table on purpose (Decision 10).

CREATE TABLE charts (
  id                  uuid        PRIMARY KEY,
  owner_id            text        NOT NULL,
  title               text        NOT NULL CHECK (length(btrim(title)) > 0),
  current_revision_id uuid        NOT NULL,
  default_source_id   uuid,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE spec_revisions (
  id                     uuid        PRIMARY KEY,
  chart_id               uuid        NOT NULL REFERENCES charts(id) ON DELETE CASCADE,
  owner_id               text        NOT NULL,
  revision_number        integer     NOT NULL CHECK (revision_number > 0),
  content_hash           char(64)    NOT NULL,
  frame                  jsonb       NOT NULL,   -- canonical_json() verbatim
  authored_flint_version text        NOT NULL,   -- recorded fact, never a gate
  created_at             timestamptz NOT NULL DEFAULT now(),
  UNIQUE (chart_id, revision_number),
  UNIQUE (chart_id, content_hash)
);

CREATE TABLE data_sources (
  id                uuid        PRIMARY KEY,
  owner_id          text        NOT NULL,
  kind              text        NOT NULL CHECK (kind IN ('upload','url')),
  object_key        text,       -- {owner_id}/{sha256}.{ext}, write-once
  original_filename text,
  content_type      text,
  byte_size         bigint,
  sha256            char(64),
  url               text,
  schema_snapshot   jsonb       NOT NULL,  -- the SOURCE's schema at registration,
  created_at        timestamptz NOT NULL DEFAULT now(),   -- not the spec's baseline
  CONSTRAINT data_sources_shape CHECK (
       (kind = 'upload' AND url IS NULL
          AND object_key IS NOT NULL AND original_filename IS NOT NULL
          AND content_type IS NOT NULL AND byte_size IS NOT NULL
          AND sha256 IS NOT NULL)
    OR (kind = 'url'    AND url IS NOT NULL
          AND object_key IS NULL AND original_filename IS NULL
          AND content_type IS NULL AND byte_size IS NULL AND sha256 IS NULL)
  )
);

CREATE TABLE bind_caches (
  chart_id    uuid        PRIMARY KEY REFERENCES charts(id)      ON DELETE CASCADE,
  owner_id    text        NOT NULL,
  cache_key   text        NOT NULL,  -- {owner_id}/charts/{chart_id}/last_bind.json
  revision_id uuid        NOT NULL REFERENCES spec_revisions(id) ON DELETE CASCADE,
  source_id   uuid        NOT NULL REFERENCES data_sources(id)   ON DELETE CASCADE,
  row_count   integer     NOT NULL,
  elapsed_ms  integer     NOT NULL,
  bound_at    timestamptz NOT NULL
);

CREATE TABLE runs (
  id           uuid        PRIMARY KEY,
  owner_id     text        NOT NULL,
  chart_id     uuid        NOT NULL REFERENCES charts(id)         ON DELETE CASCADE,
  revision_id  uuid        REFERENCES spec_revisions(id)          ON DELETE SET NULL,
  source_id    uuid        REFERENCES data_sources(id)            ON DELETE SET NULL,
  backend      text        NOT NULL CHECK (backend IN
                             ('echarts','vegalite','chartjs','plotly','excel')),
  trigger_kind text        NOT NULL CHECK (trigger_kind IN
                             ('refresh','open','backend_switch','save')),
  row_count    integer,
  elapsed_ms   integer,
  status       text        NOT NULL CHECK (status IN ('ok','error')),
  error_code   text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT runs_error_shape CHECK (
       (status = 'ok'    AND error_code IS NULL)
    OR (status = 'error' AND error_code IS NOT NULL)
  )
);

ALTER TABLE charts
  ADD CONSTRAINT charts_current_revision_fk
    FOREIGN KEY (current_revision_id) REFERENCES spec_revisions(id)
    DEFERRABLE INITIALLY DEFERRED,
  ADD CONSTRAINT charts_default_source_fk
    FOREIGN KEY (default_source_id) REFERENCES data_sources(id) ON DELETE SET NULL;

CREATE INDEX        charts_owner_updated_idx  ON charts        (owner_id, updated_at DESC);
CREATE INDEX        revisions_chart_rev_idx   ON spec_revisions(chart_id, revision_number DESC);
CREATE INDEX        sources_owner_created_idx ON data_sources  (owner_id, created_at DESC);
CREATE UNIQUE INDEX sources_owner_sha_idx     ON data_sources  (owner_id, sha256)
                                              WHERE kind = 'upload';
CREATE INDEX        caches_source_idx         ON bind_caches   (source_id);
CREATE INDEX        runs_chart_created_idx    ON runs          (chart_id, created_at DESC);
```

`charts.title` is `NOT NULL` and non-blank, defaulted at creation from the chart type and
the source's name — `"Bar chart · q3_revenue.csv"`, and for a URL the last path segment or
the host if there is none — then freely editable. A nullable title means every surface
that lists charts owns its own fallback string, and they will disagree.

**Erratum — 2026-08-28 ([#60](https://github.com/thearcscode/chartagent/issues/60),
ADR-0018).** The schema above takes a **four-item additive migration**, and the title rule
gains a branch.

```sql
ALTER TABLE spec_revisions RENAME COLUMN frame TO content;

ALTER TABLE spec_revisions
  ADD COLUMN kind text NOT NULL DEFAULT 'frame'
    CHECK (kind IN ('frame','recipe')),
  ALTER COLUMN authored_flint_version DROP NOT NULL;

ALTER TABLE runs ALTER COLUMN backend DROP NOT NULL;
```

- **`kind`** discriminates a frame from a `ChartRecipe` (Decision 2's erratum). `text` +
  `CHECK` under Decision 13's rule, never a Postgres `ENUM`. The `DEFAULT` exists for the
  migration; every insert writes the value.
- **`content`** — Decision 2's erratum.
- **`authored_flint_version` becomes nullable.** Decision 11 makes it a recorded fact about
  *which pin authored a frame*; a recipe has no such fact. **No `contract_version` column is
  added** — that value is already on the `ChartDocument` inside `content`, and a second copy is
  a second thing to keep in step.
- **`runs.backend` becomes nullable.** A custom-rail bind has no backend, for the same reason
  the card has no backend switch (Decision 6's erratum). `runs.error_code` is unaffected:
  binding a recipe raises the same typed transform and drift errors, since `bind_recipe` never
  reads the code.

**`bind_caches` is unchanged**, and so are Decisions 3, 5, 9, 10, 11, 12, 13 and 15.

**A chart's history may mix `kind`s.** Escalation does not produce one — Decision 4's *"a
revision is created by an explicit save and by nothing else"* means the expressible frame that
failed review was never a revision — but PRD §7.7's *regenerate* does, in both directions.
Forbidding it would make a rail change a **new chart**, losing the URL and the history
Decision 3 exists to protect, with no principled place to site the ban. `current_revision_id`
points at whichever, `revision_number` stays monotonic across both, and a rail change makes the
cache pointer stale so the card says *Refresh to bind* — honestly.

**So the title default branches**: a recipe has no chart type, and its default is
**`"Custom · {source name}"`** with the same URL rule (last path segment, else host). The
column stays `NOT NULL` and non-blank — the argument against a nullable title is untouched.

### 15. What #28 hands #42

A bounded offer, not a refusal.

**#28 stores a schema snapshot of the *source*, at registration time, on
`data_sources.schema_snapshot`.** It does **not** store the *spec's planning baseline*, and
takes no position on whether that belongs in `x_chartagent.source_schema`. They are
different objects: a source's schema changes when the source changes; a spec's baseline is
what the spec was planned against.

If [#42](https://github.com/thearcscode/chartagent/issues/42) chooses the app-sidecar
route it lists, **the column lands on `spec_revisions`** — versioned with the frame it
describes — as an additive migration on the schema above. The type vocabulary and the
question of who writes the baseline at P0 stay #42's entirely.

## Consequences

**What we gain.** A first schema with identity in it, so the migration ADR-0006 feared
never has to happen. A Library that costs one object fetch per card instead of a bind, on
a page whose whole point is that refresh is the paid operation and viewing is not. And a
storage layer that owns no copy of the library's grammar, so a Flint pin bump cannot
invalidate a column.

**The seam held again — a fourth dogfooding pass over ADR-0005, and no new gaps.**
`canonical_json()` for both the content address and the diff, `Envelope.row_count` /
`.elapsed` / `.warnings` for the cost line and the advisory rails, `flint_bundle()` for the
served pin, and the typed errors with stable field paths for `runs.error_code` covered all
fifteen decisions above. Nothing goes back to #25.

**What it costs.** v0 is two services rather than one, which is a real retreat from
ADR-0006's shape and is why that decision gets an erratum rather than a footnote. The
cache is a second place data lives, with a staleness rule and a guard key — the price of
deleting the per-card bind, and the first thing to suspect when a card shows the wrong
picture. A URL-backed cache can be arbitrarily out of date relative to the live URL, and
this is displayed rather than checked. And `runs` is a table nothing enforces the
completeness of: it records attempts, the cache records the last success, and neither is
derivable from the other.

**What this cancels.** Scheduled refresh is out of v0, so `1f` is a P1 surface rather than
a screen to build. Nothing is scaffolded — the map's *plan, don't do* rule holds and
`chartagent-studio` is still empty.

## Alternatives rejected

**SQLite on a persistent disk.** One service, real SQL, real migrations, and genuinely
attractive for a demonstrator. Rejected because it pins the web service to a single
instance with a volume, converting ADR-0006's deliberately deferred host-vendor question
into a hard requirement on the vendor's feature list. Recorded because it was the closest
call in this ticket.

**A directory of JSON per owner.** Rejected: listing, filtering, atomic writes and cascade
deletes get hand-rolled, and `owner_id` on every record stops being a predicate and starts
being a filename convention.

**Shredding the frame into queryable columns.** Rejected. It is a second copy of a grammar
the library owns, it drifts on a pin bump, and it is the "app as a second compiler"
failure one layer down.

**A current-frame copy on `charts` beside the revision rows.** Rejected: two rows that can
disagree about what the spec is, in a product whose diff is its argument.

**Parquet as the cache format.** Rejected: the only consumer is a browser, so it
reintroduces per-card server CPU — most of what removing the bind saved — in exchange for
typing the frame already carries.

**Caching the envelope rather than the rows.** Rejected: `theme_spec_ignored` is
backend-dependent, so a replayed envelope can carry an advisory that is now false or omit
one that is now true. Rows are backend-independent; advisories are not.

**Persisting run rows for Library card loads (with a `trigger_kind` filter).** Rejected as
the write-amplification this design exists to remove: ten Library visits would be sixty
rows describing page loads, none of them a refresh.

**Soft deletes.** Rejected for v0. Recovery is a multi-tenancy-era feature.

## Related

- ADR-0002 — the input frame is the spec, and canonical JSON is the diff unit; Decision 3
  there is why `data` is never in a stored frame, which is what makes the cache a separate
  object rather than a column.
- ADR-0005 — the seam Studio consumes; `canonical_json` is public because this schema
  needed it, and would otherwise have grown its own and drifted silently.
- ADR-0006 — identity, object storage, no rasterisation. **Decisions 2 and 12 both carry
  errata dated to this ADR**: the deployment shape (two services, not one), and the
  per-card cost claim that Decision 6 revisits.
- [#27](https://github.com/thearcscode/chartagent/issues/27) — the editor surface; the
  source as a bound object with its own lifetime, and the amber "won't render here" path
  Decision 11 routes an unrenderable historical revision into.
- [#42](https://github.com/thearcscode/chartagent/issues/42) — the retype baseline;
  Decision 15 is the offer, not the answer.
- [#81](https://github.com/thearcscode/chartagent/issues/81) — Studio P1 history, diff,
  revert and drift recovery; Decisions 3 and 7's 2026-08-30 errata.
- `design/README.md` — screen index; `5b`'s version labels were corrected on 2026-08-25 to
  match Decision 4.
