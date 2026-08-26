"""What does DuckDB actually report, and can a bucket table key on it?

ADR-0010 Decision 4 maps *reported* type heads to buckets, not accepted aliases.
This is the measurement behind that. Run: uv run --with duckdb python reported_types.py
"""

import duckdb

con = duckdb.connect()
print(f"duckdb {duckdb.__version__}\n")

accepted = [r[0] for r in con.execute("""
    SELECT DISTINCT type_name FROM duckdb_types()
    WHERE database_name = 'system' ORDER BY 1
""").fetchall()]
print(f"type names DuckDB *accepts*: {len(accepted)}")
print(f"  {', '.join(accepted)}\n")

# The same types spelled every way DuckDB accepts them.
aliases = ["int4", "int32", "integer", "int", "string", "text", "varchar", "nvarchar",
           "datetime", "timestamp", "timestamptz", "timestamp with time zone",
           "bool", "boolean", "numeric", "dec", "decimal(10,2)", "guid", "uuid",
           "float8", "double"]
cols = ", ".join(f"NULL::{a} AS c{i}" for i, a in enumerate(aliases))
reported = [row[1] for row in con.execute(f"DESCRIBE SELECT {cols}").fetchall()]

print("alias declared            -> reported by DESCRIBE")
for alias, got in zip(aliases, reported):
    print(f"  {alias:<24} -> {got}")

distinct = sorted(set(reported))
print(f"\n{len(aliases)} aliases collapse to {len(distinct)} reported names:")
print(f"  {', '.join(distinct)}")

print("\nWhy the mapping is head-based, not exact-string:")
for a, b in [("numeric", "decimal(10,2)"), ("timestamp_ms", "timestamp_ns")]:
    ra, rb = [r[1] for r in con.execute(
        f"DESCRIBE SELECT NULL::{a} AS x, NULL::{b} AS y").fetchall()]
    print(f"  {a} -> {ra}   vs   {b} -> {rb}   (same bucket, different string)")
