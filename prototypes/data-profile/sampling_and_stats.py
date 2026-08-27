"""What does a profile actually cost, and can the PRD's words be delivered?

Three questions #5 turns on:
  1. Is "stratified sample rows" (PRD 7.3) even expressible before a target column exists?
  2. approx_count_distinct vs exact COUNT(DISTINCT): error and cost at scale.
  3. Does TABLESAMPLE on Parquet read the file, and are its rows clustered?

Run: uv run --with duckdb python sampling_and_stats.py
"""
import json, time, os, tempfile
import duckdb

con = duckdb.connect()
print(f"duckdb {duckdb.__version__}\n")
tmp = tempfile.mkdtemp()
pq = os.path.join(tmp, "wide.parquet")

# A tall table with a skewed categorical, a temporal column, and a long tail.
N = 5_000_000
con.execute(f"""
COPY (
  SELECT
    i AS id,
    ('cat_' || CASE WHEN i % 100 < 90 THEN 0 WHEN i % 100 < 99 THEN 1 ELSE (i % 37) + 2 END) AS category,
    ('user_' || (i % 250000)) AS user_id,
    (i % 7 = 0) AS is_active,
    (random() * 1000)::DOUBLE AS amount,
    (TIMESTAMP '2024-01-01' + INTERVAL (i % 500) DAY) AS created_at,
    CASE WHEN i % 13 = 0 THEN NULL ELSE 'note ' || i END AS note
  FROM range({N}) t(i)
) TO '{pq}' (FORMAT PARQUET)
""")
size_mb = os.path.getsize(pq) / 1e6
print(f"fixture: {N:,} rows, 7 cols, {size_mb:.1f} MB parquet\n")

def timed(label, sql, show=True):
    t0 = time.perf_counter()
    r = con.execute(sql).fetchall()
    ms = (time.perf_counter() - t0) * 1000
    print(f"  {label:<52} {ms:8.1f} ms" + (f"   -> {r[0]}" if show and r else ""))
    return r, ms

print("=== 1. cardinality: exact vs approximate ===")
for colname in ("category", "user_id", "note"):
    (exact,), t_e = timed(f"exact COUNT(DISTINCT {colname})",
        f"SELECT count(DISTINCT {colname}) FROM '{pq}'", show=False)
    (appx,), t_a = timed(f"approx_count_distinct({colname})",
        f"SELECT approx_count_distinct({colname}) FROM '{pq}'", show=False)
    err = abs(appx[0] - exact[0]) / exact[0] * 100 if exact[0] else 0
    print(f"    {colname:<10} exact={exact[0]:>9,} ({t_e:7.1f} ms)   "
          f"approx={appx[0]:>9,} ({t_a:7.1f} ms)   err={err:5.2f}%   "
          f"speedup={t_e/t_a:5.2f}x")

print("\n=== 2. does one pass get every column's stats? ===")
_, t_sum = timed("SUMMARIZE (all 7 cols, one statement)", f"SUMMARIZE SELECT * FROM '{pq}'", show=False)
rows = con.execute(f"SUMMARIZE SELECT * FROM '{pq}'").fetchall()
cols = [d[0] for d in con.description]
print(f"    SUMMARIZE columns returned: {cols}")
print(f"    bytes of raw SUMMARIZE output as JSON: "
      f"{len(json.dumps([dict(zip(cols, [str(v) for v in r])) for r in rows]))}")

print("\n=== 3. sampling: cost and clustering ===")
for label, clause in [
    ("USING SAMPLE 10 ROWS  (reservoir, default)", "USING SAMPLE 10 ROWS"),
    ("USING SAMPLE reservoir(10 ROWS)",            "USING SAMPLE reservoir(10 ROWS)"),
    ("USING SAMPLE 0.1% (system)",                 "USING SAMPLE 0.1% (system)"),
    ("USING SAMPLE 10 ROWS (bernoulli)",           "USING SAMPLE 10 ROWS (bernoulli)"),
]:
    try:
        r, ms = timed(label, f"SELECT id FROM '{pq}' {clause}", show=False)
        ids = sorted(x[0] for x in r)[:10]
        spread = (max(x[0] for x in r) - min(x[0] for x in r)) / N if len(r) > 1 else 0
        print(f"    n={len(r):<7} first ids={ids[:5]}  id-spread={spread:.1%} of table")
    except Exception as e:
        print(f"    {label}: FAILED {type(e).__name__}: {str(e)[:90]}")

print("\n=== 4. can we stratify without a target column? ===")
try:
    r, ms = timed("stratified by 'category' (window over full scan)",
        f"""SELECT id, category FROM (
              SELECT *, row_number() OVER (PARTITION BY category ORDER BY random()) rn
              FROM '{pq}'
            ) WHERE rn <= 2""", show=False)
    print(f"    rows={len(r)}  distinct strata={len({x[1] for x in r})}")
    print("    NOTE: requires naming the stratum column -> a target the planner has not chosen yet")
except Exception as e:
    print(f"    FAILED: {e}")

print("\n=== 5. what does a profile weigh? ===")
def profile_bytes(ncols, nsample, ndistinct):
    col = {"name": "some_column_name", "bucket": "string", "null_rate": 0.031,
           "distinct": 1234, "distinct_exact": False,
           "top": [{"v": f"value_{i}", "n": 100} for i in range(ndistinct)]}
    sample = [{f"col_{c}": f"value_{c}" for c in range(ncols)} for _ in range(nsample)]
    return len(json.dumps({"columns": [col] * ncols, "sample_rows": sample}))
for ncols in (7, 12, 40, 100, 400):
    print(f"    {ncols:>3} cols  10-row sample, 5 top values: {profile_bytes(ncols,10,5)/1024:7.1f} KB"
          f"   |  no sample: {profile_bytes(ncols,0,5)/1024:6.1f} KB"
          f"   |  stub only: {ncols*40/1024:5.1f} KB")
