"""How does DuckDB *report* composite types, and does ADR-0010 D4's head rule work?

D4 says "match the constructor head before its parameters" and lists LIST, ARRAY,
STRUCT, MAP, UNION under `other`. But DuckDB reports lists in POSTFIX form.

Run: uv run --with duckdb python reported_composites.py
"""
import duckdb
con = duckdb.connect()
print(f"duckdb {duckdb.__version__}\n")
cases = [
    ("[1,2,3]", "list literal"), ("[1,2,3]::BIGINT[]", "LIST typed"),
    ("[1,2,3]::INTEGER[3]", "ARRAY fixed"), ("{'a': 1}", "STRUCT"),
    ("MAP{'a': 1}", "MAP"), ("'x'::BLOB", "BLOB"), ("'{\"a\":1}'::JSON", "JSON"),
    ("union_value(k := 1)", "UNION"), ("'1 day'::INTERVAL", "INTERVAL"),
    ("'12:00'::TIME", "TIME"), ("[[1],[2]]", "nested list"),
    ("[{'a': 1}]", "list of struct"), ("1::DECIMAL(10,2)", "DECIMAL"),
    ("now()", "TIMESTAMPTZ"), ("'a'::ENUM('a','b')", "ENUM"), ("uuid()", "UUID"),
    ("'2020-01-01'::TIMESTAMP_NS", "TIMESTAMP_NS"),
]
import re
def head(s): return re.split(r"[(\[]", s, maxsplit=1)[0].strip().upper()
print(f"{'expression':<24} {'reported type':<34} {'naive head':<16} verdict")
for expr, label in cases:
    try:
        t = con.execute(f"SELECT typeof({expr})").fetchone()[0]
    except Exception as e:
        print(f"{label:<24} FAILED {str(e)[:60]}"); continue
    h = head(t)
    composite = any(t.startswith(p) or t.endswith("]") for p in ("STRUCT", "MAP", "UNION"))
    bad = composite and h not in ("STRUCT", "MAP", "UNION")
    print(f"{label:<24} {t[:33]:<34} {h:<16} {'<-- MISBUCKETS' if bad else ''}")
print("\nPostfix forms that defeat a prefix-head rule:")
for expr in ("[1,2,3]::BIGINT[]", "[1,2,3]::INTEGER[3]", "[['a']]::VARCHAR[][]"):
    t = con.execute(f"SELECT typeof({expr})").fetchone()[0]
    print(f"  {expr:<26} reports {t:<20} naive head -> {head(t)}")
