"""Build a real `profile.json` from a DuckDB-readable source. Prototype for #5.

This is the DuckDB mapping of an engine-neutral contract: the seven buckets are
a statement about charts, and ADR-0010 D4's head table is ONE engine's mapping,
not the vocabulary (Decision 10). Per-engine head tables land with their engines.

Run: uv run --with duckdb --with pydantic --with pytz python build_profile.py
"""

import decimal
import json
import os
import re
import tempfile
from typing import Any

import duckdb

from profile_models import (
    BUDGET_BYTES, REPORTED_TYPE_BUDGET, SAMPLE_ROWS, SATURATION_CAP, TOP_K,
    BooleanColumn, NumberColumn, NumberStats, OtherColumn, Profile, StringColumn,
    StringStats, TemporalColumn, TemporalStats, TopValue, Truncation,
    test_every_field_is_classified, untrusted_paths,
)

# ADR-0010 D4's table, keyed on the reported constructor head. One engine's mapping.
HEADS: dict[str, str] = {
    **{h: "number" for h in (
        "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT",
        "UINTEGER", "UBIGINT", "UHUGEINT", "FLOAT", "DOUBLE", "DECIMAL", "VARINT", "BIGNUM")},
    **{h: "string" for h in ("VARCHAR", "ENUM", "UUID")},
    "BOOLEAN": "boolean",
    "DATE": "date",
    **{h: "timestamp" for h in ("TIMESTAMP", "TIMESTAMP_S", "TIMESTAMP_MS", "TIMESTAMP_NS")},
    "TIMESTAMP WITH TIME ZONE": "timestamptz",
}
TEMPORAL = {"date", "timestamp", "timestamptz"}


def head_of(reported: str) -> str:
    """Match the constructor head before its parameters, never the whole string."""
    return re.split(r"[(\[]", reported, maxsplit=1)[0].strip().upper()


def bucket_of(reported: str) -> str:
    """Postfix first. ADR-0010 D4 lists LIST/ARRAY as reported heads and DuckDB
    never emits either: measured, it reports `BIGINT[]`, `INTEGER[3]`,
    `VARCHAR[][]`. A prefix-head rule buckets `BIGINT[]` as `number`, so an
    unnest to plain `BIGINT` reads number -> number and raises no drift.
    See reported_composites.py; recorded as an erratum on ADR-0010 D4.
    """
    if reported.rstrip().endswith("]"):
        return "other"
    return HEADS.get(head_of(reported), "other")


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def profile(con: duckdb.DuckDBPyConnection, relation: str) -> Profile:
    con.execute("SET TimeZone='UTC'")           # ADR-0008 D11: pinned, never inherited
    # Read the schema exactly the way ADR-0008 D4's identifier allowlist does.
    # Measured: DESCRIBE renames a parquet's duplicate `id` to `id_1`, while a
    # cursor description keeps both as `id` -- so the two disagree, and the
    # profile must not be the one that disagrees. See dup_names.py.
    schema = con.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    row_count = con.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]

    columns: list[Any] = []
    scanned: list[str] = []                      # names we will sample from

    for name, reported, *_ in schema:
        b = bucket_of(reported)
        if b == "other":
            # No statistics at all, and therefore no scan at all.
            columns.append(OtherColumn(name=name, reported_type=reported))
            continue
        scanned.append(name)
        col = _q(name)
        null_rate = 0.0 if row_count == 0 else con.execute(
            f"SELECT count(*) FILTER (WHERE {col} IS NULL)::DOUBLE / count(*) FROM {relation}"
        ).fetchone()[0]
        # Exact below the cap, saturating above it: precision where the decision
        # changes (can this be a categorical axis?), saturation where it does not.
        distinct = con.execute(
            f"SELECT count(*) FROM (SELECT DISTINCT {col} FROM {relation} "
            f"WHERE {col} IS NOT NULL LIMIT {SATURATION_CAP})"
        ).fetchone()[0]
        saturated = distinct >= SATURATION_CAP
        empty = row_count == 0 or null_rate == 1.0
        common = dict(name=name, reported_type=reported, null_rate=null_rate,
                      distinct=distinct, saturated=saturated)

        if b == "number":
            stats = None if empty else NumberStats(**dict(zip(
                ("min", "max", "p01", "p25", "p50", "p75", "p99"),
                con.execute(
                    f"SELECT min({col}), max({col}), "
                    + ", ".join(f"approx_quantile({col}, {p})" for p in (0.01, 0.25, 0.5, 0.75, 0.99))
                    + f" FROM {relation}").fetchone())))
            columns.append(NumberColumn(**common, stats=stats))

        elif b in TEMPORAL:
            stats = None if empty else TemporalStats(**dict(zip(
                ("min", "max", "p01", "p25", "p50", "p75", "p99"),
                [_iso(v) for v in con.execute(
                    f"SELECT min({col}), max({col}), "
                    + ", ".join(f"approx_quantile({col}, {p})" for p in (0.01, 0.25, 0.5, 0.75, 0.99))
                    + f" FROM {relation}").fetchone()])))
            columns.append(TemporalColumn(bucket=b, **common, stats=stats))

        elif b == "boolean":
            top = None if row_count == 0 else [
                TopValue(value=v, count=n) for v, n in con.execute(
                    f"SELECT {col}, count(*) FROM {relation} GROUP BY 1 ORDER BY 2 DESC").fetchall()]
            columns.append(BooleanColumn(**common, top=top))

        else:  # string
            top = None if empty else [
                TopValue(value=v, count=n) for v, n in con.execute(
                    f"SELECT {col}, count(*) FROM {relation} WHERE {col} IS NOT NULL "
                    f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {TOP_K}").fetchall()]
            stats = None
            if not empty:
                lo, hi = con.execute(f"SELECT min({col}), max({col}) FROM {relation}").fetchone()
                non_null = con.execute(
                    f"SELECT count(*) FROM {relation} WHERE {col} IS NOT NULL").fetchone()[0]
                coverage = (sum(t.count for t in top) / non_null) if non_null else 0.0
                # Sniff VARCHAR only, over the SAMPLE, and report the rate -- never a
                # type name. A named semantic type is what gets copied into Flint's
                # `semantic_types` unexamined (ADR-0008 D9, one layer up).
                rate = None
                if head_of(reported) == "VARCHAR":
                    rate = con.execute(
                        f"SELECT avg(CASE WHEN try_cast({col} AS TIMESTAMP) IS NOT NULL "
                        f"THEN 1.0 ELSE 0.0 END) FROM (SELECT {col} FROM {relation} "
                        f"WHERE {col} IS NOT NULL ORDER BY random() LIMIT {SAMPLE_ROWS})"
                    ).fetchone()[0]
                stats = StringStats(min=lo, max=hi, top_k_coverage=coverage,
                                    iso8601_parse_rate=rate)
            columns.append(StringColumn(**common, top=top, stats=stats))

    # A uniform sample. `USING SAMPLE n ROWS` is NOT one -- measured, it draws 85%
    # of its rows from the first quintile. Production collects a reservoir of k in
    # the stats pass; the prototype issues it separately, and the artifact is the
    # same either way.
    sample_rows: list[dict[str, Any]] = []
    if row_count and scanned:
        cols = ", ".join(_q(c) for c in scanned)
        cur = con.execute(f"SELECT {cols} FROM {relation} ORDER BY random() LIMIT {SAMPLE_ROWS}")
        names = [d[0] for d in cur.description]
        sample_rows = [{k: _plain(v) for k, v in zip(names, row)} for row in cur.fetchall()]

    return _apply_ladder(Profile(row_count=row_count, columns=columns, sample_rows=sample_rows))


def _iso(v: Any) -> str:
    s = v.isoformat() if hasattr(v, "isoformat") else str(v)
    return s.replace("+00:00", "Z")


def _plain(v: Any) -> Any:
    if hasattr(v, "isoformat"):
        return _iso(v)
    if isinstance(v, decimal.Decimal):
        # A `number` column must not reach the planner as a JSON string.
        return float(v)
    if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
        return None                              # ADR-0008 D9's non-finite rule
    return v if isinstance(v, (str, int, float, bool, type(None))) else str(v)


def _size(p: Profile) -> int:
    return len(json.dumps(p.model_dump(exclude_none=True), default=str))


def _apply_ladder(p: Profile) -> Profile:
    """Rungs fire for the WHOLE profile or not at all, in a fixed order."""
    fired: list[str] = []
    if _size(p) <= BUDGET_BYTES:
        return p

    for col in p.columns:                                    # 1. reported_type head
        if len(col.reported_type) > REPORTED_TYPE_BUDGET:
            col.reported_type = head_of(col.reported_type)
    fired.append("reported_type_head")
    if _size(p) <= BUDGET_BYTES:
        return _stamp(p, fired)

    p.sample_rows = []                                       # 2. sample rows
    fired.append("sample_rows")
    if _size(p) <= BUDGET_BYTES:
        return _stamp(p, fired)

    for col in p.columns:                                    # 3. top values
        if getattr(col, "top", None):
            col.top = None
    fired.append("top_values")
    if _size(p) <= BUDGET_BYTES:
        return _stamp(p, fired)

    for col in p.columns:                                    # 4. percentiles + remainder
        if getattr(col, "stats", None) is not None:
            col.stats = None
    fired.append("percentiles")
    if _size(p) <= BUDGET_BYTES:
        return _stamp(p, fired)

    # 5. cap columns, in DESCRIBE order, and say how many were dropped.
    kept = len(p.columns)
    while kept > 1:
        kept -= 1
        trial = Profile(row_count=p.row_count, columns=p.columns[:kept],
                        truncation=Truncation(rungs=fired + ["columns"], omitted_count=1))
        if _size(trial) <= BUDGET_BYTES:
            break
    omitted = len(p.columns) - kept
    p.columns = p.columns[:kept]
    fired.append("columns")
    return _stamp(p, fired, omitted)


def _stamp(p: Profile, fired: list[str], omitted: int | None = None) -> Profile:
    p.truncation = Truncation(rungs=fired, omitted_count=omitted)
    return p


def _dump(p: Profile) -> dict:
    return p.model_dump(exclude_none=True)


if __name__ == "__main__":
    test_every_field_is_classified()
    print("taint classification: every field classified\n")

    con = duckdb.connect()
    tmp = tempfile.mkdtemp()
    pq = os.path.join(tmp, "orders.parquet")
    con.execute(f"""
    COPY (
      SELECT
        i AS order_id,
        ('region_' || CASE WHEN i % 100 < 60 THEN 'north' WHEN i % 100 < 85 THEN 'south'
                           WHEN i % 100 < 97 THEN 'east' ELSE 'west' END) AS region,
        ('SKU-' || lpad(((i * 7919) % 4300)::VARCHAR, 5, '0')) AS sku,
        (i % 11 <> 0) AS fulfilled,
        round((random() * 480 + 12)::DECIMAL(10,2), 2) AS amount_usd,
        (TIMESTAMP '2021-03-01' + INTERVAL (i % 1200) DAY)::DATE AS ordered_on,
        (TIMESTAMP '2021-03-01' + INTERVAL (i * 37) MINUTE) AT TIME ZONE 'UTC' AS updated_at,
        CASE WHEN i % 9 = 0 THEN NULL ELSE '2021-0' || ((i % 9) + 1) || '-14' END AS legacy_date,
        [i, i + 1] AS tags
      FROM range(400000) t(i)
    ) TO '{pq}' (FORMAT PARQUET)""")
    print(f"source: orders.parquet, 400,000 rows, 9 columns, "
          f"{os.path.getsize(pq)/1e6:.1f} MB\n")

    p = profile(con, f"'{pq}'")
    out = json.dumps(_dump(p), indent=2, default=str)
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile.sample.json")
    with open(path, "w") as fh:
        fh.write(out + "\n")
    print(out)
    print(f"\nprofile.sample.json: {len(out)} bytes "
          f"({len(out)/BUDGET_BYTES*100:.0f}% of the {BUDGET_BYTES}-byte budget), "
          f"truncation={'none' if p.truncation is None else p.truncation.rungs}")

    print("\nuntrusted paths the prompt renderer must fence:")
    for path_ in untrusted_paths():
        print(f"  {path_}")

    print("\n=== the ladder, on progressively wider sources ===")
    for ncols in (9, 40, 120, 400):
        con.execute("DROP TABLE IF EXISTS wide")
        cols = ", ".join(
            f"('cat_' || (i % {7 + c}))::VARCHAR AS c{c}" if c % 3 else f"(i * {c + 1})::BIGINT AS c{c}"
            for c in range(ncols))
        con.execute(f"CREATE TABLE wide AS SELECT {cols} FROM range(20000) t(i)")
        w = profile(con, "wide")
        size = len(json.dumps(_dump(w), default=str))
        rungs = "none" if w.truncation is None else ",".join(w.truncation.rungs)
        om = "" if w.truncation is None or w.truncation.omitted_count is None \
            else f"  omitted={w.truncation.omitted_count}"
        print(f"  {ncols:>3} cols -> {size:>6} bytes  ({size <= BUDGET_BYTES and 'under' or 'OVER '})"
              f"  rungs: {rungs}{om}")

    print("\n=== degenerate sources never raise (Decision 11) ===")
    con.execute("CREATE TABLE zero AS SELECT 1 AS a, 'x' AS b WHERE false")
    z = profile(con, "zero")
    print(f"  zero rows        -> row_count={z.row_count} columns={len(z.columns)} "
          f"stats={[getattr(c, 'stats', 'n/a') for c in z.columns]} sample={z.sample_rows}")
    con.execute("CREATE TABLE allnull AS SELECT NULL::INTEGER AS a FROM range(5)")
    n = profile(con, "allnull")
    print(f"  all-null column  -> null_rate={n.columns[0].null_rate} stats={n.columns[0].stats}")
    con.execute("CREATE TABLE blobs AS SELECT 'ab'::BLOB AS a, {'x': 1} AS b FROM range(5)")
    o = profile(con, "blobs")
    print(f"  all-`other`      -> {[ (c.bucket, c.reported_type) for c in o.columns ]} "
          f"(no scan, nothing chartable)")
    dup = profile(con, "(SELECT 1 AS id, 2 AS id)")
    print(f"  duplicate names  -> {[c.name for c in dup.columns]} "
          f"(a list, so both survive)")
