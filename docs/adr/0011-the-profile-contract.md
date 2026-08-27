# 11. `profile.json` is an internal, machine-first artifact of the source

- **Status:** Accepted
- **Date:** 2026-08-27
- **Settled on:** [#5](https://github.com/thearcscode/chartagent/issues/5)
- **Builds on:** ADR-0002 (the input frame *is* the spec), ADR-0005 (`bind` is the public
  seam; one verb at P0), ADR-0007 (what Studio stores), ADR-0008 (the transform menu; the
  identifier allowlist; the serialisation rules), ADR-0010 (the seven buckets)
- **Amends:** ADR-0010 Decision 4 (the reported-head table), and PRD §7.3, §7.4 and P0.2 —
  recorded as dated errata in place and listed under *What this amends*

## Context

PRD §7.3 gives the profiler one sentence: *"emits compact `profile.json`: schema, dtypes,
cardinality, null rates, min/max/percentiles, stratified sample rows"*, with P0.2 asserting
that a 10 GB Parquet profiles under 500 MB of memory into an artifact below 10 KB. The
profiler is P1 — the same phase as the planner it feeds — and nothing downstream of it can
be specified until the shape of what it emits is fixed.

Two of that sentence's clauses did not survive contact with a measurement, and one of the
ticket's own premises did not survive contact with ADR-0008.

### The premise that was already void

The ticket asks the profile to tell the transform layer *"which columns need ISO-8601 date
normalisation (ADR-0001 Decision 3)"*. ADR-0008 Decision 9 had already moved that: dates are
formatted at **serialisation**, keyed on the column's DuckDB reported type, and `bind`
reads that schema itself for ADR-0008 Decision 4's identifier allowlist. No profile is
consulted, and none could be — `bind` is P0 and the profiler is P1.

What survives is the half the ticket mentioned second, and ADR-0008 made it *sharper*
rather than smaller. Because the transform layer now refuses to sniff a string —
*"a `VARCHAR` is never inspected, never guessed at, never rewritten"* — **the profiler is
the only place in the system where a "this string looks temporal" signal can live**.

### The failure this exists to catch

A profile is not read by a person. It is read by a planner, which will believe it.

Measured (`prototypes/data-profile/sample_bias.py`, DuckDB 1.5.5), over 40 trials on a
5,000,000-row table with a monotonic id:

| method | mean position | quintile distribution |
| --- | --- | --- |
| `USING SAMPLE 10 ROWS` (the default) | **9.3%** of N | **85%** / 15% / 0% / 0% / 0% |
| `USING SAMPLE reservoir(10 ROWS)` | 9.9% | 82% / 18% / 0% / 0% / 0% |
| `USING SAMPLE 1% (system)` | 3.8% | 98% / 2% / 0% / 0% / 0% |
| `ORDER BY random() LIMIT 10` | **50.3%** | 22% / 19% / 21% / 18% / 21% |

DuckDB's obvious sampling API is not a sample of the table. It is a sample of the top of the
file, and on time-ordered data — which is most data anyone charts — it hands the planner the
oldest week of a two-year table under the heading `sample_rows`. Nothing about the resulting
chart looks wrong. That is the whole class of failure this contract is shaped against, and
it is the same class as ADR-0010's retype: an artifact that is quietly unrepresentative
produces a chart that is quietly incorrect.

There is no cheap way out. A cluster sample — k random offsets, m rows each — is positionally
honest but **slower** than the uniform sample, 17–34 ms against 6.3 ms, because `OFFSET`
still scans (`cheap_spread_sample.py`). The honest option is also the cheapest honest option.

## Decision

### 1. Internal at P1, with the second-profiler hazard closed by decision

`Profile` and its models are **not in `chartagent.__all__`**. The artifact is a VFS file the
planner reads (PRD §7.6) and that our own Phase-2 checks read. Its shape may change between
minor versions.

A public `profile(data)` verb was rejected on ADR-0010 Decision 5's precedent, which refused
`source_schema(spec, data)` for being *"the second verb that reads a source"* against
ADR-0005 Decision 1's one-verb surface. That freeze is the **P0 seam**; P1's agentic
entrypoint may read a source internally without minting a second public verb to do it.

But forever-internal leaves Studio no path to column statistics and invites it to grow its
own profiler — the `canonical_json` two-implementations hazard (ADR-0005 Decision 8) one
level down, where two plausible bucketings of the same source drift in silence. So the
commitment is recorded now, while the type is still private:

> **If Studio needs column statistics, this object is promoted. Studio does not grow a
> profiler.**

Studio v0 needs none of it: `data_sources.schema_snapshot` (ADR-0007 Decision 15) already
carries names and types at registration. **Statistics** are what must not be computed twice.

### 2. Four top-level keys, and three deliberate absences

```json
{ "row_count": …, "columns": [ … ], "sample_rows": [ … ], "truncation": { … } }
```

`truncation` is present **only when a rung fired** — never a zeroed object.

**No source identity.** A path or an `s3://` URL is caller data that would flow straight into
a planner prompt, widening the untrusted surface for a fact the planner cannot use: where
bytes came from does not change what chart they support. Studio already holds it on
`data_sources`.

**No `generated_at` or `elapsed`.** Non-deterministic bytes in an artifact that Phase-2
checks read and that may well be hashed. Timing belongs on the P1 span, not in the payload.

**No `profile_version`.** A version field is a promise, and Decision 1 deliberately withheld
the promise. Promotion is the coherent moment to add one.

### 3. A column is a union discriminated on `bucket`, and `other` costs no scan

`NumberColumn` · `TemporalColumn` · `StringColumn` · `BooleanColumn` · `OtherColumn` — five
variants for seven buckets. `TemporalColumn` carries `date | timestamp | timestamptz`: they
chart differently, which is why ADR-0010 split them, but they share a stats shape, so a
model each would buy nothing.

A flat model with every statistic optional was rejected because it makes every consumer
defend against fields that were never going to exist. **`columns` is a list, never a
name-keyed map** — a map collapses duplicate names, and Decision 12 has more to say about it.

`OtherColumn` carries `name`, `bucket` and `reported_type` and **nothing else**. Nothing in
`other` was chartable in the first place (ADR-0010 Decision 4), so counting its nulls spends
a column read on a number no one reads. The consequence is worth stating: a source of 300
`BLOB` columns profiles for the price of a footer read.

### 4. Cardinality is exact below a cap and saturates above it

`distinct: 1001, saturated: true` above the cap; the exact count below it. **`N = 1001`,
frozen here, and every Phase-2 cardinality cap must stay strictly below it.**

Approximation was rejected on measurement (`sampling_and_stats.py`).
`approx_count_distinct` returned **36 for 39** and **300,210 for 250,000** — wrong in both
directions — to save 15 ms on 5M rows. The low-end error is the disqualifying one: a
Phase-2 cap of 50 would be *passed* by a column with 54 real categories. `SUMMARIZE`'s
`approx_unique` is the same number and inherits the same defect.

Exact-always was rejected too: it spends a full-column `DISTINCT` on a 10 GB source to
produce a number nobody reads. The rule is ADR-0010 Decision 3's, one level up —
**precision where the decision changes, saturation where it does not.** The decision
cardinality feeds is *can this be a categorical axis?*, and above ~1000 the answer is no
whether the true value is 250,000 or 300,210.

`row_count` stays exact: `count(*)` is a footer read on Parquet (0.2 ms measured).

### 5. A hard budget, a global ladder, and what the rungs are

**10 KB is a prompt budget wearing a byte count.** A 400-column profile poisons a planner's
context whether or not it fits. So the cap holds, and the profiler degrades to hold it:

1. truncate `reported_type` parameters to the head (budget: 120 characters)
2. drop `sample_rows`
3. shrink, then drop, top-value enumerations
4. drop percentiles and the prompt-facing remainder — **keeping** `name`, `bucket`,
   `reported_type` head, `null_rate`, `distinct`, `saturated`, which are what Phase-2 reads
5. cap `columns` in `DESCRIBE` order and emit `omitted_count`

**Rungs fire for the whole profile or not at all.** This is a constraint on the ladder, not
a property of it: a per-column rung — *"drop stats past column 40"* — makes `stats: null`
undecodable, and decodability is the entire reason the column models are a union. Because
rungs are global, optionality has exactly **two** readings:

- **emptiness** — always `null_rate == 1.0` or `row_count == 0`, and still true after rung 4
- **degradation** — the `truncation.rungs` list says which rung took it

Rung 5 needed a correction to the ticket's instinct that a column must never be dropped
without a name-and-bucket stub. Measured, **400 stubs are 15.6 KB** — the stub floor misses
the budget on its own. So the terminal rung is a column cap plus a count, not a stub for
every column. Force-including columns named in the user's instruction is a caller policy
and is deliberately not a field here.

Measured on progressively wider sources of the same data: 9 columns 5,405 bytes and no rung;
40 columns 9,063 bytes at rungs 1–3; 120 columns 10,161 bytes at rungs 1–5 with
`omitted_count: 36`; 400 columns 10,162 bytes with `omitted_count: 316`.

### 6. The sample is uniform, and it is the only honest option

`ORDER BY random() LIMIT k` semantics, `k = 10`, `sample_rows` an array of objects.

A declared-biased sample was rejected as the failure in the *Context* above, wearing
documentation. Tiering by source flavour — uniform locally, biased over `s3://` — was
rejected because it makes the same bytes yield a different plan depending on where they
live, with nothing in the artifact to explain why. Dropping the sample entirely is already
rung 2, and cannot be the default: Decision 9's parse rate has no inputs without it.

**The implementation collects a reservoir of `k` rows during the statistics pass**, uniform
and in O(k) memory, rather than issuing a second full scan. The artifact is identical either
way; the prototype issues it separately and says so.

### 7. Percentiles are p01/p25/p50/p75/p99, approximate, with exact extrema

Approximate quantiles, exact `min`/`max`, the same set on temporal columns, and none at all
on `boolean` or `other`.

The reason is **memory, not milliseconds**. Measured, `approx_quantile` is 13.7 ms against
`quantile_cont`'s 28.6 ms and the values agree to a rounding error (49999 vs 49999.99) — a
weak argument. The real one is that `quantile_cont` materialises while `approx_quantile`
streams in bounded space, and P0.2's binding constraint is **< 500 MB on 10 GB**. Extrema
stay exact because they set axis bounds and cost 0.2 ms from the Parquet footer.

`SUMMARIZE`'s free q25/q50/q75 was rejected because every decision a percentile feeds is a
tail question: outlier presence, whether a zero baseline distorts, whether a log scale is
warranted. Temporal columns get the same set because q01/q99 over a timestamp is how a
planner sees that 99% of a five-year file lands in its last month — a chart-changing fact
that nothing else in the profile reports. Temporal extrema serialise ISO-8601, UTC with a
trailing `Z` for `timestamptz`, per ADR-0008 Decision 9.

### 8. Top values are `{value, count}`, ten for strings, all for booleans

`K = 10` for `string`, every value for `boolean` (at most three, including null), nothing
for `number`, temporal or `other`. String enumeration **excludes null** — `null_rate`
already carries it. Low-cardinality numbers are served by `distinct` plus the sample, not by
a second enumeration.

The count is the load-bearing half. A column with 39 categories where one holds 90% of rows
is a different chart from 39 even ones, and cardinality alone cannot tell them apart.

**`top_k_coverage`** — the fraction of non-null rows the enumerated values account for — is
skew in one number, and it is the only skew signal that survives rung 3.

### 9. `iso8601_parse_rate`: the evidence, never the conclusion

For `string` columns whose reported head is `VARCHAR`, the profile reports the fraction of
**sampled** values that parse as a timestamp. Never over the whole column, never a type
name, and never a second rate for slash-dates — which would reintroduce `03/04/2020` as a
temptation in the one place ADR-0008 Decision 9 removed it.

Emitting a candidate `semantic_type` was rejected: a named type is what gets copied into
Flint's `semantic_types` unexamined, which is ADR-0008's failure one layer up with a
confidence number as cover. Reporting nothing was rejected because a review check has
nothing to read once rung 2 drops the sample.

`UUID` and `ENUM` are not sniffed. This creates the **one documented third case** of
optionality, against Decision 5's two: `iso8601_parse_rate` is absent when the head is not
`VARCHAR`. It stays decodable because degradation drops the enclosing `stats` object
wholesale — so **inside a present `StringStats`, `null` can only mean "the head was not
`VARCHAR`"**. Recorded as an exception rather than left to be discovered.

### 10. Taint is structural, expressed as a manifest, enforced by an exhaustiveness test

One sentence governs it:

> **A statistic computed *over* untrusted values is ours. A value *copied from* untrusted
> data is not.**

So `iso8601_parse_rate` and `top_k_coverage` are ours despite every input to them being
attacker-influenced, while `columns[].name`, `columns[].reported_type`, string `min`/`max`,
`top[].value`, and `sample_rows` keys *and* values are not.

`reported_type` is untrusted deliberately: it is a schema string, and `STRUCT(…)` parameters
embed attacker-controlled field names. Numeric and temporal extrema and percentiles are
ours, being JSON numbers and computed ISO-8601 strings.

Contiguity is impossible — `columns[].name` is untrusted while `columns[].null_rate` sits
beside it — and buying contiguity by separating a column's name from its statistics would
destroy the adjacency a planner needs. So the classification is a **manifest the module
exports and the prompt renderer consumes**, and it is *not* a field in `profile.json`; a
per-field mark in the artifact is the taint-tracking system Decision 10 exists to avoid.

**The mechanism is the test, not the manifest.** Every model declares `TRUSTED` and
`UNTRUSTED`, and one test asserts each model's fields are exactly their union, with no
overlap. A new field classified in neither fails CI rather than review.

### 11. The profiler never raises on data shape

It raises on I/O failure and on nothing else.

Zero rows profiles to `row_count: 0`, columns with buckets, no statistics, an empty sample —
which is Decision 5's emptiness test, unchanged. An all-`other` source profiles successfully
and tells the planner that nothing here is chartable, which is a far better outcome than an
exception, because the planner can *say so* to the user. A constant column is not a special
case: `distinct: 1`, `min == max`.

### 12. The buckets are engine-neutral; ADR-0010's table is one engine's mapping

The seven buckets were drawn where **the chart changes**, which is a statement about charts
and not about DuckDB. ADR-0010 Decision 4's reported-head table is therefore *a* mapping and
not the vocabulary — it currently reads like the definition, and this ADR says otherwise.

This matters at P1, because PRD §7.4's flavour-2 connection-like sources land in the same
phase as the profiler and push down to *their* engine: Snowflake reports `NUMBER(38,0)`,
`TIMESTAMP_NTZ`, `VARIANT`. Per-engine head tables land with their engines. Nothing widens,
because ADR-0009's expose-don't-enforce shape was applied to `reported_type` in Decision 3:
it is an **opaque `str`, never a closed `Literal` of DuckDB type names**, and no
deterministic check branches on it. Phase-2 and routing read `bucket`; the planner reading
the string is the reason it exists. One test binds this bucketing to ADR-0010 Decision 4.

## What this amends

### ADR-0010 Decision 4 — the head rule misses DuckDB's postfix list syntax

**Erratum, 2026-08-27 (#5, ADR-0011).** Decision 4's table lists `LIST` and `ARRAY` as
reported type heads under `other`, and instructs implementers to *"match the constructor
head before its parameters"*. Measured (`prototypes/data-profile/reported_composites.py`,
DuckDB 1.5.5), **DuckDB never reports either string.** It reports lists and arrays in
**postfix** form:

| expression | reported type | prefix head | bucket under D4 as written |
| --- | --- | --- | --- |
| `[1,2,3]` | `INTEGER[]` | `INTEGER` | **`number`** |
| `[1,2,3]::BIGINT[]` | `BIGINT[]` | `BIGINT` | **`number`** |
| `[1,2,3]::INTEGER[3]` | `INTEGER[3]` | `INTEGER` | **`number`** |
| `[['a']]::VARCHAR[][]` | `VARCHAR[][]` | `VARCHAR` | **`string`** |
| `[{'a': 1}]` | `STRUCT(a INTEGER)[]` | `STRUCT` | `other` (by luck) |

`STRUCT(…)`, `MAP(…)` and `UNION(…)` are prefix-formed and bucket correctly; only the
list/array family is affected, and `STRUCT(…)[]` is right for the wrong reason.

The consequence lands inside ADR-0010's own failure mode. A `BIGINT[]` column records
`number` in a stored baseline, so a retype to plain `BIGINT` — someone unnests the column —
reads `number` → `number` and **raises no `SchemaDriftError`**, while ADR-0008 Decision 4's
identifier allowlist stays quiet because the name never changed. That is exactly the
silent-wrong-chart class ADR-0010 exists to catch, arriving through its own bucket table.

**The rule is amended to test the postfix suffix first: any reported type ending in `]` is
`other`, before any prefix head is considered.** `LIST` and `ARRAY` are struck from the
table as heads DuckDB does not emit. No implementation is affected — ADR-0010 landed
2026-08-27 against a repo with no `pyproject.toml`, so the ADR text was the only artifact.

### PRD §7.3 — "stratified sample rows" is not deliverable at profile time

**Erratum, 2026-08-27 (#5, ADR-0011).** Stratification requires naming the stratum column.
At profiling time the planner has not chosen a target, so there is no column to stratify by;
measured, the query is expressible only once one is named. The clause is replaced by a
**uniform** sample of `k = 10` rows, per Decision 6. Same class as ADR-0004's finding that
ADR-0001's *"fails on any unexplained diff"* was unbuildable as written.

### PRD §7.4 and P0.2 — "transferring MBs" is a claim about schema reads

**Erratum, 2026-08-27 (#5, ADR-0011).** §7.4 says a 50 GB file *"profiles by transferring
MBs"*. Measured, only the footer is free: `count(*)` and `min`/`max` are 0.2 ms and read no
column data. **Null rate, distinct, top-K and quantiles each transfer the column.**

P0.2's two criteria are therefore not one criterion. *Peak memory < 500 MB* holds and is why
Decision 7 takes streaming quantiles and Decision 6 takes a reservoir. *Transferring MBs*
holds for a schema read and for nothing else. **"No full-data load" means we do not
materialise the table, not that we do not scan columns.**

P0.2's *"`profile.json` < 10 KB"* is likewise a claim about its own tall-narrow fixture. The
artifact grows with **width**, not height, and Decision 5's ladder is what makes the cap
hold on a wide source.

## Consequences

- The planner gets one artifact, of the **source**. Encodings bind to transform *output*
  (ADR-0002 Decision 4), so the planner infers output from the source profile plus the
  transform it is authoring. **Phase-2 checks on `derive` and `bin` outputs cannot run
  against a source-only profile**; group-key cardinality can. Those derived checks wait for
  an output-side profile, which belongs to the review gate — it already re-runs the
  transform for the data-truthfulness check.
- Profiling runs **in-process**, like `bind`. PRD §7.5's rule is about *model-authored*
  code; the profiler is ours, and it opens the same file with the same DuckDB that ADR-0005
  Decision 6 already accepted running in-process at P0. Sandboxing one and not the other
  does not contain a hostile Parquet. **That vector is accepted and unsolved, not handled by
  §7.5** — written down rather than left to be inferred. Profiling next to the bytes when a
  remote sandbox owns them is a locality question for [#6](https://github.com/thearcscode/chartagent/issues/6);
  the contract is unchanged either way.
- **The profile reports the engine's disambiguated names.** Measured, a Parquet holding two
  `id` columns is reported by `DESCRIBE` as `id` and `id_1`, while a cursor description for
  `SELECT 1 AS id, 2 AS id` keeps both as `id` — the two ways of reading a schema disagree.
  The profiler reads it **the way ADR-0008 Decision 4's identifier allowlist does**, so they
  cannot disagree about what columns exist. `columns` stays a list regardless, because
  Decision 12 admits engines that do not rename.
- Frozen here, and each one changes the artifact if moved: `k = 10`, `N = 1001`,
  `TOP_K = 10`, a 120-character `reported_type` budget, a 10 KB cap, and rung 5 keeping
  `DESCRIBE` order.

## Alternatives rejected

- **A public `profile()` verb** — Decision 1. ADR-0010 Decision 5's precedent, applied to
  the verb that argument was really about.
- **Prompt-shaped output** — a pre-rendered summary string, prose fields. The map's own fog
  already commits our code to reading this artifact (*"Phase-2 validation thresholds… against
  a data profile"*), so a purely prompt-facing shape was never available. Prompt rendering
  is a separate serialisation of the same object, and where the two jobs conflict the
  machine field wins.
- **Two profiles, source and transform output** — a second contract and a second round trip,
  to catch what the review gate already pays a transform re-run to catch.
- **Per-field taint marks in the artifact** — Decision 10. A taint-tracking system to keep
  correct forever, where a manifest plus an exhaustiveness test fails loudly instead.
- **Whole-artifact tainting** — throws away that `null_rate: 0.03` is ours, and would
  swallow the two fields Decision 10 works hardest to keep untainted.
- **DuckDB logical types as the bucket vocabulary** — rejected in ADR-0010 Decision 3 and
  not reopened. What this ADR adds is that the *reported* string is worth carrying beside
  the bucket, exposed and never enforced.

## Evidence

All under `prototypes/data-profile/`, DuckDB 1.5.5 on macOS, 2026-08-27:
`sample_bias.py` (sampling is positionally biased), `cheap_spread_sample.py` (no cheap
middle; only the footer is free), `sampling_and_stats.py` (cardinality, `SUMMARIZE`, byte
budgets), `reported_composites.py` (postfix list reporting), `dup_names.py` (duplicate-name
disambiguation), `build_profile.py` + `profile.sample.json` (the artifact and the ladder).

## Related

- ADR-0005 — one verb at P0; the seam this deliberately does not widen.
- ADR-0008 — Decision 9's refusal to sniff a string, which is why Decision 9 here exists.
- ADR-0010 — the seven buckets, amended above.
- [#5](https://github.com/thearcscode/chartagent/issues/5) — the ticket.
- Open: the **planner output contract**, which this unblocks; **Phase-2 validation
  thresholds**, which read `bucket`, `distinct` and `saturated`.
