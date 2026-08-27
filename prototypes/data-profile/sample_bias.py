"""Is DuckDB's reservoir sample actually uniform over the table?

The first probe drew 10 rows and got ids [512, 1182, 3214, 5986, 131875] from a
5M-row table -- suspiciously early. If reservoir sampling with a discrete row
count is position-biased, "a sample of the data" is a sample of the top of the
file, and on time-ordered data that is a sample of the oldest week.

Run: uv run --with duckdb python sample_bias.py
"""
import os, tempfile, statistics
import duckdb

con = duckdb.connect()
print(f"duckdb {duckdb.__version__}\n")
tmp = tempfile.mkdtemp(); pq = os.path.join(tmp, "t.parquet")
N = 5_000_000
con.execute(f"COPY (SELECT i AS id FROM range({N}) t(i)) TO '{pq}' (FORMAT PARQUET)")
print(f"fixture: {N:,} rows, monotonic id 0..{N-1}\n")
print("A uniform sample has mean id ~= 50% of N and ~20% of draws in each quintile.\n")

TRIALS = 40
for label, sql in [
    ("USING SAMPLE 10 ROWS (default)",      f"SELECT id FROM '{pq}' USING SAMPLE 10 ROWS"),
    ("USING SAMPLE reservoir(10 ROWS)",     f"SELECT id FROM '{pq}' USING SAMPLE reservoir(10 ROWS)"),
    ("USING SAMPLE 1% (system) LIMIT 10",   f"SELECT id FROM '{pq}' USING SAMPLE 1% (system) LIMIT 10"),
    ("USING SAMPLE 1% (bernoulli) LIMIT 10",f"SELECT id FROM '{pq}' USING SAMPLE 1% (bernoulli) LIMIT 10"),
    ("ORDER BY random() LIMIT 10",          f"SELECT id FROM '{pq}' ORDER BY random() LIMIT 10"),
]:
    try:
        ids = []
        for _ in range(TRIALS):
            ids += [r[0] for r in con.execute(sql).fetchall()]
        q = [0]*5
        for i in ids: q[min(4, int(i / N * 5))] += 1
        pct = [f"{c/len(ids)*100:4.0f}%" for c in q]
        print(f"  {label:<38} mean={statistics.mean(ids)/N*100:5.1f}% of N   quintiles: {' '.join(pct)}")
    except Exception as e:
        print(f"  {label:<38} FAILED {type(e).__name__}: {str(e)[:70]}")

print("\n=== cost of an honest sample on the same file ===")
import time
for label, sql in [
    ("USING SAMPLE reservoir(10 ROWS)", f"SELECT * FROM '{pq}' USING SAMPLE reservoir(10 ROWS)"),
    ("ORDER BY random() LIMIT 10",      f"SELECT * FROM '{pq}' ORDER BY random() LIMIT 10"),
]:
    t0 = time.perf_counter(); con.execute(sql).fetchall()
    print(f"  {label:<38} {(time.perf_counter()-t0)*1000:8.1f} ms")
