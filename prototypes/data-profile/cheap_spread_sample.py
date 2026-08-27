"""Can we get a positionally-spread sample WITHOUT reading the whole file?

The bias probe showed `USING SAMPLE n ROWS` draws 85% of its rows from the first
quintile, and that the honest alternative (`ORDER BY random() LIMIT n`) is a full
scan -- which contradicts PRD 7.4's "a 50 GB file profiles by transferring MBs".

Is there a middle: read the parquet footer, pick offsets at random, read only
those? That is a cluster sample -- spread across the file, adjacent within a group.

Run: uv run --with duckdb python cheap_spread_sample.py
"""
import os, tempfile, time, statistics, random
import duckdb

con = duckdb.connect()
print(f"duckdb {duckdb.__version__}\n")
tmp = tempfile.mkdtemp(); pq = os.path.join(tmp, "t.parquet")
N = 5_000_000
con.execute("SET preserve_insertion_order=true")
con.execute(f"""COPY (SELECT i AS id, 'v' || i AS label,
                  (TIMESTAMP '2020-01-01' + INTERVAL (i) MINUTE) AS ts
                FROM range({N}) t(i)) TO '{pq}' (FORMAT PARQUET, ROW_GROUP_SIZE 100000)""")
print(f"fixture: {N:,} rows, 3 cols, {os.path.getsize(pq)/1e6:.1f} MB, ROW_GROUP_SIZE=100000\n")

rg = con.execute(f"SELECT count(DISTINCT row_group_id) FROM parquet_metadata('{pq}')").fetchone()
t0 = time.perf_counter()
con.execute(f"SELECT count(*) FROM parquet_metadata('{pq}')").fetchall()
print(f"row groups visible in footer: {rg[0]}   footer read cost: {(time.perf_counter()-t0)*1000:.1f} ms\n")

TRIALS = 20
def quint(ids):
    q = [0]*5
    for i in ids: q[min(4, int(i / N * 5))] += 1
    return ' '.join(f'{c/len(ids)*100:4.0f}%' for c in q)

print("Cluster sample: k random offsets x m rows, UNION ALL")
def cluster_sql(k, m):
    return " UNION ALL ".join(
        f"(SELECT id FROM '{pq}' LIMIT {m} OFFSET {random.randint(0, N-m-1)})" for _ in range(k))
for k, m in [(5, 2), (10, 1), (3, 4)]:
    ids, tot = [], 0.0
    for _ in range(TRIALS):
        t0 = time.perf_counter(); ids += [r[0] for r in con.execute(cluster_sql(k, m)).fetchall()]
        tot += time.perf_counter()-t0
    print(f"  k={k} x m={m:<2}  mean={statistics.mean(ids)/N*100:5.1f}%  quintiles: {quint(ids)}  {tot/TRIALS*1000:7.1f} ms")

print("\nBaselines on the same fixture")
for label, sql in [("ORDER BY random() LIMIT 10", f"SELECT id FROM '{pq}' ORDER BY random() LIMIT 10"),
                   ("USING SAMPLE 10 ROWS",       f"SELECT id FROM '{pq}' USING SAMPLE 10 ROWS")]:
    ids, tot = [], 0.0
    for _ in range(TRIALS):
        t0 = time.perf_counter(); ids += [r[0] for r in con.execute(sql).fetchall()]; tot += time.perf_counter()-t0
    print(f"  {label:<28} mean={statistics.mean(ids)/N*100:5.1f}%  quintiles: {quint(ids)}  {tot/TRIALS*1000:7.1f} ms")

print("\nWhat is free from the footer, and what costs a scan?")
for label, sql in [
    ("count(*)",                 f"SELECT count(*) FROM '{pq}'"),
    ("min/max on id",            f"SELECT min(id), max(id) FROM '{pq}'"),
    ("footer stats_min/max",     f"SELECT stats_min, stats_max FROM parquet_metadata('{pq}') WHERE path_in_schema='id' LIMIT 1"),
    ("exact distinct <=1001",    f"SELECT count(*) FROM (SELECT DISTINCT label FROM '{pq}' LIMIT 1001)"),
    ("exact distinct full",      f"SELECT count(DISTINCT label) FROM '{pq}'"),
    ("approx_quantile p01/p99",  f"SELECT approx_quantile(id,0.01), approx_quantile(id,0.99) FROM '{pq}'"),
    ("exact quantile_cont p01/p99", f"SELECT quantile_cont(id,0.01), quantile_cont(id,0.99) FROM '{pq}'"),
]:
    t0 = time.perf_counter(); r = con.execute(sql).fetchall(); ms = (time.perf_counter()-t0)*1000
    print(f"  {label:<30} {ms:8.1f} ms   {str(r[0])[:52]}")
