"""Does a TIMESTAMP -> TIMESTAMPTZ retype change the chart?

ADR-0010 Decision 3 splits `timestamp` and `timestamptz` into separate buckets.
This is the measurement behind that split. Run: uv run --with duckdb python day_boundary.py
"""

import duckdb

con = duckdb.connect()
con.execute("SET TimeZone='UTC'")
print(f"duckdb {duckdb.__version__}, TimeZone='UTC'\n")


def report(title, aware_expr, start):
    con.execute("DROP TABLE IF EXISTS src")
    con.execute(f"""
        CREATE TABLE src AS
        SELECT ts_text,
               ts_text::TIMESTAMP AS as_naive,
               {aware_expr}       AS as_aware
        FROM (
          SELECT strftime(TIMESTAMP '{start}' + INTERVAL (n) HOUR,
                          '%Y-%m-%d %H:%M:%S') AS ts_text
          FROM range(0, 240) t(n)
        )
    """)
    moved, total = con.execute("""
        SELECT (SELECT count(*) FROM src
                 WHERE date_trunc('day', as_naive)
                    <> date_trunc('day', as_aware)::TIMESTAMP),
               (SELECT count(*) FROM src)
    """).fetchone()

    print(f"{title}\n  rows whose day bucket differs: {moved}/{total}")
    print("  per-day row counts (the bar heights):")
    for day, naive, aware in con.execute("""
        SELECT COALESCE(n.d, a.d), n.c, a.c
        FROM      (SELECT date_trunc('day', as_naive)::DATE d, count(*) c
                     FROM src GROUP BY 1) n
        FULL JOIN (SELECT date_trunc('day', as_aware)::DATE d, count(*) c
                     FROM src GROUP BY 1) a ON n.d = a.d
        ORDER BY 1
    """).fetchall():
        flag = "" if naive == aware else "   <-- differs"
        print(f"    {day}  naive={str(naive):>4}  aware={str(aware):>4}{flag}")
    print()


# A fixed offset: the shift is uniform, so only the two edge bars move.
report("fixed -05:00 offset", "(ts_text || '-05:00')::TIMESTAMPTZ", "2026-03-01 00:00:00")

# A real zone across a DST transition: an interior bar moves too.
report("America/New_York, across the 2026-03-08 DST transition",
       "ts_text::TIMESTAMP AT TIME ZONE 'America/New_York'", "2026-03-04 00:00:00")
