# `profile.json` — the profiler's output contract

Prototype for [#5](https://github.com/thearcscode/chartagent/issues/5), settled as
**ADR-0011**. Nothing here ships: the profiler is P1 and this directory is the
artifact the decision was made against.

| file | what it is |
| --- | --- |
| `profile_models.py` | the contract, as Pydantic models, plus the taint manifest and its exhaustiveness test |
| `build_profile.py` | a working profiler over any DuckDB-readable source; writes `profile.sample.json` |
| `profile.sample.json` | the artifact, from a 400,000-row / 9-column parquet |
| `sampling_and_stats.py` | cardinality exact-vs-approximate, `SUMMARIZE`, sampling cost, byte budgets |
| `sample_bias.py` | **`USING SAMPLE n ROWS` is not a sample of the table** |
| `cheap_spread_sample.py` | there is no cheap middle: cluster sampling is slower than the honest sample |
| `reported_composites.py` | **DuckDB reports lists postfix**, which defeats ADR-0010 D4's head rule |
| `dup_names.py` | `DESCRIBE` renames a parquet's duplicate `id` to `id_1`; a cursor description does not |

Run any of them with `uv run --with duckdb --with pydantic --with pytz python <file>`.

## The four measurements that decided it

**1. `USING SAMPLE n ROWS` draws 85–90% of its rows from the first quintile.**
Mean position 7.6–9.9% of a 5M-row table over 40 trials. `ORDER BY random()
LIMIT n` is uniform (20/18/24/18/20) and *cheaper than every honest
alternative* — 6.3 ms against 17–34 ms for a cluster sample, because `OFFSET`
still scans. On time-ordered data the obvious API returns the oldest week and
looks fine doing it.

**2. `approx_count_distinct` is wrong in both directions.** 39 → **36**, and
250,000 → **300,210**, to save 15 ms on 5M rows. Under-counting at the low end
is a false *pass* on a Phase-2 cardinality cap. `SUMMARIZE`'s `approx_unique` is
the same number.

**3. DuckDB reports list types postfix.** `BIGINT[]`, `INTEGER[3]`,
`VARCHAR[][]` — never `LIST(…)` or `ARRAY[n]`, both of which ADR-0010 D4 lists
as reported heads. A prefix-head rule buckets `BIGINT[]` as `number`. Erratum
recorded in ADR-0011.

**4. Only the footer is free.** `count(*)` and `min`/`max` are 0.2 ms. Null
rate, distinct, top-K and quantiles each read the column. PRD §7.4's *"a 50 GB
file profiles by transferring MBs"* is true of a schema read and of nothing else.

## What the sample artifact shows

7,487 bytes — 73% of the 10 KB budget — for 9 columns, no rung fired:

- `legacy_date` is a `VARCHAR` carrying `iso8601_parse_rate: 1.0`. That is the
  signal the transform layer refuses to produce (ADR-0008 D9 will not sniff a
  string), reported as **evidence and never as a type name**.
- `tags` is `BIGINT[]` → `other`, with no statistics and no scan.
- `order_id` is `distinct: 1001, saturated: true` — exact below the cap,
  saturating above it.
- `region` is 4 distinct with `top_k_coverage: 1.0` and counts 240000 / 100000 /
  48000 / 12000, so the skew is legible without a second field.

The ladder, on progressively wider sources of the same data:

| columns | bytes | rungs fired |
| --- | --- | --- |
| 9 | 5,404 | none |
| 40 | 9,063 | 1–3 |
| 120 | 10,161 | 1–5, `omitted_count: 36` |
| 400 | 10,162 | 1–5, `omitted_count: 316` |
