# 8. The transform menu, and the three locks on its escape hatch

- **Status:** Accepted
- **Date:** 2026-08-26
- **Settled on:** [#4](https://github.com/thearcscode/chartagent/issues/4)
- **Builds on:** ADR-0001 (pin Flint; compile in the client; ISO-8601 before Flint sees
  data), ADR-0002 (the input frame *is* the spec; `x_chartagent` holds our grammar),
  ADR-0005 (`bind` is the public seam), ADR-0006 (Studio's server binds)
- **Amends:** ADR-0001 Decision 3, ADR-0002 Decision 3, ADR-0005 Decisions 1, 7, 10 and
  11, and PRD §8 — all recorded as errata in place, and listed under *What this amends*

## Context

ADR-0002 Decision 3 stores the frame **without rows** and supplies them per render from
`x_chartagent.transform`. That single sentence is what makes *"generate once, refresh
forever at `$0.00`"* true rather than aspirational — and it makes the transform the most
load-bearing object in the library. If the transform cannot express what a chart needs,
the spec is not refreshable, and the pillar is marketing.

It carries a second weight. ADR-0002 Decision 4 forbids derivation at the encoding: a
Flint channel is `{ field }` and nothing else, measured at 1830 of 1830 upstream channels.
So **every** derived value a chart draws — a monthly bucket, a sum, a margin — has to exist
as a transform output column or it cannot be drawn at all. The transform is not a
convenience layer over the data; it is the only place derivation can happen.

PRD §8 resolved the shape a year ago: a declarative operation menu plus a flagged
`raw_sql` escape, file-like sources only in v1. This ADR makes that concrete, and three
things fell out of doing so that the resolved decision did not anticipate.

**The menu as specified could not draw a monthly time series.** PRD §8's op list —
`filter, group_by, aggregate, pivot, sort, limit`, window basics — has no way to compute a
column. Nothing in it turns a `timestamp` into a `month`, or `revenue - cost` into
`margin`. Combined with Decision 4's ban on encoding-level derivation, the single most
common chart in existence was inexpressible in the menu and fell straight to the escape
hatch. The escape hatch was going to be the main road.

**`raw_sql` is not a local concern any more.** PRD §8 was written when the library ran in
the caller's own process on the caller's own data, where "this SQL can read your files" is
a tautology. ADR-0006 puts **Studio's server** on the binding side of the call, so a
Studio user's `raw_sql` now executes on our infrastructure. Statement-type validation
stops writes; it does nothing about `SELECT * FROM read_csv('/etc/passwd')`, which is a
perfectly ordinary single `SELECT`.

**The environment can change the chart.** DuckDB's null ordering, sort direction and
session timezone are all *settings*, read from the host. `default_null_order` and
`default_order` are configurable; `TimeZone` comes from the operating system — measured as
`Asia/Kolkata` on the machine this was designed on. The same stored spec, the same bytes,
a differently-configured host, and `sort desc + limit 10` returns different rows and
`date_trunc('month', …)` puts a row in a different month. Reproducibility is the property
the whole refresh claim rests on, and nothing was pinning it.

## Decision

**A closed declarative menu of eight slots in one canonical order, compiled to DuckDB's
relational API rather than to SQL text; plus `raw_sql` as an exclusive-or alternative,
held by three independent locks.**

```json
"x_chartagent": {
  "spec_version": "1.0",
  "transform": {
    "filter":    { "kind": "gt", "args": [{ "kind": "col", "name": "revenue" },
                                          { "kind": "lit", "value": 0 }] },
    "derive":    [{ "name": "margin", "expr": { "kind": "sub", "args": [
                      { "kind": "col", "name": "revenue" },
                      { "kind": "col", "name": "cost" }] } }],
    "bin":       [{ "name": "month", "field": "ordered_at", "unit": "month" }],
    "group_by":  ["month"],
    "aggregate": [{ "name": "margin_sum", "op": "sum", "field": "margin" }],
    "having":    { "kind": "gt", "args": [{ "kind": "col", "name": "margin_sum" },
                                          { "kind": "lit", "value": 1000 }] },
    "sort":      [{ "field": "month", "dir": "asc", "nulls": "last" }],
    "limit":     { "count": 24, "offset": 0 }
  }
}
```

### 1. A fixed-slot object in one canonical order, not an ordered op list

Eight slots, each appearing **at most once**, executed in exactly one order:

> `filter` → `derive` → `bin` → `group_by`/`aggregate` → `having` → `sort` → `limit`

An ordered list of ops is strictly more expressive — filter, aggregate, filter again; two
group-bys; a limit in the middle. That expressiveness is bought at a price paid three
times. There is one SQL skeleton to compile instead of a combinatorial family. There is
one form to generate, which is what [#27](https://github.com/thearcscode/chartagent/issues/27)
locked when it made the generated form the editor. And a patch-mode diff of a transform is
a diff of **named keys** rather than of list positions — which matters directly, because
ADR-0002 Decision 5 makes canonical JSON the spec-diff unit and list reordering is the
classic generator of diff noise. `design/`'s screen `5b` already draws the object form.

Expressiveness beyond the eight slots is `raw_sql`. That is the deal, and it is the same
menu-first-with-an-honest-escape shape the project uses at the rail level.

**`transform` absent or `{}` is pass-through** — all source columns, no error. Studio's
editor needs a chart to exist before a transform does. `transform: null` is never
persisted, because canonical JSON omits nulls (ADR-0002 Decision 5) and absent and null
must stay the same statement.

### 2. The menu is eight slots, and `pivot` and `window` are not among them

| Slot | Shape | Notes |
| --- | --- | --- |
| `filter` | `Expr` (boolean) | over source columns |
| `derive` | `[{ name, expr }]` | computed columns; `Expr` |
| `bin` | `[{ name, field, unit }]` or `[{ name, field, width, origin }]` | temporal or numeric |
| `group_by` | `[column]` | may name `derive`/`bin` outputs |
| `aggregate` | `[{ name, op, field? }]` | `op` ∈ seven, closed |
| `having` | `Expr` (boolean) | the **late filter**, see Decision 6 |
| `sort` | `[{ field, dir, nulls }]` | `field` must be an output column |
| `limit` | `{ count, offset }` | `offset` defaults to 0 |

**`derive` and `bin` are additions to PRD §8's list, and they are the reason the menu is
worth having.** Without them the menu cannot draw a time series, which is not a gap at the
margin. `bin`'s temporal `unit` is closed — `year | quarter | month | week | day | hour` —
and its numeric form takes a `width` and an `origin`.

**`derive` takes a closed operator set, never an expression string.** An arbitrary SQL
string in `derive` would be `raw_sql` wearing a costume: it would inherit the entire
validation burden of Decision 7 while bypassing the `raw_sql_used` advisory that makes the
escape hatch visible. If a case needs a string, it needs `raw_sql`, and saying so is the
honest answer.

**`aggregate`'s `op` is seven functions, closed:** `sum, mean, min, max, count,
count_distinct, median`. `count` takes no `field` and means `COUNT(*)`; `count_distinct`
requires one.

**`pivot` and `window` are cut from v1.** `pivot` exists mainly to produce wide
multi-series columns, and the route that consumes them — Flint's array-valued channel,
`y: ["sales", "profit"]` — is recorded in ADR-0002 as **unverified: 0 of 705 upstream
fixtures use one**. Shipping an op whose payoff has never been observed to compile is
building on a guess. `window` is a real need whose scope nobody has stated: "window
basics" in PRD §8 is undefined, and it graduates when someone names the four functions.

Both route to `raw_sql` meanwhile, and that is a **feature of the evidence, not a
concession**: a `raw_sql_used` rate concentrated on window functions is what decides P1's
menu. See *What this feeds*.

### 3. One closed `Expr` AST, shared by `filter`, `having` and `derive`

Twenty-four node kinds, a discriminated union on `kind`:

| Group | Nodes |
| --- | --- |
| Leaves | `col(name)`, `lit(value)` |
| Comparison | `eq, ne, lt, lte, gt, gte` |
| Membership | `in`, `between` |
| Null tests | `is_null`, `is_not_null` |
| String tests | `contains, starts_with, ends_with` |
| Boolean | `and, or, not` |
| Arithmetic | `add, sub, mul, div, neg` |
| Other | `coalesce`, `concat`, `case` |

`filter` and `having` are that same AST with a boolean result type, checked at validation.
They differ **only by stage** — that is, by which columns are in scope — never by grammar.
A boolean tree (`and`/`or`/`not`), not a flat list of ANDed predicates: once there is an
AST, `or` is one more node kind, whereas a flat-AND list makes the first `or` request a
schema break.

**There is no generic `fn(name, args)` node.** One would reopen DuckDB's entire function
surface — 2948 functions at the pin — and make "closed set" decorative.

Four semantics that are stated rather than inherited, because DuckDB offers both
behaviours and silence would pick one by accident:

- **`concat` is null-skipping** (DuckDB's `concat`, not `||`). Measured: `concat('a', NULL)`
  is `'a'`; `'a' || NULL` is `NULL`. A label built from three fields should not vanish
  because one is missing; a caller who wants propagation writes it with `case`.
- **`in`'s right-hand side is literals only** — never a column, never a subquery. It is a
  value test, not a join in disguise.
- **`case` requires `else`.** SQL's omitted-`ELSE` default is `NULL`, which surfaces as a
  `(null)` category or a gap nobody wrote. Requiring `else` costs four characters and makes
  the unmatched branch a stated decision; `{"kind": "lit", "value": null}` is available and
  diffs visibly. All `then`/`else` branches share one result type.
- **`div` is compiled with a zero-denominator guard.** See Decision 9 — DuckDB returns
  `inf`, not an error, and `inf` is not JSON.

**Literals are bare JSON scalars — no type tag.** JSON already distinguishes number,
string, bool and null, and a tag would be a second type system to keep in step with the
source schema we already read. Against a `DATE`/`TIMESTAMP`/`TIMESTAMPTZ` column a literal
**must be ISO-8601**, validated by us with a field path and passed to DuckDB as a bound
Python `date`/`datetime`, never as SQL text. This aligns with the engine rather than
inventing a rule: measured, `DATE '2020-01-05' > '2020-01-01'` is `true` while
`> '01/05/2020'` and `> 'Jan 2020'` both raise `ConversionException` — we reject exactly
what DuckDB rejects, earlier, and with a path the editor can render.

**SQL's three-valued logic is inherited verbatim, and the asymmetry is documented rather
than fixed.** Measured over `[1, 2, 3, NULL]`: `WHERE a != 1` returns `[2, 3]` — the null
row is dropped — and so does `WHERE NOT (a = 1)`; but `GROUP BY a` **keeps** `NULL` as its
own group. So in one pipeline nulls silently disappear at `filter` and silently appear as a
category at `group_by`. Compiling `ne` to `IS DISTINCT FROM` would be more intuitive
per-predicate and is rejected anyway: it would invent a dialect, so the same `filter` would
mean something different from the `raw_sql` a user writes to replace it, and the escape
hatch would stop being a faithful escape. The mitigation is `is_not_null`, which is one
node.

### 4. Validation is an identifier allowlist plus structure — not a type checker

Every `col(name)` in the transform is checked against the column names **DuckDB reports for
the source**. An unknown name is `SchemaDriftError`. This is an allowlist, not escaping, and
it is the whole injection story: a name that is not a real column never reaches the engine.

It costs nothing, because ADR-0005 Decision 7 already reads that schema for the drift
pre-check. And it is the right mechanism rather than merely the cheap one — measured,
**escaping does not work**. `ColumnExpression("weird name; DROP")` raises a
`ParserException`, because the expression API parses its argument as SQL; manual
double-quote doubling fixes spaces and semicolons, but a column whose name *contains* a
double quote still binds wrong (`ev"il` resolved to `evil`). There is no escape function
that is correct here. There is only an allowlist.

**One narrow type rule beyond that: literal-vs-column compatibility on comparison and
`between` nodes.** It catches the overwhelmingly common authoring error — `revenue > "100"`,
a date compared to a free-form string — with a precise field path, and needs no
function-resolution model. When schemas are written, DATE/TIMESTAMP versus string-literal
compatibility is defined explicitly, so the editor and DuckDB cannot disagree.

Everything else surfaces as `TransformError` with DuckDB's message as `__cause__` and **our
node path** attached by the compiler, which is free: we know which node was being compiled
when it threw. A full type checker over 24 node kinds is a second binder that will disagree
with DuckDB's at the edges — and disagreement means rejecting specs DuckDB would have run.
That is the translation layer ADR-0002 exists to refuse, in miniature.

### 5. The menu compiles to DuckDB's relational API, not to SQL text

PRD §8 says the menu is *"compiled by our code to the target engine's SQL"*. At v1 there is
one engine, so the menu compiles to DuckDB's **relational and expression API**
(`rel.filter(…).aggregate(…).order(…).limit(…)`) and **no SQL text is constructed for the
menu path at all**.

SQL-text generation is real work that P1's pushdown needs, and writing "compiles to SQL"
into the record as a v1 fact would be recording a fiction. PRD §8's phrase should be read
as describing P1.

### 6. `having` is the late filter, and it is legal without `group_by`

The canonical order runs `filter` **before** `derive`, so `margin > 0` — where `margin` is
derived — has no legal home in `filter`. That is an ordinary request, and left unaddressed
it would fall to `raw_sql` on day one, polluting the very evidence Decision 2 is collecting
with a gap we designed in.

So `having` is defined by **stage, not by SQL clause**: it filters over whatever columns are
in scope at that point — group keys and aggregate outputs when there is a `group_by`,
derived and binned columns when there is not.

The key keeps the name `having`, because the SQL-shaped case is the common one and the word
is familiar; the documentation calls it the late filter. One consequence is written down
honestly: **the same spec key compiles to two different SQL constructs.** Measured, it has
to — `SELECT a, b FROM t HAVING a > 1` is a `BinderException` in DuckDB, so with no
`group_by` it compiles to a post-projection filter instead, which the relational API does
directly. A second slot differing from `having` only by position was rejected: it would
break Decision 1's one-canonical-order simplicity for no expressive gain.

Three degenerate combinations, ruled: **`group_by` with no `aggregate` is legal** (distinct
categories — refusing it would force a pointless dummy `count`); **`aggregate` with no
`group_by` is legal** (a grand total is exactly one row, which is what a KPI tile is, and
`design/` draws those); **`having` referencing a column not in scope at its stage is
`SpecShapeError`**, with a precise message, because the in-scope set is already computed.

### 7. `raw_sql` is exclusive-or with the menu, reads only `source`, and is held by three locks

`raw_sql` present means **every menu slot absent**, else `SpecShapeError` — the SQL is never
examined, because the spec was malformed before we got there. No hybrid where `raw_sql`
produces a relation and menu ops compose over it: it doubles the validation surface and
makes drift-checking worse, since half the referenced columns would be checkable and half
opaque.

**The bound source is the reserved relation `source`.** `SELECT date_trunc('month', ts) AS
month, sum(rev) AS rev_sum FROM source GROUP BY 1`. One reserved name, documented, and never
reused for anything else.

Three independent locks, each doing a different job.

**Lock 1 — DuckDB's own parser, as a statement allowlist.** `con.extract_statements(sql)`
must yield **exactly one statement of type `SELECT`**. Not a third-party parser: a second
SQL grammar that can disagree with the executing one is a vulnerability, not a defence. Not
a regex. Measured on the pin:

```
SELECT 1                              n=1  SELECT
SELECT 1; SELECT 2                    n=2  SELECT, SELECT      → multi_statement
INSERT INTO t VALUES (1)              n=1  INSERT              → not_read_only
COPY (SELECT 1) TO 'x.csv'            n=1  COPY                → not_read_only
ATTACH 'x.db'                         n=1  ATTACH              → not_read_only
WITH x AS (SELECT 1) INSERT INTO t …  n=1  INSERT              → CTE-wrapped write, caught
SELECT 1 -- ; DROP TABLE t            n=1  SELECT              → comment trick, no false split
''                                    n=0                      → empty
NOT SQL AT ALL {{                     ParserException          → unparseable
```

Allowlisting `SELECT` alone also disposes of DuckDB's split `PRAGMA` classification —
`PRAGMA enable_profiling` reports as `PRAGMA` and `PRAGMA profiling_output='…'` as `SET`,
so both are refused, while the harmless `PRAGMA database_list` reports as `SELECT` and is
allowed.

**A read-only connection is not available to us**, and this is recorded because it is the
obvious first guess: `duckdb.connect(':memory:', read_only=True)` raises *"Cannot launch
in-memory database in read-only mode"*, and in-memory is what `bind` uses.

**Lock 2 — a relation allowlist from DuckDB's parse tree.** `json_serialize_sql(…)` returns
DuckDB's **own** parse tree as JSON (the `json` extension, built into the wheel). Every
relation the query names must be `source` or one of the query's own CTE names, and no
**table function** may appear. Table functions need no hand-maintained list: `SELECT
function_name FROM duckdb_functions() WHERE function_type='table'` returns **127 of 2948**
functions, derived from the pinned engine. Violations are
`RawSqlRejectedError(reason="foreign_relation")`.

This lock exists because Lock 1 stops writes and does nothing about reads, and ADR-0006 put
Studio's server on the binding side. Measured against every evasion tried:

```
SELECT * FROM '/etc/passwd'                             tables=['/etc/passwd']
SELECT * FROM 'https://evil.com/x.csv'                  tables=['https://evil.com/x.csv']
SELECT (SELECT count(*) FROM read_csv('/etc/passwd'))…  tables=['source']  funcs=['read_csv']
WITH t AS (SELECT * FROM read_parquet('s3://x/y'))…     tables=['t']       funcs=['read_parquet']
```

Nothing leaked: a bare file path in `FROM` surfaces as a table name, and a table function
inside a subquery or a CTE surfaces as a function name. **This is a parser, not a binder** —
it does not resolve `source` against a catalog — so it complements Lock 3 rather than
replacing it.

**Lock 3 — a locked-down connection, on the `raw_sql` path only.** Measured, a connection
opened with `config={"enable_external_access": False}` and then `SET lock_configuration=true`
refuses `read_csv` of an arbitrary path, `COPY … TO`, and `ATTACH`, and refuses to be
unlocked (`SET enable_external_access=true` → *"Cannot change configuration option"*).

It also blocks reading **our own source**, since flavour-1 sources are exactly filesystem
and httpfs reads. So the `raw_sql` path is two connections: **A** reads the source into
Arrow with access on; **B** is opened locked-down, is handed that relation as `source`, and
runs the `SELECT`. The **menu path keeps one ordinary connection and stays lazy** — its
identifiers are allowlisted by Decision 4 and it cannot name a file.

Re-widening the lock to "let our own reads through" was considered and is **rejected on the
record**: it is a hole an attacker aims at, and it would undo this decision a fortnight
after taking it. `raw_sql` must not ship on Studio's server without Lock 3. Refusing to
persist `raw_sql` in Studio is not the alternative — #27's editor depends on it.

### 8. `raw_sql` is not unconditionally opaque, and drift-checking degrades rather than skips

ADR-0005 Decision 7 recorded that with `raw_sql` present, *"its input columns are opaque
without parsing SQL"*, so even the source-stage pre-check degrades to a post-check. Lock 2's
parse tree makes that conditional: it reports referenced **column** names, and it reports
`STAR`.

So: run the source-stage pre-check when the tree yields a definite column set; skip to the
post-check when `STAR` is present. The transform-output check is unchanged — it can only
ever happen after the transform runs.

### 9. Three serialisation rules, applying to both paths

These are properties of **the envelope**, not of how the rows were produced. `raw_sql` is an
escape from the menu, never from the wire format — connection B carries the same timezone
pin, and the non-finite sweep runs over whatever result table exists.

**ISO-8601 for typed temporal columns only; never sniff a string.** Columns whose DuckDB
type is `DATE`/`TIMESTAMP`/`TIMESTAMPTZ` are formatted ISO-8601 on serialisation. A
`VARCHAR` is never inspected, never guessed at, never rewritten. ADR-0001 Decision 3 puts
date normalisation in this layer because `"Jan 2020"` yields a temporal axis under V8 and an
ordinal one under SpiderMonkey — but a silent rewrite of a string *we guessed at* is the
same silently-wrong-chart class, and it is indeterminate on values like `03/04/2020`. The
residual string case is served three other ways: `bin` makes producing a properly-typed
column the easy path, `semantic_types` states meaning where parsing cannot, and `raw_sql`
casts explicitly. **This means ADR-0001's "closes the last 10 of 705" is not discharged by
this layer** — see the erratum there.

**`TimeZone='UTC'`, pinned on our connection; `TIMESTAMPTZ` serialises as UTC with a
trailing `Z`.** Measured, `current_setting('TimeZone')` is read from the operating system —
`Asia/Kolkata` on the machine this was designed on — so without a pin, `TIMESTAMPTZ`
rendering and `date_trunc` bucketing both depend on the host. Same spec, same bytes,
different chart. The cost is stated plainly: **a "daily revenue" chart over `TIMESTAMPTZ`
data buckets in UTC, not in the viewer's zone**, which will surprise someone. A per-spec
viewer timezone is not v1; it belongs to whoever asks for it.

**Non-finite floats become `null`.** Measured: **`SELECT 1/0` returns `inf`** in DuckDB —
not `NULL`, not an error — and `json.dumps` emits the bare token `Infinity`, which is
invalid JSON that a browser's `JSON.parse` rejects outright. Unhandled, a `div` over a zero
produces an envelope the client cannot parse, with nothing in the library's error surface
explaining it. So `div` compiles with a zero-denominator guard yielding `null`, and any
remaining non-finite float — including one arriving from the source data — is converted to
`null` at serialisation. `null` is the honest statement: the value is not a number, and
every renderer draws a gap. Raising instead was rejected — one bad row would refuse a whole
chart, and this is a data condition, not a spec defect.

### 10. `bin` emits the narrowest type, never a label string

Measured, `date_trunc` returns `TIMESTAMP` **even from a `DATE` input**, so a monthly bin
would otherwise reach Flint as `"2020-03-01T00:00:00"` — correct, ISO-8601, and a terrible
axis label.

Temporal `bin` therefore casts down: **`DATE` for `year|quarter|month|week|day`,
`TIMESTAMP` for `hour`.** Numeric `bin` emits **the bin's lower edge as a number**, with
`origin` defaulting to 0.

**Emitting a formatted label (`"Mar 2020"`, `"10–20"`) is rejected outright** — it is
precisely the ordinal-versus-temporal failure ADR-0001 Decision 3 exists to prevent, and it
makes the column unsortable and unscalable. Pretty labels are `semantic_types` and
`field_display_names`, written by the planner or the editor; `bin` does not mutate the frame
around itself in v1.

### 11. Reproducibility is pinned, not inherited

Measured, `default_null_order` (`NULLS_LAST`) and `default_order` (`ASCENDING`) are
connection **settings**, host-configurable, and `lock_configuration` does not set them for
us. Both are pinned explicitly on our connection.

Pinning is not sufficient on its own: `ORDER BY revenue DESC LIMIT 10` over ties has no
defined winner, so a refresh against *identical* data can legitimately return a different
ten rows. So **when `limit` is present, every remaining output column is appended as a
trailing ascending tiebreak**, in a fixed output-column order, making the result a function
of the data alone.

`sort` keys also carry an explicit `nulls: "first" | "last"`, defaulting to `last` —
relying on a pinned global for a per-spec question is how the setting drifts back in.

This is the transform's half of reproducibility. ADR-0002 Decision 6's pinned `baseSize` is
the other half.

### 12. `bind` gains a `timeout`, because ADR-0006 configured one it could not reach

ADR-0006 Decision 9 lists *a DuckDB statement timeout* among four caps, "all as
configuration". ADR-0005 Decision 12 lists *"DuckDB connection handling"* as **private**.
Studio therefore had a configured timeout and no way to apply it.

```python
def bind(spec, data, *, backend: Backend, timeout: float | None = None) -> Envelope
```

Expiry raises `TransformError`. It is one keyword, and it is the only one of ADR-0006's four
caps that must live inside the library, because it is the only one guarding *our* execution
— the 50 MB upload limit and the row cap stay Studio's, correctly. A module-level
`configure()` (process-global, awkward under concurrency, a second entry point), an
environment variable (invisible, untestable per call), and "the HTTP request timeout is
enough" (abandons an in-flight query rather than cancelling it) were all rejected.

Lock 3's materialisation has a memory cliff that a timeout does not save you from: 50 MB of
compressed Parquet is comfortably multi-GB in Arrow, and Studio's row cap is measured on
transform *output* — after the step that would blow up. So **`memory_limit` is set on both
connections**, converting an OOM kill into a catchable DuckDB exception re-raised as
`TransformError`, plus a pre-flight row/byte guard where the source exposes one for free
(Parquet footers). That is ADR-0006 Decision 9's "raises rather than truncates" posture
applied one layer down. The numeric limit is configuration, like the timeout, never a
literal.

### 13. No transform version field; unknown slots are a hard error

The menu rides `x_chartagent.spec_version` (D7's `MAJOR.MINOR`). Two version numbers on one
document is a compatibility matrix.

What protects us is different, and stronger: the slot vocabulary is **closed**, and an
unrecognised slot is `SpecShapeError` — never ignored. Adding `window` in P1 is a
`spec_version` MINOR bump, and an old reader meeting a new spec fails loudly at the unknown
slot. This is worth stating because "ignore unknown keys" is the default instinct and it is
exactly wrong here: a silently-dropped `filter` draws a chart over unfiltered data.

## What this amends

Recorded as dated errata in place, so a reader of the original decision is not required to
find this ADR to learn what changed.

| Document | What moved |
| --- | --- |
| **ADR-0001** D3 | The "closes the last 10 of 705" claim is not discharged by this layer — Decision 9 never sniffs strings |
| **ADR-0002** D3 | The transform's shape, which Decision 3 asserted the existence of and left unspecified |
| **ADR-0005** D1 | `bind` gains `timeout` |
| **ADR-0005** D7 | `raw_sql` is not unconditionally opaque — Decision 8 |
| **ADR-0005** D10 | `RawSqlRejectedError.reason` as a six-value `Literal`; new `SpecShapeError` cases |
| **ADR-0005** D11 | Five advisory codes become six (`non_finite_nulled`); `dates_normalised` widens to cover UTC conversion |
| **PRD** §8 | `derive`/`bin` added, `pivot`/`window` cut; "compiles to SQL" is P1; "file-like only" means "no foreign dialect" |

`RawSqlRejectedError.reason` is `Literal["multi_statement", "not_read_only", "unparseable",
"empty", "non_file_source", "foreign_relation"]` — plain strings at runtime, matching the
house style ADR-0005 already set with `SchemaDriftError.stage` and `DriftedField.kind`.
Adding a seventh value in P1 is a widening, not a break.

`dates_normalised` counts **columns**, named in the message:
`"3 columns normalised to ISO-8601 (UTC): ts, created_at, closed_at"`. Columns rather than
values, because the caller's question is which of their fields we touched and a value count
over a million rows is noise. A `TIMESTAMPTZ` column counts unconditionally, even when its
values were already UTC — that is a data accident, and the caller needs to know the column
is UTC by policy in order to reason about the next refresh. `Advisory` stays `{code,
message}`; widening it for one column list is a bigger change than this deserves.

### `raw_sql`'s scope is "no foreign dialect", not "must be a file"

PRD §8 scopes `raw_sql` to *"file-like sources (DuckDB) in v1"*, and justifies it explicitly
by **dialect**: read-only *"is not reliably checkable across warehouse dialects"*. Flavour 3
— Arrow tables, `list[dict]` — has no foreign dialect. It is the same DuckDB, the same
parser, the same three locks.

So **`raw_sql` is allowed on flavours 1 and 3**. Read literally, the original rule would
reject `raw_sql` against a Polars DataFrame for no reason anyone can state.

A consequence worth recording so nobody writes a test that cannot fail: ADR-0005's
`RawSqlRejectedError` case for *"a non-file source"* is **unreachable at P0** — flavour 2
does not exist until P1 (ADR-0005 Decision 4) — so `reason="non_file_source"` stays in the
union and its P0 test is a placeholder.

## Consequences

**What we gain.** A menu that can actually draw the charts people ask for, which the
original list could not. One canonical order, so one compiler, one generated form, and a
transform diff that is a diff of named keys. An escape hatch that is genuinely safe to run
on our own infrastructure, held by three locks that fail independently. And a transform
whose output is a function of the data alone — no host setting, no session timezone, no tie
ordering left to chance.

**What we accept.** `pivot` and `window` are missing from v1, so real charts will take the
escape hatch, and the escape hatch costs a full materialisation of the source. Three-valued
logic's asymmetry stays visible to users. `TIMESTAMPTZ` buckets in UTC, which will surprise
someone with a daily chart. One spec key, `having`, compiles to two different SQL
constructs. And `bind` grew a keyword argument two days after its signature was frozen.

**What this obliges us to build.** The `Expr` AST as a Pydantic discriminated union with a
stage-scoped validator. A compiler to DuckDB's relational API that attaches node paths to
engine errors. Three `raw_sql` locks, of which Lock 2 needs the `duckdb_functions()`
table-function set captured at the pin. The two-connection materialisation path with
`memory_limit` on both. A serialisation pass covering ISO-8601, UTC and non-finite floats,
feeding two advisory codes. And a test that the slot vocabulary is closed — an ignored
unknown slot is the failure mode Decision 13 exists to prevent.

**What this cancels.** `pivot` and `window` as v1 obligations. PRD §8's "compiles to the
target engine's SQL" as a v1 statement. And any reading of "file-like sources only" that
turns on the source being a file.

## What this feeds

`raw_sql_used` is now evidence two other open tickets depend on, and the dependency is
recorded here rather than as a blocking edge, because it runs the wrong way: neither ticket
is blocked by *this ticket closing*. Both are blocked by **operating experience**, which
arrives only once the transform ships and people take the escape hatch.

- [#7](https://github.com/thearcscode/chartagent/issues/7) — the pressure-test corpus is
  what a menu-coverage rate is measured *over*; the `raw_sql_used` population is its
  taxonomy's first input.
- [#10](https://github.com/thearcscode/chartagent/issues/10) — a chart that needed
  `raw_sql` is a chart the declarative menu did not cover, which is the deterministic-rail
  share its <60% gate measures.

## Alternatives rejected

**An ordered list of ops instead of fixed slots.** Rejected. Strictly more expressive, and
it costs the canonical form the patch-mode diff depends on (ADR-0002 Decision 5), the single
SQL skeleton, and #27's generated form. `raw_sql` covers what the eight slots cannot.

**An arbitrary expression string in `derive`.** Rejected. It is `raw_sql` with none of
`raw_sql`'s validation and none of its visibility — no `raw_sql_used` advisory, no three
locks, and the deterministic-rail share silently overstated.

**A generic `fn(name, args)` node in the `Expr` AST.** Rejected. It reopens 2948 DuckDB
functions and makes the closed set decorative.

**Compiling `ne`/`not` to null-preserving forms.** Rejected. More intuitive per-predicate,
but it invents a dialect: the same `filter` would then mean something different from the
`raw_sql` a user writes to replace it, and a faithful escape hatch is worth more than a
nicer default.

**A full static type checker over the `Expr` AST.** Rejected. A second binder that disagrees
with DuckDB's at the edges rejects specs DuckDB would have run — the translation layer
ADR-0002 exists to refuse.

**Escaping identifiers instead of allowlisting them.** Rejected, and it does not work
anyway: measured, a column name containing a double quote binds to the wrong name even with
correct doubling.

**A third-party SQL parser (`sqlglot`) for the read-only check.** Rejected. A second SQL
grammar that can disagree with the executing one is a vulnerability, not a defence.

**A read-only DuckDB connection.** Not rejected — unavailable. In-memory databases cannot be
opened read-only, and in-memory is what `bind` uses.

**Narrowing Lock 3 so our own reads pass through.** Rejected. It removes the materialisation
cost and reopens exactly the hole the lock was taken for.

**Refusing to persist `raw_sql` in Studio.** Rejected. It contradicts #27's editor, and it
solves a server-side execution problem by deleting a product feature.

**A second post-`derive` filter slot.** Rejected. Two slots differing only by position, for
no expressive gain over defining `having` by stage.

**A `transform`-specific version field.** Rejected. A compatibility matrix, where a closed
vocabulary with hard errors on unknown slots is stronger.

**A module-level `configure()` or an environment variable for the timeout.** Rejected.
Process-global under concurrency, or invisible and untestable per call.

**Raising on non-finite floats.** Rejected. One bad row would refuse a whole chart, and a
non-finite value is a data condition, not a spec defect.

## Evidence

Measured 2026-08-26 against **DuckDB 1.5.5** (`uv run --with duckdb --with pyarrow`), the
engine `bind` runs in-process per ADR-0005 Decision 6. Every claim above marked *measured*
comes from these probes:

- `extract_statements` statement counts and types across nine queries, including the
  CTE-wrapped `INSERT` and the trailing-comment split (Decision 7, Lock 1).
- `duckdb.connect(':memory:', read_only=True)` → *"Cannot launch in-memory database in
  read-only mode"* (Decision 7).
- `enable_external_access=False` + `lock_configuration=true` refusing `read_csv`,
  `COPY … TO`, `ATTACH` and its own unlocking (Decision 7, Lock 3).
- `json_serialize_sql` parse trees for four evasion attempts, plus `duckdb_functions()`
  reporting 127 table functions of 2948 (Decision 7, Lock 2).
- `ColumnExpression` with hostile identifiers — parser error on a bare name, wrong binding
  on an embedded double quote (Decision 4).
- `current_setting('TimeZone')` = `Asia/Kolkata`; `default_null_order` / `default_order` as
  settings (Decisions 9 and 11).
- `date_trunc` returning `TIMESTAMP` from a `DATE` input (Decision 10).
- `SELECT 1/0` → `inf`; `concat('a', NULL)` → `'a'` versus `'a' || NULL` → `NULL`
  (Decisions 3 and 9).
- `HAVING` over a bare column without `GROUP BY` → `BinderException`; the relational-API
  project-then-filter equivalent returning correct rows (Decision 6).
- `DATE '2020-01-05'` compared against `'2020-01-01'`, `'01/05/2020'` and `'Jan 2020'`
  (Decision 3).

These were exploratory probes, not committed fixtures. The ones that guard a security
boundary — Lock 1's statement table, Lock 2's evasion set, Lock 3's refusals — should become
tests when the compiler is built, because each encodes an assumption about the pinned engine
that a bump could move.

## Related

- ADR-0001 — ISO-8601 before Flint sees data (Decision 3, amended here); the envelope.
- ADR-0002 — Decision 3 (no stored `data`, the reason this ADR matters), Decision 4
  (encodings reference transform output and never aggregate), Decision 5 (canonical JSON as
  the diff unit), Decision 6 (pinned `baseSize`, reproducibility's other half).
- ADR-0005 — `bind`'s signature, the error taxonomy, the advisory codes, and the schema-drift
  split this ADR amends in four places.
- ADR-0006 — Studio's server binds, which is why Lock 3 exists; Decision 9's four caps, one
  of which Decision 12 here makes reachable.
- [#27](https://github.com/thearcscode/chartagent/issues/27) — the generated form that
  Decision 1's fixed slots and Decision 4's field paths are for.
- [#7](https://github.com/thearcscode/chartagent/issues/7),
  [#10](https://github.com/thearcscode/chartagent/issues/10) — see *What this feeds*.
- `prototypes/chartspec-v1/` — retired by ADR-0002, but its two-phase-validation finding is
  what Decision 4's "grammatically valid, still unrenderable" split descends from.
- Not decided here: `window` and `pivot` schemas (P1, on the evidence above); connection-like
  pushdown and its dialect compilation (P1, ADR-0005 Decision 4); a per-spec viewer
  timezone; `escape`'s placement, still open from ADR-0002 *Related*.
