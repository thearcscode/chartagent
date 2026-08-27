"""Do duplicate column names ever reach the profiler as duplicates?

Q18 locked `columns` as a list "because ADR-0008 D4's allowlist must see the same
list". But DuckDB's binder renamed `SELECT 1 AS id, 2 AS id` to id, id_1. Does a
parquet file with two identically-named columns behave the same way?
"""
import os, tempfile, duckdb, pyarrow as pa, pyarrow.parquet as pqw

con = duckdb.connect()
print(f"duckdb {duckdb.__version__}, pyarrow {pa.__version__}\n")
tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "dup.parquet")
tbl = pa.table([pa.array([1, 2]), pa.array(["a", "b"])],
               schema=pa.schema([pa.field("id", pa.int64()), pa.field("id", pa.string())]))
pqw.write_table(tbl, path)
print("parquet schema on disk: " + str([f"{f.name}:{f.type}" for f in tbl.schema]))

desc = con.execute("DESCRIBE SELECT * FROM '" + path + "'").fetchall()
print("  DESCRIBE  -> " + str([(r[0], r[1]) for r in desc]))
cur = con.execute("SELECT * FROM '" + path + "'")
print("  binder    -> " + str([d[0] for d in cur.description]))
cur2 = con.execute("SELECT 1 AS id, 2 AS id")
print("  aliases   -> " + str([d[0] for d in cur2.description]))
