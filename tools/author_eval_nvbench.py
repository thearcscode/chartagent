"""One-shot authoring of the nvBench-drawn cases of eval-benchmark-v1 (issue #284).

Draws the 102 common-path nvBench cases (90 cell-0 plus 12 cell-2) of the
frozen 150 (ADR-0029 Decisions 6 and 7), pins each case's table under
``eval/data/``, builds a façade-valid reference frame for each, and writes the
partial cases file ``eval/cases-nvbench.json`` that the assembly ticket (#287)
merges with the authored cases.

nvBench 1.0 is fetched (NVBench.json and databases.zip from
TsinghuaDatabaseGroup/nvBench, sha256 pinned below) into ``NVDIR``. Nothing is
read from ``corpus/data``. Not a library surface. Re-running it after the
``eval-benchmark-v1`` tag is cut is a freeze break.

Selection rules, in the order they bite:

1. Unnamed-mark: the NL query names no chart type (no bar / pie / line /
   scatter / chart / plot / graph / ... word) and no axis or binning
   vocabulary. At least ``MIN_LEFTOVER`` such queries must remain after
   excluding corpus-prereg-v1; fewer is a STOP, never a smaller n.
2. Disjoint from corpus-prereg-v1: no nvBench key (nor an ``@x_name@...``
   variant of it) that the 50 or its reserves used, and no nvBench database
   the 50 used. Stricter than "no shared source ID".
3. One query per nvBench key, at most ``DB_CAP`` per database.
4. Mechanically checkable: the query parses to a single group-aggregate, a
   binned aggregate, or a two-column pick over one table or an equi-join. The
   reference frame is executed against the pinned parquet by the real
   transform engine and its y values must equal both the gold SQL run on the
   nvBench database and nvBench's own gold ``y_data``.

nvBench's gold chart type is not the reference frame (ADR-0014 Decision 8):
the intent is assigned after selection and picks the chart type. Shapes are
assigned by construction of the pinned table (see ``_shape_table``).
"""

from __future__ import annotations

import collections
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import urllib.request
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from chartagent.frame.input import InputFrame
from chartagent.transform.engine import (
    describe_source,
    open_connection,
    register_source,
)
from chartagent.transform.menu import run_transform
from chartagent.transform.raw_sql import validate_raw_sql

REPO = Path(__file__).resolve().parents[1]
EVAL = REPO / "eval"
DATA = EVAL / "data"
OUT = EVAL / "cases-nvbench.json"
CORPUS_PREREG = REPO / "corpus" / "pre-registration.json"
NVDIR = Path("/tmp/nvbench-1.0")

NV_REPO = "TsinghuaDatabaseGroup/nvBench"
NV_COMMIT = "544fbc218a2c2fd5dac7591371e3e01ccd6afb93"
NV_FILES = {
    "NVBench.json": "8c85a9454fe1343074ba915bcbb379f170ab62bb1279b6a7aed23255e6eefbcf",
    "databases.zip": "a2e22bf648f6d8e4c387d85f75962931976f1756338b41d025de528c8ff2da3d",
}

BASE = {"width": 640, "height": 400}
MIN_LEFTOVER = 102
DB_CAP = 3
MAX_ROWS = 3000

# The common-path design (ADR-0029 Decision 6) for the 102 drawn here. The 18
# other common-path cases (cell-3 x2, cell-4 x16) are authored elsewhere
# (#283/#285/#286); the totals below are what is left of the common-path
# marginals once those are in: intents trend 23, comparison 29, distribution 4,
# correlation 7, part-to-whole 22, ranking 5, flow 4, geographic 4, single 4;
# shapes long 43, wide 43, nested 8, wide_sparse 8.
CELL0_INTENTS = {
    "trend over time": 18,
    "comparison across categories": 26,
    "distribution of one measure": 4,
    "correlation between measures": 7,
    "part-to-whole": 18,
    "ranking / top-N": 5,
    "flow or transition between states": 4,
    "geographic distribution": 4,
    "single value against a target": 4,
}
CELL2_INTENTS = {
    "trend over time": 5,
    "part-to-whole": 4,
    "comparison across categories": 3,
}
CELL0_SHAPES = {"long": 43, "wide": 35, "nested": 8, "wide_sparse": 4}
CELL2_SHAPES = {"wide": 8, "wide_sparse": 4}

CHARTWORDS = re.compile(
    r"\b(bar|bars|pie|line|lines|scatter|histogram|chart|charts|plot|plots|graph|"
    r"graphs|visuali[sz]\w*|stacked|donut|trend ?line|point|points|heatmap|draw|"
    r"pictur\w*|diagram)\b",
    re.I,
)
AXISWORDS = re.compile(
    r"(x[- ]?axis|y[- ]?axis|\baxis\b|group by attribute|\bbin\b|\bbinning\b|"
    r"\bthe x\b|\bthe y\b|\bX\b|\bY\b|by time)",
    re.I,
)
ORDERWORDS = re.compile(
    r"(ascend|descend|\basc\b|\bdesc\b|\border(ed|ing)?\b|\bsort|low to high|"
    r"high to low|from low|from high|alphabet|increasing|decreasing|ranked)",
    re.I,
)
YEARISH = re.compile(r"(year|date|month|time|day|period|season|born|dob|hire|creation)", re.I)
STATUSISH = re.compile(r"(status|stage|step|phase|outcome|decision)", re.I)
GEOISH = re.compile(r"(country|nation|state|province|citizenship)", re.I)
RANKWORDS = re.compile(
    r"\b(top|most|highest|largest|biggest|fewest|lowest|least|best|worst|greatest|"
    r"smallest|cheapest|oldest|youngest|at least \d+|at most \d+)\b",
    re.I,
)
UNITS = {"YEAR": "year", "MONTH": "month", "DAY": "day", "QUARTER": "quarter", "WEEK": "week"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Fetch and pool
# ---------------------------------------------------------------------------


def fetch() -> Path:
    NVDIR.mkdir(parents=True, exist_ok=True)
    for name, digest in NV_FILES.items():
        path = NVDIR / name
        if not path.exists() or _sha(path) != digest:
            url = f"https://raw.githubusercontent.com/{NV_REPO}/{NV_COMMIT}/{name}"
            with urllib.request.urlopen(url) as resp, path.open("wb") as fh:  # noqa: S310
                shutil.copyfileobj(resp, fh)
        if _sha(path) != digest:
            raise SystemExit(f"{name}: sha256 does not match the pin")
    dbdir = NVDIR / "databases"
    if not dbdir.exists():
        with zipfile.ZipFile(NVDIR / "databases.zip") as zf:
            zf.extractall(dbdir)
    return NVDIR


def _dbpath(db: str) -> Path:
    return NVDIR / "databases" / "database" / db / f"{db}.sqlite"


def load_nvbench() -> dict[str, Any]:
    return json.loads((NVDIR / "NVBench.json").read_text())


def _base_key(source_key: str) -> str:
    return source_key.split("@")[0]


def prereg_exclusions(nv: dict[str, Any]) -> tuple[set[str], set[str]]:
    prereg = json.loads(CORPUS_PREREG.read_text())
    keys: set[str] = set()
    dbs: set[str] = set()
    for row in prereg["requests"] + prereg["reserves"]:
        if row["source"] != "nvbench1":
            continue
        key = row["source_id"].rsplit("@", 1)[0]
        keys.add(_base_key(key))
        if key in nv:
            dbs.add(nv[key]["db_id"])
    return keys, dbs


def unnamed_leftovers(nv: dict[str, Any], used_keys: set[str]) -> list[tuple[str, int]]:
    out = []
    for key, rec in nv.items():
        if _base_key(key) in used_keys:
            continue
        for i, q in enumerate(rec["nl_queries"]):
            if not CHARTWORDS.search(q):
                out.append((key, i))
    return out


# ---------------------------------------------------------------------------
# Query parsing
# ---------------------------------------------------------------------------

SQLRE = re.compile(
    r"^SELECT (?P<sel>.+?) FROM (?P<frm>.+?)"
    r"(?: WHERE (?P<where>.+?))?"
    r"(?: GROUP BY (?P<grp>.+?))?"
    r"(?: ORDER BY (?P<ord>.+?))?\s*$",
    re.I,
)
AGGRE = re.compile(r"^(COUNT|SUM|AVG|MAX|MIN)\(\s*(DISTINCT\s+)?(\*|[\w.]+)\s*\)$", re.I)
JOINRE = re.compile(
    r"\bJOIN\s+(\w+)(?:\s+AS\s+(\w+))?\s+ON\s+([\w.]+)\s*=\s*([\w.]+)", re.I
)
PREDRE = re.compile(
    r"^([\w.]+)\s*(=|!=|<>|>=|<=|>|<)\s*('[^']*'|\"[^\"]*\"|-?\d+(?:\.\d+)?)$"
)
INRE = re.compile(r"^([\w.]+)\s+IN\s*\(([^()]*)\)$", re.I)
OPKIND = {"=": "eq", "!=": "ne", "<>": "ne", ">": "gt", "<": "lt", ">=": "gte", "<=": "lte"}
AGGOP = {"count": "count", "sum": "sum", "avg": "mean", "max": "max", "min": "min"}


@dataclass
class Parsed:
    key: str
    idx: int
    db: str
    chart: str
    sql: str
    tables: list[tuple[str, str]]  # (alias, table)
    joins: list[tuple[str, str, str, str]]  # (alias_a, col_a, alias_b, col_b)
    x: tuple[str, str]  # (alias, canonical column)
    y: tuple[str, str] | None  # plain column
    agg: tuple[str, bool, tuple[str, str] | None] | None  # (op, distinct, col)
    preds: list[tuple[str, str, str, Any]]  # (alias, col, kind, literal)
    conj: str
    group: bool
    order: tuple[str, str] | None  # ("x"|"y", "asc"|"desc")
    bin: tuple[str, str] | None  # (col, unit)
    query: str
    columns: dict[str, list[str]] = field(default_factory=dict)  # table -> columns


def _table_columns(db: str, table: str) -> list[tuple[str, str]]:
    con = sqlite3.connect(_dbpath(db))
    try:
        return [(r[1], (r[2] or "").upper()) for r in con.execute(f'PRAGMA table_info("{table}")')]
    finally:
        con.close()


def _literal(raw: str) -> Any:
    if raw[0] in "'\"":
        return raw[1:-1]
    return float(raw) if "." in raw else int(raw)


def parse(key: str, idx: int, rec: dict[str, Any]) -> Parsed | None:
    dp = rec["vis_query"]["data_part"]
    sql = " ".join(dp["sql_part"].split())
    up = sql.upper()
    if any(w in up for w in (" HAVING ", " UNION ", " LIMIT ", " LIKE ", " BETWEEN ", " NOT ")):
        return None
    if up.count("SELECT") > 1:
        return None
    m = SQLRE.match(sql)
    if not m:
        return None
    g = m.groupdict()
    db = rec["db_id"]

    # FROM / JOIN
    frm = g["frm"]
    head = re.split(r"\s+JOIN\s+", frm, maxsplit=1, flags=re.I)[0]
    hm = re.match(r"^(\w+)(?:\s+AS\s+(\w+))?$", head.strip(), re.I)
    if not hm:
        return None
    tables = [(hm.group(2) or hm.group(1), hm.group(1))]
    joins_raw = JOINRE.findall(frm)
    if len(re.findall(r"\bJOIN\b", frm, re.I)) != len(joins_raw):
        return None
    pending = []
    for tbl, alias, left, right in joins_raw:
        tables.append((alias or tbl, tbl))
        pending.append((left, right))
    if len(tables) > 3:
        return None
    cols: dict[str, list[tuple[str, str]]] = {}
    try:
        for alias, tbl in tables:
            cols[alias] = _table_columns(db, tbl)
    except sqlite3.Error:
        return None

    def resolve(ref: str) -> tuple[str, str] | None:
        if "." in ref:
            a, c = ref.split(".", 1)
            for alias, _ in tables:
                if alias.lower() == a.lower():
                    for name, _typ in cols[alias]:
                        if name.lower() == c.lower():
                            return alias, name
            return None
        hits = [
            (alias, name)
            for alias, _ in tables
            for name, _typ in cols[alias]
            if name.lower() == ref.lower()
        ]
        return hits[0] if hits else None

    joins = []
    for left, right in pending:
        a, b = resolve(left), resolve(right)
        if a is None or b is None:
            return None
        joins.append((a[0], a[1], b[0], b[1]))

    # SELECT
    sel = [s.strip() for s in g["sel"].split(",")]
    if len(sel) != 2:
        return None
    if AGGRE.match(sel[0]):
        return None
    x = resolve(sel[0])
    if x is None:
        return None
    y: tuple[str, str] | None = None
    agg: tuple[str, bool, tuple[str, str] | None] | None = None
    am = AGGRE.match(sel[1])
    if am:
        op, distinct, ref = am.group(1).lower(), am.group(2) is not None, am.group(3)
        col = None if ref == "*" else resolve(ref)
        if ref != "*" and col is None:
            return None
        if distinct and op != "count":
            return None
        agg = (op, distinct, col)
    else:
        y = resolve(sel[1])
        if y is None:
            return None

    # WHERE
    preds: list[tuple[str, str, str, Any]] = []
    conj = "and"
    if g["where"]:
        text = g["where"].strip()
        has_and = re.search(r"\s+AND\s+", text, re.I) is not None
        has_or = re.search(r"\s+OR\s+", text, re.I) is not None
        if has_and and has_or:
            return None
        conj = "or" if has_or else "and"
        for part in re.split(r"\s+(?:AND|OR)\s+", text, flags=re.I):
            part = part.strip()
            pm, im = PREDRE.match(part), INRE.match(part)
            if pm:
                ref = resolve(pm.group(1))
                if ref is None:
                    return None
                preds.append((ref[0], ref[1], OPKIND[pm.group(2)], _literal(pm.group(3))))
            elif im:
                ref = resolve(im.group(1))
                if ref is None:
                    return None
                items = [i.strip() for i in im.group(2).split(",")]
                if not items or not all(PREDRE.match(f"a={i}") for i in items):
                    return None
                preds.append((ref[0], ref[1], "in", [_literal(i) for i in items]))
            else:
                return None

    # GROUP BY
    group = False
    if g["grp"]:
        groups = [s.strip() for s in g["grp"].split(",")]
        if len(groups) != 1:
            return None
        gref = resolve(groups[0])
        if gref is None or gref != x:
            return None
        group = True

    bin_item: tuple[str, str] | None = None
    if dp["binning"]:
        bm = re.match(r"^BIN\s+(\w+)\s+BY\s+(\w+)$", dp["binning"].strip(), re.I)
        if not bm or bm.group(2).upper() not in UNITS:
            return None
        bref = resolve(bm.group(1))
        if bref is None or bref != x:
            return None
        bin_item = (bref[1], UNITS[bm.group(2).upper()])

    # shape of the query must be one of the three kinds
    if agg is not None and not group and bin_item is None:
        return None
    if agg is None and (group or bin_item is not None):
        return None
    if group and bin_item is not None:
        return None

    # ORDER BY
    order = None
    if g["ord"]:
        om = re.match(r"^([\w.]+(?:\([^()]*\))?)\s*(ASC|DESC)?$", g["ord"].strip(), re.I)
        if not om:
            return None
        target = om.group(1)
        direction = (om.group(2) or "asc").lower()
        if AGGRE.match(target):
            if agg is None or target.replace(" ", "").lower() != sel[1].replace(" ", "").lower():
                return None
            order = ("y", direction)
        else:
            tref = resolve(target)
            if tref == x:
                order = ("x", direction)
            elif y is not None and tref == y:
                order = ("y", direction)
            else:
                return None

    return Parsed(
        key=key,
        idx=idx,
        db=db,
        chart=rec["chart"],
        sql=sql if not dp["binning"] else sql,
        tables=tables,
        joins=joins,
        x=x,
        y=y,
        agg=agg,
        preds=preds,
        conj=conj,
        group=group,
        order=order,
        bin=bin_item,
        query=rec["nl_queries"][idx],
        columns={a: [n for n, _ in cols[a]] for a, _ in tables},
    )


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


@dataclass
class Cand:
    p: Parsed
    source_id: str
    intents: list[str]
    names: dict[tuple[str, str], str]  # (alias, col) -> output column name
    needed: list[tuple[str, str]]
    nrows: int
    ncols_table: int
    unused: int
    gold_y: list[float | str]
    oracle_y: list[float | str]
    types: dict[tuple[str, str], str]
    distinct_x: int
    x_numeric: bool
    y_numeric: bool
    goal: str | None = None


def _needed(p: Parsed) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []

    def add(c: tuple[str, str] | None) -> None:
        if c is not None and c not in out:
            out.append(c)

    add(p.x)
    add(p.y)
    if p.agg is not None:
        add(p.agg[2])
    for alias, col, _k, _v in p.preds:
        add((alias, col))
    return out


def _names(needed: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    counts: dict[str, int] = {}
    for _a, c in needed:
        counts[c.lower()] = counts.get(c.lower(), 0) + 1
    return {(a, c): (c if counts[c.lower()] == 1 else f"{a}_{c}") for a, c in needed}


def _from_sql(p: Parsed) -> str:
    first_alias, first_tbl = p.tables[0]
    sql = f'"{first_tbl}" AS "{first_alias}"'
    for (alias, tbl), (aa, ac, ba, bc) in zip(p.tables[1:], p.joins, strict=True):
        sql += f' JOIN "{tbl}" AS "{alias}" ON "{aa}"."{ac}" = "{ba}"."{bc}"'
    return sql


def _round(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 4)
    return v


def _sorted(values: list[Any]) -> list[Any]:
    return sorted((_round(v) for v in values), key=lambda v: (v is None, str(v)))


def _norm_num(values: list[Any]) -> list[Any]:
    out = []
    for v in values:
        if isinstance(v, bool):
            out.append(int(v))
        elif isinstance(v, (int, float)):
            out.append(round(float(v), 4))
        else:
            out.append(v)
    return sorted(out, key=lambda v: (v is None, str(v)))


def make_candidate(
    key: str, idx: int, rec: dict[str, Any]
) -> Cand | None:
    q = rec["nl_queries"][idx]
    if CHARTWORDS.search(q) or AXISWORDS.search(q) or len(q.split()) < 5:
        return None
    if rec["vis_obj"].get("classify"):
        return None
    p = parse(key, idx, rec)
    if p is None:
        return None
    if p.chart not in {"Bar", "Pie", "Line", "Scatter"}:
        return None
    # ordering vocabulary must agree with the SQL: a request that asks for an
    # order has an ORDER BY the frame can carry, and vice versa.
    if bool(ORDERWORDS.search(q)) != (p.order is not None):
        return None
    needed = _needed(p)
    names = _names(needed)
    con = sqlite3.connect(_dbpath(p.db))
    con.text_factory = lambda b: b.decode("utf-8", errors="replace")
    try:
        cols_sql = ", ".join(f'"{a}"."{c}" AS "{names[(a, c)]}"' for a, c in needed)
        nrows = con.execute(f"SELECT count(*) FROM {_from_sql(p)}").fetchone()[0]
        if nrows == 0 or nrows > MAX_ROWS:
            return None
        sql = p.sql
        if p.bin is not None:
            sql_run = None
        else:
            sql_run = sql
        oracle: list[Any] = []
        if sql_run is not None:
            try:
                oracle = [r[-1] for r in con.execute(sql_run).fetchall()]
            except sqlite3.Error:
                return None
        types = {}
        for a, c in needed:
            tname = dict(_table_columns(p.db, dict(p.tables)[a]))[c]
            types[(a, c)] = tname
        xs = [r[0] for r in con.execute(f"SELECT {cols_sql} FROM {_from_sql(p)}").fetchall()]
        distinct_x = len(set(xs))
    except sqlite3.Error:
        return None
    finally:
        con.close()
    gold = rec["vis_obj"]
    gold_y: list[Any] = [v for series in gold["y_data"] for v in series]
    if p.bin is None and _norm_num(gold_y) != _norm_num(oracle):
        return None
    ncols_table = len(p.columns[p.tables[0][0]])
    unused = ncols_table - sum(1 for a, _c in needed if a == p.tables[0][0])
    numeric = lambda t: any(s in t for s in ("INT", "REAL", "FLOAT", "NUM", "DOUBLE", "DEC"))  # noqa: E731
    cand = Cand(
        p=p,
        source_id=f"{key}@{idx}",
        intents=[],
        names=names,
        needed=needed,
        nrows=nrows,
        ncols_table=ncols_table,
        unused=unused,
        gold_y=gold_y,
        oracle_y=oracle,
        types=types,
        distinct_x=distinct_x,
        x_numeric=numeric(types[p.x]),
        y_numeric=(p.y is not None and numeric(types[p.y])),
    )
    cand.intents = intents_of(cand)
    return cand if cand.intents else None


def intents_of(c: Cand) -> list[str]:
    p = c.p
    out: list[str] = []
    xname = p.x[1]
    if p.bin is not None:
        if _bin_castable(c):
            out.append("trend over time")
        return out
    if p.group and p.agg is not None:
        whole = re.search(r"\b(proportion|percentage|share|ratio|breakdown)\b", p.query, re.I)
        if p.chart == "Pie" or whole:
            out.append("part-to-whole")
        elif p.chart == "Line" or (YEARISH.search(xname) and p.chart == "Bar"):
            out.append("trend over time")
        elif p.chart == "Scatter":
            if c.x_numeric:
                out.append("correlation between measures")
        else:
            out.append("comparison across categories")
        if STATUSISH.search(xname):
            out.append("flow or transition between states")
        if GEOISH.search(xname) and not c.x_numeric:
            out.append("geographic distribution")
        if p.order is not None and p.order[0] == "y":
            out.append("ranking / top-N")
        if (
            p.agg[0] == "count"
            and not p.agg[1]
            and c.distinct_x >= 8
            and p.order is None
            and not YEARISH.search(xname)
        ):
            # the measure is the per-group count; its histogram is the
            # distribution (nvBench has no unnamed-mark query over a raw measure).
            out.append("distribution of one measure")
        return out
    if p.agg is None and p.y is not None:
        if p.chart == "Scatter" and c.x_numeric and c.y_numeric:
            out.append("correlation between measures")
        if p.chart == "Line" and c.y_numeric and (YEARISH.search(xname) or c.x_numeric):
            out.append("trend over time")
        if p.chart == "Bar" and c.y_numeric and not c.x_numeric:
            out.append("comparison across categories")
            if RANKWORDS.search(p.query) and p.order is not None:
                out.append("ranking / top-N")
            if len(p.tables) == 1 and _goal_column(c) is not None:
                out.append("single value against a target")
    return out


def _bin_castable(c: Cand) -> bool:
    typ = c.types[c.p.x]
    return typ in {"TEXT", "DATE", "DATETIME", "VARCHAR", "TIMESTAMP"} or "CHAR" in typ


# ---------------------------------------------------------------------------
# Table building
# ---------------------------------------------------------------------------


def _sqlite_table(c: Cand, *, all_columns: bool) -> pa.Table:
    p = c.p
    con = sqlite3.connect(_dbpath(p.db))
    con.text_factory = lambda b: b.decode("utf-8", errors="replace")
    try:
        if all_columns:
            alias, _tbl = p.tables[0]
            cols = list(p.columns[alias])
            sql = f'SELECT {", ".join(chr(34) + x + chr(34) for x in cols)} FROM "{p.tables[0][1]}"'
            names = cols
        else:
            names = [c.names[n] for n in c.needed]
            sql = (
                "SELECT "
                + ", ".join(f'"{a}"."{col}" AS "{c.names[(a, col)]}"' for a, col in c.needed)
                + f" FROM {_from_sql(p)}"
            )
        cur = con.execute(sql)
        rows = cur.fetchall()
    finally:
        con.close()
    columns: dict[str, list[Any]] = {n: [] for n in names}
    for row in rows:
        for i, n in enumerate(names):
            v = row[i]
            columns[n].append(None if v == "" else v)
    return pa.table(columns)


def _cast_date(table: pa.Table, col: str) -> pa.Table | None:
    con = duckdb.connect()
    con.register("t", table)
    try:
        ok = con.execute(
            f'SELECT count(*) FROM t WHERE "{col}" IS NOT NULL AND '
            f'try_cast("{col}" AS TIMESTAMP) IS NULL'
        ).fetchone()[0]
        if ok:
            return None
        others = [n for n in table.column_names if n != col]
        sel = ", ".join(f'"{n}"' for n in others)
        sel = (sel + ", " if sel else "") + f'try_cast("{col}" AS TIMESTAMP) AS "{col}"'
        out = con.execute(f"SELECT {sel} FROM t").to_arrow_table()
    finally:
        con.close()
    order = [n for n in table.column_names]
    return out.select(order)


def _with_json(table: pa.Table, extras: list[str], col: str = "details") -> pa.Table:
    keep = [n for n in table.column_names if n not in extras]
    con = duckdb.connect()
    con.register("t", table)
    quoted = ", ".join(f"'{n}', \"{n}\"" for n in extras)
    sel = ", ".join(f'"{n}"' for n in keep)
    out = con.execute(
        f"SELECT {sel}, json_object({quoted}) AS {col} FROM t"
    ).to_arrow_table()
    con.close()
    return out


def _add_sparse(table: pa.Table, n: int = 8) -> pa.Table:
    for i in range(n):
        table = table.append_column(f"unused_{i}", pa.array([None] * table.num_rows))
    return table


def _shape_table(c: Cand, shape: str) -> pa.Table | None:
    """Pin the table whose structure carries ``shape``.

    long: only the columns the request needs, one tidy narrow table.
    wide: the whole source table, six or more columns (single table only).
    nested: the needed columns plus one JSON ``details`` column that folds two
        or more other columns of the source table (single table only).
    wide_sparse: the needed columns plus eight all-null spreadsheet columns.
    """
    p = c.p
    if shape == "long":
        table = _sqlite_table(c, all_columns=False)
    elif shape == "wide":
        if len(p.tables) != 1 or c.ncols_table < 6:
            return None
        table = _sqlite_table(c, all_columns=True)
    elif shape == "nested":
        if len(p.tables) != 1 or c.unused < 2:
            return None
        full = _sqlite_table(c, all_columns=True)
        used = [c.names[n] for n in c.needed]
        extras = [n for n in full.column_names if n not in used]
        table = _with_json(full.select(used + extras), extras)
    elif shape == "wide_sparse":
        table = _add_sparse(_sqlite_table(c, all_columns=False), 8)
    else:
        raise ValueError(shape)
    if p.bin is not None:
        col = c.names[p.x]
        table = _cast_date(table, col)
    return table


# ---------------------------------------------------------------------------
# Frames
# ---------------------------------------------------------------------------


def _col(name: str) -> dict[str, Any]:
    return {"kind": "col", "name": name}


def _lit(value: Any) -> dict[str, Any]:
    return {"kind": "lit", "value": value}


def _filter(c: Cand) -> dict[str, Any] | None:
    exprs = []
    for alias, col, kind, val in c.p.preds:
        name = c.names[(alias, col)]
        if kind == "in":
            exprs.append({"kind": "in", "args": [_col(name), *[_lit(v) for v in val]]})
        else:
            exprs.append({"kind": kind, "args": [_col(name), _lit(val)]})
    if not exprs:
        return None
    if len(exprs) == 1:
        return exprs[0]
    return {"kind": c.p.conj, "args": exprs}


def _agg_item(c: Cand) -> dict[str, Any]:
    op, distinct, col = c.p.agg  # type: ignore[misc]
    if op == "count" and col is None:
        return {"name": "n", "op": "count"}
    field = c.names[col]  # type: ignore[index]
    if op == "count":
        if distinct:
            return {"name": f"distinct_{field}", "op": "count_distinct", "field": field}
        return {"name": "n", "op": "count"}
    name = {"mean": f"avg_{field}", "max": f"max_{field}", "min": f"min_{field}", "sum": f"{field}_sum"}[
        AGGOP[op]
    ]
    return {"name": name, "op": AGGOP[op], "field": field}


def y_name(c: Cand) -> str:
    if c.p.agg is not None:
        return _agg_item(c)["name"]
    return c.names[c.p.y]  # type: ignore[index]


def x_name(c: Cand) -> str:
    if c.p.bin is not None:
        return f"{c.names[c.p.x]}_{c.p.bin[1]}"
    return c.names[c.p.x]


def transform_of(c: Cand, intent: str) -> dict[str, Any]:
    t: dict[str, Any] = {}
    flt = _filter(c)
    if flt is not None:
        t["filter"] = flt
    if c.p.bin is not None:
        t["bin"] = [{"name": x_name(c), "field": c.names[c.p.x], "unit": c.p.bin[1]}]
        t["group_by"] = [x_name(c)]
        t["aggregate"] = [_agg_item(c)]
    elif c.p.group:
        t["group_by"] = [c.names[c.p.x]]
        t["aggregate"] = [_agg_item(c)]
    if c.p.order is not None:
        field = x_name(c) if c.p.order[0] == "x" else y_name(c)
        t["sort"] = [{"field": field, "dir": c.p.order[1], "nulls": "last"}]
    elif intent == "ranking / top-N":
        t["sort"] = [{"field": y_name(c), "dir": "desc", "nulls": "last"}]
    return t


def frame_of(c: Cand, intent: str) -> dict[str, Any]:
    x, y = x_name(c), y_name(c)
    if intent == "trend over time":
        chart, enc = "Line Chart", {"x": x, "y": y}
    elif intent == "comparison across categories":
        chart, enc = "Bar Chart", {"x": x, "y": y}
    elif intent == "part-to-whole":
        chart, enc = "Pie Chart", {"color": x, "size": y}
    elif intent == "ranking / top-N":
        chart, enc = "Lollipop Chart", {"x": x, "y": y}
    elif intent == "flow or transition between states":
        chart, enc = "Funnel Chart", {"y": x, "size": y}
    elif intent == "geographic distribution":
        chart, enc = "Choropleth", {"id": x, "color": y}
    elif intent == "correlation between measures":
        chart, enc = "Scatter Plot", {"x": x, "y": y}
    elif intent == "distribution of one measure":
        chart, enc = "Histogram", {"x": y}
    elif intent == "single value against a target":
        assert c.goal is not None
        chart, enc = "Bullet Chart", {"y": x, "x": y, "goal": c.goal}
    else:
        raise ValueError(intent)
    frame = {
        "chart_spec": {"chartType": chart, "encodings": enc, "baseSize": BASE},
        "x_chartagent": {"transform": transform_of(c, intent)},
    }
    InputFrame.model_validate(frame)
    return frame


def _goal_column(c: Cand) -> str | None:
    """A numeric column of the source table the request does not already use."""
    alias, tbl = c.p.tables[0]
    used = {c.names[n] for n in c.needed}
    typed = dict(_table_columns(c.p.db, tbl))
    for name in c.p.columns[alias]:
        if name not in used and any(s in typed[name] for s in ("INT", "REAL", "FLOAT", "NUM")):
            return name
    return None


def finalize(c: Cand, intent: str) -> Cand:
    """Carry the goal column of a single-value case in the pinned table."""
    if intent != "single value against a target":
        return c
    goal = _goal_column(c)
    assert goal is not None
    key = (c.p.tables[0][0], goal)
    needed = [*c.needed, key]
    names = {**c.names, key: goal}
    return replace(c, needed=needed, names=names, goal=goal)


# ---------------------------------------------------------------------------
# Execution (the real engine over the pinned parquet) and verification
# ---------------------------------------------------------------------------


def run_frame(path: Path, transform: dict[str, Any]) -> pa.Table:
    con = open_connection()
    try:
        register_source(con, str(path))
        types, schema = describe_source(con)
        table, _ = run_transform(
            con, transform, source_types=types, source_schema=schema, timeout=30.0
        )
        return table
    finally:
        con.close()


def _column(table: pa.Table, name: str) -> list[Any]:
    return table.column(name).to_pylist()


def check_result(table: pa.Table, ycol: str, expected: list[Any], *, ordered: str | None) -> str | None:
    if ycol not in table.column_names:
        return f"result has no column {ycol}"
    got = _norm_num(_column(table, ycol))
    want = _norm_num(expected)
    if got != want:
        return f"y values differ: got {got[:6]}.. want {want[:6]}.."
    if ordered is not None:
        raw = [v for v in _column(table, ycol) if v is not None]
        if raw != sorted(raw, reverse=(ordered == "desc")):
            return "result is not ordered as the frame sorts"
    return None


# ---------------------------------------------------------------------------
# Query rewrite: fluency only, both versions stored
# ---------------------------------------------------------------------------

TYPOS = {"forwhat": "for what", "aboutthe": "about the", "giveing": "giving"}
QWORDS = (
    "what", "which", "who", "whom", "whose", "where", "when", "how", "is", "are", "do", "does",
    "did", "can", "could", "will", "would", "have", "has", "was", "were",
)
MANUAL_REWRITE: dict[str, str] = {}


def rewrite(source_id: str, q: str) -> str:
    if source_id in MANUAL_REWRITE:
        return MANUAL_REWRITE[source_id]
    t = " ".join(q.replace("“", '"').replace("”", '"').replace("’", "'").split())
    for bad, good in TYPOS.items():
        t = re.sub(bad, good, t, flags=re.I)
    t = re.sub(r"\s+([,.?!;:])", r"\1", t)
    t = re.sub(r"\?\s*,\s*", "? ", t)
    t = re.sub(r"([,?!;])(?=[A-Za-z])", r"\1 ", t)
    t = re.sub(r"\.\s*,\s*", ". ", t)
    t = re.sub(r"\bi\b", "I", t)
    out = []
    for sentence in re.split(r"(?<=[.?!])\s+", t):
        sentence = sentence.strip()
        if not sentence:
            continue
        sentence = sentence[0].upper() + sentence[1:]
        first = re.match(r"[A-Za-z']+", sentence)
        asks = first is not None and first.group(0).lower() in QWORDS
        out.append(sentence.rstrip(".?! ") + ("?" if asks else "."))
    return " ".join(out)


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

# A request that carries one intent's cue word cannot be tagged with another
# intent: the judge reads the instruction against the tag.
CUES = (
    ("part-to-whole", re.compile(r"\b(proportion|percentage|share|ratio|breakdown)\b", re.I)),
    ("correlation between measures", re.compile(r"\b(correlation|relationship)\b", re.I)),
    ("trend over time", re.compile(r"\b(trend|tendency)\b", re.I)),
)
COMPARE = re.compile(r"\bcompar(e|ison)\b", re.I)

# Hand curation, by source ID. PICKS are tried first within their intent.
# AVOID drops a candidate whose wording or table reads badly on inspection.
PICKS: dict[str, list[str]] = {}
AVOID: set[str] = set()

CELL0_ORDER = [
    "flow or transition between states",
    "distribution of one measure",
    "single value against a target",
    "geographic distribution",
    "ranking / top-N",
    "correlation between measures",
    "trend over time",
    "part-to-whole",
    "comparison across categories",
]


def cue_ok(query: str, intent: str) -> bool:
    for owner, rx in CUES:
        if rx.search(query) and owner != intent:
            return False
    if COMPARE.search(query) and intent not in {
        "comparison across categories",
        "ranking / top-N",
        "geographic distribution",
    }:
        return False
    return True


def _h(source_id: str) -> str:
    return hashlib.sha256(source_id.encode()).hexdigest()


def draw_candidates(nv: dict[str, Any], used_keys: set[str], used_dbs: set[str]) -> list[Cand]:
    out = []
    for key, rec in nv.items():
        if _base_key(key) in used_keys or rec["db_id"] in used_dbs:
            continue
        for i in range(len(rec["nl_queries"])):
            c = make_candidate(key, i, rec)
            if c is not None and c.source_id not in AVOID:
                out.append(c)
    return out


class Taken:
    def __init__(self) -> None:
        self.keys: set[str] = set()
        self.dbs: collections.Counter[str] = collections.Counter()
        self.tables: collections.Counter[tuple[str, str]] = collections.Counter()

    def ok(self, c: Cand) -> bool:
        return (
            _base_key(c.p.key) not in self.keys
            and self.dbs[c.p.db] < DB_CAP
            and self.tables[(c.p.db, c.p.tables[0][1])] < 1
        )

    def add(self, c: Cand) -> None:
        self.keys.add(_base_key(c.p.key))
        self.dbs[c.p.db] += 1
        self.tables[(c.p.db, c.p.tables[0][1])] += 1


def select(
    cands: list[Cand], quotas: dict[str, int], taken: Taken, order: list[str], *, cell2: bool
) -> list[tuple[Cand, str]]:
    chosen: list[tuple[Cand, str]] = []
    for intent in order:
        need = quotas.get(intent, 0)
        pool = [
            c
            for c in cands
            if intent in c.intents and cue_ok(c.p.query, intent) and (not cell2 or cell2_ok(c))
        ]
        picks = PICKS.get(intent, [])
        pool.sort(key=lambda c: (c.source_id not in picks, _h(c.source_id)))
        got = 0
        for c in pool:
            if got == need:
                break
            if not taken.ok(c):
                continue
            if precheck(c, intent, cell2=cell2) is not None:
                continue
            taken.add(c)
            chosen.append((c, intent))
            got += 1
        if got != need:
            raise SystemExit(f"STOP: only {got} of {need} drawable for {intent!r} (cell2={cell2})")
    return chosen


def cell2_ok(c: Cand) -> bool:
    p = c.p
    return (
        p.group
        and p.agg is not None
        and p.bin is None
        and p.order is None
        and 4 <= c.distinct_x <= 24
        and not any(v is None for v in [c.distinct_x])
    )


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def cell2_intents(c: Cand) -> list[str]:
    out = []
    whole = re.search(r"\b(proportion|percentage|share|ratio|breakdown)\b", c.p.query, re.I)
    if c.p.chart == "Pie" or whole:
        out.append("part-to-whole")
    elif c.p.chart == "Line" or YEARISH.search(c.p.x[1]):
        out.append("trend over time")
    elif c.p.chart == "Bar":
        out.append("comparison across categories")
    return out


def _label(value: Any, yearish: bool) -> str:
    text = re.sub(r"\W+", "_", str(value)).strip("_")
    if not text:
        return ""
    if text[0].isdigit():
        text = ("y_" if yearish else "c_") + text
    return text


def build_cell2(c: Cand, intent: str, shape: str, path: Path) -> tuple[pa.Table, dict[str, Any], list[Any]] | None:
    con = sqlite3.connect(_dbpath(c.p.db))
    con.text_factory = lambda b: b.decode("utf-8", errors="replace")
    try:
        rows = con.execute(c.p.sql).fetchall()
    finally:
        con.close()
    if any(r[0] is None or r[1] is None for r in rows):
        return None
    yearish = bool(YEARISH.search(c.p.x[1]))
    rows = sorted(rows, key=lambda r: (str(type(r[0])), r[0]))
    labels = [_label(r[0], yearish) for r in rows]
    if "" in labels or len(set(labels)) != len(labels):
        return None
    values = [float(r[1]) if c.p.agg[0] == "avg" else int(r[1]) for r in rows]  # type: ignore[index]
    table = pa.table({lab: [val] for lab, val in zip(labels, values, strict=True)})
    if shape == "wide_sparse":
        table = _add_sparse(table, 6)
    xcol = re.sub(r"\W+", "_", c.p.x[1]).lower()
    ycol = "n" if c.p.agg[0] == "count" else re.sub(r"\W+", "_", f"{c.p.agg[0]}_{(c.p.agg[2] or ('', 'x'))[1]}").lower()  # type: ignore[index]
    if xcol == ycol:
        ycol = f"{ycol}_value"
    sql = (
        f'SELECT {xcol}, {ycol} FROM source UNPIVOT ({ycol} FOR {xcol} IN ({", ".join(labels)}))'
    )
    if intent == "trend over time":
        chart, enc = "Line Chart", {"x": xcol, "y": ycol}
    elif intent == "part-to-whole":
        chart, enc = "Pie Chart", {"color": xcol, "size": ycol}
    else:
        chart, enc = "Bar Chart", {"x": xcol, "y": ycol}
    frame = {
        "chart_spec": {"chartType": chart, "encodings": enc, "baseSize": BASE},
        "x_chartagent": {"transform": {"raw_sql": sql}},
    }
    InputFrame.model_validate(frame)
    return table, frame, [r[1] for r in rows]


def precheck(c: Cand, intent: str, *, cell2: bool) -> str | None:
    """Execute the frame over a long-shaped table before the case is drawn."""
    tmp = NVDIR / "precheck.parquet"
    try:
        if cell2:
            built = build_cell2(c, intent, "wide", tmp)
            if built is None:
                return "unusable group labels"
            table, frame, expected = built
        else:
            cc = finalize(c, intent)
            table = _sqlite_table(cc, all_columns=False)
            if cc.p.bin is not None:
                cast = _cast_date(table, cc.names[cc.p.x])
                if cast is None:
                    return "bin column does not parse as a date"
                table = cast
            frame = frame_of(cc, intent)
            expected = cc.gold_y if cc.p.bin is not None else cc.oracle_y
        pq.write_table(table, tmp)
        transform = frame["x_chartagent"]["transform"]
        result = run_frame(tmp, transform)
        ycol = _enc_y(frame, intent)
        ordered = None
        if not cell2 and transform.get("sort") and transform["sort"][0]["field"] == ycol:
            ordered = transform["sort"][0]["dir"]
        return check_result(result, ycol, expected, ordered=ordered)
    except Exception as exc:  # noqa: BLE001 - any failure disqualifies the candidate
        return f"{type(exc).__name__}: {exc}"


YCHANNEL = {
    "trend over time": "y",
    "comparison across categories": "y",
    "ranking / top-N": "y",
    "correlation between measures": "y",
    "part-to-whole": "size",
    "flow or transition between states": "size",
    "geographic distribution": "color",
    "distribution of one measure": "x",
    "single value against a target": "x",
}


def _enc_y(frame: dict[str, Any], intent: str) -> str:
    return frame["chart_spec"]["encodings"][YCHANNEL[intent]]


def assign_shapes(
    chosen: list[tuple[Cand, str]], quotas: dict[str, int], *, cell2: bool
) -> dict[str, str]:
    order = sorted(chosen, key=lambda ci: _h(ci[0].source_id))
    out: dict[str, str] = {}
    if cell2:
        for n, (c, _i) in enumerate(order):
            out[c.source_id] = "wide" if n < quotas["wide"] else "wide_sparse"
        return out

    def single(c: Cand) -> bool:
        return len(c.p.tables) == 1

    def unused(c: Cand, intent: str) -> int:
        cc = finalize(c, intent)
        alias = cc.p.tables[0][0]
        return cc.ncols_table - sum(1 for a, _ in cc.needed if a == alias)

    nested = [ci for ci in order if single(ci[0]) and unused(*ci) >= 2][: quotas["nested"]]
    for c, _i in nested:
        out[c.source_id] = "nested"
    wide_ok = [
        ci
        for ci in order
        if ci[0].source_id not in out and single(ci[0]) and ci[0].ncols_table >= 6
    ][: quotas["wide"]]
    for c, _i in wide_ok:
        out[c.source_id] = "wide"
    rest = [ci for ci in order if ci[0].source_id not in out]
    for n, (c, _i) in enumerate(rest):
        out[c.source_id] = "wide_sparse" if n < quotas["wide_sparse"] else "long"
    got = collections.Counter(out.values())
    if dict(got) != {k: v for k, v in quotas.items() if v}:
        raise SystemExit(f"STOP: shape quotas not met: {dict(got)} vs {quotas}")
    return out


def build_all(
    cell0: list[tuple[Cand, str]],
    cell2: list[tuple[Cand, str]],
    shapes0: dict[str, str],
    shapes2: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, tuple[list[Any], str]]]:
    DATA.mkdir(parents=True, exist_ok=True)
    for stale in DATA.glob("nv*.parquet"):
        stale.unlink()
    rank = {name: n for n, name in enumerate(CELL0_ORDER)}
    jobs = sorted(
        [(0, c, i) for c, i in cell0] + [(2, c, i) for c, i in cell2],
        key=lambda j: (j[0], rank[j[2]], _h(j[1].source_id)),
    )
    records: list[dict[str, Any]] = []
    expected: dict[str, tuple[list[Any], str]] = {}
    for n, (cell, c, intent) in enumerate(jobs, start=1):
        rid = f"nv{n:03d}"
        path = DATA / f"{rid}.parquet"
        if cell == 2:
            shape = shapes2[c.source_id]
            built = build_cell2(c, intent, shape, path)
            assert built is not None
            table, frame, exp = built
        else:
            shape = shapes0[c.source_id]
            cc = finalize(c, intent)
            maybe = _shape_table(cc, shape)
            assert maybe is not None, (c.source_id, shape)
            table = maybe
            frame = frame_of(cc, intent)
            exp = cc.gold_y if cc.p.bin is not None else cc.oracle_y
        pq.write_table(table, path)
        rewritten = rewrite(c.source_id, c.p.query)
        records.append(
            {
                "id": rid,
                "source": "nvbench1",
                "source_id": c.source_id,
                "query_original": c.p.query,
                "query_rewritten": rewritten,
                "instruction": rewritten,
                "stratum": "common_path",
                "cell": cell,
                "intent": intent,
                "shape": shape,
                "dataset_path": f"eval/data/{rid}.parquet",
                "dataset_sha256": _sha(path),
                "reference_frame": frame,
                "expected_outcome": "hit",
            }
        )
        expected[rid] = (exp, intent)
    return records, expected


def verify(
    records: list[dict[str, Any]],
    expected: dict[str, tuple[list[Any], str]],
    nv: dict[str, Any],
    used_keys: set[str],
    used_dbs: set[str],
) -> None:
    errors: list[str] = []
    ids = [r["id"] for r in records]
    if len(ids) != len(set(ids)) or len(records) != 102:
        errors.append(f"expected 102 unique ids, got {len(records)}")
    cell = collections.Counter(r["cell"] for r in records)
    if dict(cell) != {0: 90, 2: 12}:
        errors.append(f"cells {dict(cell)}")
    for c_, quota in ((0, CELL0_INTENTS), (2, CELL2_INTENTS)):
        got = collections.Counter(r["intent"] for r in records if r["cell"] == c_)
        if dict(got) != quota:
            errors.append(f"cell {c_} intents {dict(got)} != {quota}")
    for c_, quota in ((0, CELL0_SHAPES), (2, CELL2_SHAPES)):
        got = collections.Counter(r["shape"] for r in records if r["cell"] == c_)
        if dict(got) != quota:
            errors.append(f"cell {c_} shapes {dict(got)} != {quota}")
    seen: set[tuple[str, str]] = set()
    for r in records:
        path = REPO / r["dataset_path"]
        if _sha(path) != r["dataset_sha256"]:
            errors.append(f'{r["id"]}: dataset sha256 mismatch')
        if r["dataset_path"].startswith("corpus/"):
            errors.append(f'{r["id"]}: reuses corpus data')
        key = r["source_id"].rsplit("@", 1)[0]
        if _base_key(key) in used_keys or nv[key]["db_id"] in used_dbs:
            errors.append(f'{r["id"]}: shares a source with corpus-prereg-v1')
        if CHARTWORDS.search(r["query_rewritten"]):
            errors.append(f'{r["id"]}: rewritten query names a chart type')
        pair = (r["instruction"], r["dataset_sha256"])
        if pair in seen:
            errors.append(f'{r["id"]}: duplicate (instruction, dataset)')
        seen.add(pair)
        InputFrame.model_validate(r["reference_frame"])
        exp, intent = expected[r["id"]]
        transform = r["reference_frame"]["x_chartagent"]["transform"]
        try:
            result = run_frame(path, transform)
            ycol = _enc_y(r["reference_frame"], intent)
            ordered = None
            if transform.get("sort") and transform["sort"][0]["field"] == ycol:
                ordered = transform["sort"][0]["dir"]
            problem = check_result(result, ycol, exp, ordered=ordered)
        except Exception as exc:  # noqa: BLE001
            problem = f"{type(exc).__name__}: {exc}"
        if problem:
            errors.append(f'{r["id"]}: frame does not reproduce the gold: {problem}')
    if errors:
        raise SystemExit("verification failed:\n  " + "\n  ".join(errors))


def main() -> None:
    fetch()
    nv = load_nvbench()
    used_keys, used_dbs = prereg_exclusions(nv)
    leftovers = unnamed_leftovers(nv, used_keys)
    if len(leftovers) < MIN_LEFTOVER:
        raise SystemExit(
            f"STOP: {len(leftovers)} unnamed-mark leftovers after excluding "
            f"corpus-prereg-v1, need {MIN_LEFTOVER}. Do not shrink n."
        )
    cands = draw_candidates(nv, used_keys, used_dbs)
    taken = Taken()
    cell0 = select(cands, CELL0_INTENTS, taken, CELL0_ORDER, cell2=False)
    pool2 = [replace(c, intents=cell2_intents(c)) for c in cands if cell2_ok(c)]
    cell2 = select(pool2, CELL2_INTENTS, taken, list(CELL2_INTENTS), cell2=True)
    shapes0 = assign_shapes(cell0, CELL0_SHAPES, cell2=False)
    shapes2 = assign_shapes(cell2, CELL2_SHAPES, cell2=True)
    records, expected = build_all(cell0, cell2, shapes0, shapes2)
    verify(records, expected, nv, used_keys, used_dbs)
    prereg = json.loads(CORPUS_PREREG.read_text())
    doc = {
        "part": "nvbench",
        "ticket": 284,
        "flint_version": prereg["flint_version"],
        "fixture_commit": prereg["fixture_commit"],
        "nvbench": {"repo": NV_REPO, "commit": NV_COMMIT, "sha256": NV_FILES},
        "leftover_unnamed_queries": len(leftovers),
        "matrix": {"common_path": {"0": 90, "2": 12}},
        "intent_counts": {"cell0": CELL0_INTENTS, "cell2": CELL2_INTENTS},
        "shape_counts": {"cell0": CELL0_SHAPES, "cell2": CELL2_SHAPES},
        "requests": records,
    }
    OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(REPO)} with {len(records)} cases")


if __name__ == "__main__":
    main()
