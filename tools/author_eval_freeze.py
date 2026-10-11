"""One-shot assembly of eval/pre-registration.json (issue #287, spec #282, ADR-0029).

Combines the three partial files (eval/cases-nvbench.json, cases-authored-1.json,
cases-cell4.json) into the public 150, authors the 30-case hold-out pool and its
pinned tables (eval/data/holdout-*.parquet), draws the 30 smoke IDs and the two
permutations from recorded seeds, and writes eval/pre-registration.json and
eval/NOTICE. The authoring note eval/pre-registration.md is written by hand.

Not a library surface; adds nothing to chartagent.__all__. The partial files are
inputs only and are not part of the freeze. Re-running after the
eval-benchmark-v1 tag is cut is a freeze break.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from chartagent.frame.input import InputFrame
from chartagent.transform.engine import open_connection
from chartagent.transform.raw_sql import validate_raw_sql

REPO = Path(__file__).resolve().parents[1]
EVAL = REPO / "eval"
DATA = EVAL / "data"
OUT = EVAL / "pre-registration.json"
NOTICE = EVAL / "NOTICE"
BASE = {"width": 640, "height": 400}
AUTHORED_ON = "2026-10-11"
SEEDS = {
    "smoke_ids": 287001,
    "holdout_permutation": 287002,
    "human_calibration_permutation": 287003,
}
FIELDS = (
    "id",
    "instruction",
    "source",
    "source_id",
    "query_original",
    "query_rewritten",
    "stratum",
    "cell",
    "cell_family",
    "intent",
    "shape",
    "dataset_path",
    "dataset_sha256",
    "reference_frame",
    "expressible_if",
    "ambiguity_degree",
    "expected_outcome",
    "expected_bucket",
)
OVERLAP = "set overlap / intersection structure"


def _load(name: str) -> dict[str, Any]:
    return json.loads((EVAL / name).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _normal(raw: dict[str, Any]) -> dict[str, Any]:
    return {field: raw.get(field) for field in FIELDS}


# --------------------------------------------------------------------- hold-out


def _write(name: str, table: pa.Table) -> tuple[str, str]:
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / f"{name}.parquet"
    pq.write_table(table, path)
    return f"eval/data/{name}.parquet", hashlib.sha256(path.read_bytes()).hexdigest()


def _wide(table: pa.Table, extra: int) -> pa.Table:
    """Pad a table with unrelated numeric columns so it reads as wide."""
    n = table.num_rows
    for k in range(extra):
        table = table.append_column(
            f"metric_{k + 1:02d}", pa.array([(i * (k + 3)) % 17 + k for i in range(n)])
        )
    return table


def _sparse(table: pa.Table, extra: int) -> pa.Table:
    """Pad a table with mostly-null columns."""
    n = table.num_rows
    for k in range(extra):
        table = table.append_column(
            f"extra_{k + 1:02d}",
            pa.array(
                [float(i + k) if (i + k) % 9 == 0 else None for i in range(n)],
                type=pa.float64(),
            ),
        )
    return table


def _nested(table: pa.Table, name: str, make: Any) -> pa.Table:
    return table.append_column(
        name, pa.array([json.dumps(make(i)) for i in range(table.num_rows)])
    )


def _frame(
    chart: str, encodings: dict[str, str], transform: dict[str, Any]
) -> dict[str, Any]:
    frame = {
        "chart_spec": {"chartType": chart, "encodings": encodings, "baseSize": BASE},
        "x_chartagent": {"transform": transform},
    }
    InputFrame.model_validate(frame)
    return frame


def _group(by: str, name: str, op: str, field: str | None = None, **more: Any) -> dict:
    agg: dict[str, Any] = {"name": name, "op": op}
    if field is not None:
        agg["field"] = field
    return {"group_by": [by], "aggregate": [agg], **more}


def _desc(field: str) -> list[dict[str, str]]:
    return [{"field": field, "dir": "desc", "nulls": "last"}]


def _eq(col: str, value: Any) -> dict[str, Any]:
    return {
        "kind": "eq",
        "args": [{"kind": "col", "name": col}, {"kind": "lit", "value": value}],
    }


def _check_sql(table: pa.Table, sql: str) -> None:
    con = open_connection()
    try:
        validate_raw_sql(con, sql)
    finally:
        con.close()
    probe = duckdb.connect()
    try:
        probe.register("source", table)
        assert probe.execute(sql).fetchall(), sql
    finally:
        probe.close()


def _check_columns(table: pa.Table, frame: dict[str, Any] | None) -> None:
    """Every name the frame uses is a column or something the transform makes."""
    if frame is None:
        return
    cols = set(table.schema.names)
    transform = frame["x_chartagent"]["transform"]
    if "raw_sql" in transform:
        return
    made = {a["name"] for a in transform.get("aggregate", [])}
    for name in transform.get("group_by", []):
        assert name in cols, name
    for agg in transform.get("aggregate", []):
        assert agg.get("field") is None or agg["field"] in cols, agg
    for key in transform.get("sort", []):
        assert key["field"] in cols | made, key
    for value in frame["chart_spec"]["encodings"].values():
        assert value in cols | made, value


def _months(n: int, year: int = 2024) -> list[datetime.date]:
    return [datetime.date(year + i // 12, i % 12 + 1, 1) for i in range(n)]


def _holdout_specs() -> list[dict[str, Any]]:
    """Thirty authored hold-out cases: ids ho-01..ho-30."""
    specs: list[dict[str, Any]] = []

    def add(
        key: str,
        table: pa.Table,
        original: str,
        rewritten: str,
        *,
        stratum: str,
        cell: int,
        intent: str,
        shape: str,
        frame: dict[str, Any] | None,
        family: str | None = None,
        expressible: list[str] | None = None,
        degree: int | None = None,
        sql: str | None = None,
    ) -> None:
        if sql is not None:
            _check_sql(table, sql)
        _check_columns(table, frame)
        specs.append(
            {
                "key": key,
                "table": table,
                "original": original,
                "rewritten": rewritten,
                "stratum": stratum,
                "cell": cell,
                "intent": intent,
                "shape": shape,
                "frame": frame,
                "family": family,
                "expressible": expressible,
                "degree": degree,
            }
        )

    com, adv = "common_path", "adversarial"

    # ---- cell 0, common path (15)
    add(
        "ho-01",
        pa.table(
            {
                "month": _months(12),
                "visits": [4100 + 230 * ((i * 5) % 9) + 60 * i for i in range(12)],
            }
        ),
        "how have monthly website visits changed over the past year",
        "How have monthly website visits changed over the past year?",
        stratum=com, cell=0, intent="trend over time", shape="long",
        frame=_frame("Line Chart", {"x": "month", "y": "visits"}, {}),
    )  # fmt: skip
    depts = ["Sales", "Support", "Finance", "Legal", "Research", "Design"]
    add(
        "ho-02",
        pa.table(
            {
                "department": [depts[i % 6] for i in range(60)],
                "salary": [38000 + (i * 2713) % 31000 + 1500 * (i % 6) for i in range(60)],
            }
        ),
        "compare the average salary of each department",
        "Compare the average salary of each department.",
        stratum=com, cell=0, intent="comparison across categories", shape="long",
        frame=_frame(
            "Bar Chart",
            {"x": "department", "y": "avg_salary"},
            _group("department", "avg_salary", "mean", "salary"),
        ),
    )  # fmt: skip
    add(
        "ho-03",
        pa.table(
            {
                "order_id": [f"ord-{i:04d}" for i in range(80)],
                "payment_method": [
                    ("card", "card", "card", "transfer", "wallet", "cash")[(i * 7) % 6]
                    for i in range(80)
                ],
                "amount": [12 + (i * 37) % 140 for i in range(80)],
            }
        ),
        "what share of orders does each payment method account for",
        "What share of orders does each payment method account for?",
        stratum=com, cell=0, intent="part-to-whole", shape="long",
        frame=_frame(
            "Pie Chart",
            {"color": "payment_method", "size": "n"},
            _group("payment_method", "n", "count"),
        ),
    )  # fmt: skip
    add(
        "ho-04",
        pa.table(
            {
                "parcel": [f"p{i:03d}" for i in range(90)],
                "delivery_days": [1 + (i * 7) % 5 + (i % 11 == 0) * 4 for i in range(90)],
            }
        ),
        "show the distribution of delivery times",
        "Show the distribution of delivery times.",
        stratum=com, cell=0, intent="distribution of one measure", shape="long",
        frame=_frame("Histogram", {"x": "delivery_days"}, {}),
    )  # fmt: skip
    add(
        "ho-05",
        pa.table(
            {
                "week": list(range(1, 31)),
                "ad_spend": [800 + 55 * ((i * 7) % 13) for i in range(30)],
                "sales": [9000 + 410 * ((i * 7) % 13) + 90 * (i % 4) for i in range(30)],
            }
        ),
        "is there a relationship between advertising spend and sales",
        "Is there a relationship between advertising spend and sales?",
        stratum=com, cell=0, intent="correlation between measures", shape="long",
        frame=_frame("Scatter Plot", {"x": "ad_spend", "y": "sales"}, {}),
    )  # fmt: skip
    cities = [
        "Lisbon", "Porto", "Braga", "Faro", "Coimbra", "Aveiro", "Evora", "Viseu",
        "Leiria", "Setubal", "Funchal", "Guarda", "Beja", "Tomar", "Sines",
        "Lagos", "Silves", "Mafra", "Cascais", "Sintra",
    ]  # fmt: skip
    add(
        "ho-06",
        pa.table(
            {
                "city": cities,
                "population": [545 - 23 * i + (i * i) % 17 for i in range(20)],
            }
        ),
        "which five cities have the largest population",
        "Which five cities have the largest population?",
        stratum=com, cell=0, intent="ranking / top-N", shape="long",
        frame=_frame(
            "Bar Chart",
            {"x": "city", "y": "population"},
            {"sort": _desc("population"), "limit": {"count": 5, "offset": 0}},
        ),
    )  # fmt: skip
    add(
        "ho-07",
        _wide(
            pa.table(
                {
                    "year": list(range(2010, 2022)),
                    "rainfall_mm": [610 + 35 * ((i * 5) % 8) - 12 * i for i in range(12)],
                }
            ),
            9,
        ),
        "show total rainfall by year",
        "Show total rainfall by year.",
        stratum=com, cell=0, intent="trend over time", shape="wide",
        frame=_frame(
            "Line Chart",
            {"x": "year", "y": "rainfall_total"},
            _group("year", "rainfall_total", "sum", "rainfall_mm"),
        ),
    )  # fmt: skip
    add(
        "ho-08",
        _wide(
            pa.table(
                {
                    "class_name": [("4A", "4B", "4C", "5A", "5B")[i % 5] for i in range(50)],
                    "exam_score": [48 + (i * 13) % 47 for i in range(50)],
                }
            ),
            8,
        ),
        "compare the average exam score of each class",
        "Compare the average exam score of each class.",
        stratum=com, cell=0, intent="comparison across categories", shape="wide",
        frame=_frame(
            "Bar Chart",
            {"x": "class_name", "y": "avg_score"},
            _group("class_name", "avg_score", "mean", "exam_score"),
        ),
    )  # fmt: skip
    add(
        "ho-09",
        _wide(
            pa.table(
                {
                    "ticket": [f"t-{i:03d}" for i in range(70)],
                    "priority": [
                        ("low", "low", "medium", "medium", "medium", "high", "urgent")[
                            (i * 3) % 7
                        ]
                        for i in range(70)
                    ],
                }
            ),
            10,
        ),
        "what proportion of tickets does each priority level have",
        "What proportion of tickets does each priority level have?",
        stratum=com, cell=0, intent="part-to-whole", shape="wide",
        frame=_frame(
            "Pie Chart",
            {"color": "priority", "size": "n"},
            _group("priority", "n", "count"),
        ),
    )  # fmt: skip
    add(
        "ho-10",
        _wide(
            pa.table(
                {
                    "applicant": [f"a{i:03d}" for i in range(100)],
                    "stage": [
                        (
                            "applied", "applied", "applied", "screened",
                            "screened", "interviewed", "offered",
                        )[(i * 5) % 7]
                        for i in range(100)
                    ],
                }
            ),
            7,
        ),
        "show how many applicants are at each stage of the hiring process",
        "Show how many applicants are at each stage of the hiring process.",
        stratum=com, cell=0, intent="flow or transition between states", shape="wide",
        frame=_frame(
            "Funnel Chart",
            {"y": "stage", "size": "n"},
            _group("stage", "n", "count"),
        ),
    )  # fmt: skip
    add(
        "ho-11",
        _wide(
            pa.table(
                {
                    "customer": [f"c{i:03d}" for i in range(75)],
                    "country": [
                        ("Germany", "France", "Spain", "Italy", "Poland", "Austria")[
                            (i * 5) % 6
                        ]
                        for i in range(75)
                    ],
                }
            ),
            8,
        ),
        "map the number of customers in each country",
        "Map the number of customers in each country.",
        stratum=com, cell=0, intent="geographic distribution", shape="wide",
        frame=_frame(
            "Choropleth",
            {"id": "country", "color": "n"},
            _group("country", "n", "count"),
        ),
    )  # fmt: skip
    add(
        "ho-12",
        _nested(
            pa.table(
                {
                    "store": [f"store {c}" for c in "ABCDEFGH"],
                    "sales": [210, 340, 125, 410, 290, 180, 365, 255],
                    "target": [250, 300, 150, 400, 300, 200, 350, 250],
                }
            ),
            "details",
            lambda i: {"manager": f"mgr-{i}", "opened": 2005 + i * 2},
        ),
        "compare each store's sales with its target",
        "Compare each store's sales with its target.",
        stratum=com, cell=0, intent="single value against a target", shape="nested",
        frame=_frame(
            "Bullet Chart", {"y": "store", "x": "sales", "goal": "target"}, {}
        ),
    )  # fmt: skip
    add(
        "ho-13",
        _nested(
            pa.table(
                {
                    "bug_id": [f"bug-{i:03d}" for i in range(60)],
                    "module": [
                        ("auth", "billing", "search", "export", "ui")[(i * 3) % 5]
                        for i in range(60)
                    ],
                    "status": [("open", "closed", "closed", "open")[i % 4] for i in range(60)],
                }
            ),
            "reporter",
            lambda i: {"team": ("qa", "dev", "ops")[i % 3], "severity": i % 4},
        ),
        "how many bugs are still open in each module",
        "How many bugs are still open in each module?",
        stratum=com, cell=0, intent="comparison across categories", shape="nested",
        frame=_frame(
            "Bar Chart",
            {"x": "module", "y": "n"},
            {**_group("module", "n", "count"), "filter": _eq("status", "open")},
        ),
    )  # fmt: skip
    add(
        "ho-14",
        _sparse(
            pa.table(
                {
                    "month": [("jan", "feb", "mar", "apr", "may", "jun")[i % 6] for i in range(24)],
                    "signups": [30 + (i * 11) % 45 for i in range(24)],
                }
            ),
            9,
        ),
        "plot the number of signups per month",
        "Plot the number of signups per month.",
        stratum=com, cell=0, intent="trend over time", shape="wide_sparse",
        frame=_frame(
            "Line Chart",
            {"x": "month", "y": "signups_total"},
            _group("month", "signups_total", "sum", "signups"),
        ),
    )  # fmt: skip
    add(
        "ho-15",
        _sparse(
            pa.table(
                {
                    "flat": [f"flat-{i:02d}" for i in range(36)],
                    "area_sqm": [38 + (i * 7) % 60 for i in range(36)],
                    "price": [118000 + 2300 * ((i * 7) % 60) + 900 * (i % 5) for i in range(36)],
                }
            ),
            9,
        ),
        "do larger flats sell for more",
        "Do larger flats sell for more?",
        stratum=com, cell=0, intent="correlation between measures", shape="wide_sparse",
        frame=_frame("Scatter Plot", {"x": "area_sqm", "y": "price"}, {}),
    )  # fmt: skip

    # ---- cell 2, common path (3): one-row wide extracts, then UNPIVOT
    years = [f"y_{y}" for y in range(2018, 2024)]
    sales_row = pa.table({y: [900 + 85 * i] for i, y in enumerate(years)})
    sql = (
        "SELECT year, sales FROM source "
        f"UNPIVOT (sales FOR year IN ({', '.join(years)}))"
    )
    add(
        "ho-16", sales_row,
        "plot the sales for each year",
        "Plot the sales for each year.",
        stratum=com, cell=2, intent="trend over time", shape="wide",
        frame=_frame("Line Chart", {"x": "year", "y": "sales"}, {"raw_sql": sql}),
        sql=sql,
    )  # fmt: skip
    staff_cols = ["Billing", "Claims", "Legal", "Underwriting", "Records", "Audit"]
    staff_row = pa.table(
        {c: [12 + 5 * ((i * 3) % 7)] for i, c in enumerate(staff_cols)}
    )
    sql = (
        "SELECT unit, staff FROM source "
        f"UNPIVOT (staff FOR unit IN ({', '.join(staff_cols)}))"
    )
    add(
        "ho-17", staff_row,
        "how many staff does each unit have",
        "How many staff does each unit have?",
        stratum=com, cell=2, intent="comparison across categories", shape="wide",
        frame=_frame("Bar Chart", {"x": "unit", "y": "staff"}, {"raw_sql": sql}),
        sql=sql,
    )  # fmt: skip
    areas = ["Roads", "Schools", "Parks", "Transit", "Housing"]
    budget_row = _sparse(
        pa.table({a: [100 + 40 * ((i * 2) % 5)] for i, a in enumerate(areas)}), 8
    )
    sql = (
        "SELECT area, budget FROM source "
        f"UNPIVOT (budget FOR area IN ({', '.join(areas)}))"
    )
    add(
        "ho-18", budget_row,
        "break the city budget down by area",
        "Break the city budget down by area.",
        stratum=com, cell=2, intent="part-to-whole", shape="wide_sparse",
        frame=_frame("Pie Chart", {"color": "area", "size": "budget"}, {"raw_sql": sql}),
        sql=sql,
    )  # fmt: skip

    # ---- cell 3, common path (1): silent row drop
    add(
        "ho-19",
        pa.table(
            {
                "clinic": [f"clinic-{i:03d}" for i in range(1, 171)],
                "patients": [300 + (i * 4231) % 2700 for i in range(170)],
            }
        ),
        "show the number of patients seen at every clinic",
        "Show the number of patients seen at every clinic.",
        stratum=com, cell=3, intent="comparison across categories", shape="long",
        frame=_frame("Bar Chart", {"x": "clinic", "y": "patients"}, {}),
        family="silent_row_drop",
    )  # fmt: skip

    # ---- cell 4, common path (5): (ii) x2, (iii), (iv) x2
    add(
        "ho-20",
        pa.table(
            {
                "region": [("north", "south", "east", "west")[i % 4] for i in range(48)],
                "quarter": [f"q{i // 4 % 4 + 1}" for i in range(48)],
                "revenue": [5000 + (i * 977) % 4100 for i in range(48)],
                "profit": [600 + (i * 331) % 900 for i in range(48)],
            }
        ),
        "which region performs best",
        "Which region performs best?",
        stratum=com, cell=4, intent="ranking / top-N", shape="long",
        frame=_frame(
            "Bar Chart",
            {"x": "region", "y": "revenue_total"},
            _group("region", "revenue_total", "sum", "revenue", sort=_desc("revenue_total")),
        ),
        family="ii", degree=2,
    )  # fmt: skip
    add(
        "ho-21",
        pa.table(
            {
                "team": [("Hawks", "Otters", "Wolves", "Lynx", "Bears")[i % 5] for i in range(40)],
                "season": [2016 + i // 5 for i in range(40)],
                "wins": [8 + (i * 7) % 14 for i in range(40)],
                "attendance": [11000 + (i * 719) % 6000 for i in range(40)],
            }
        ),
        "compare the teams",
        "Compare the teams.",
        stratum=com, cell=4, intent="comparison across categories", shape="long",
        frame=_frame(
            "Bar Chart",
            {"x": "team", "y": "wins_total"},
            _group("team", "wins_total", "sum", "wins"),
        ),
        family="ii", degree=2,
    )  # fmt: skip
    add(
        "ho-22",
        pa.table(
            {
                "month": _months(12),
                "plan": [("free", "pro", "team")[i % 3] for i in range(12)],
                "signups": [55 + (i * 17) % 80 for i in range(12)],
            }
        ),
        "show monthly signups and tell me which plan is most popular",
        "Show monthly signups and tell me which plan is most popular.",
        stratum=com, cell=4, intent="trend over time", shape="long",
        frame=_frame(
            "Line Chart",
            {"x": "month", "y": "signups_total"},
            _group("month", "signups_total", "sum", "signups"),
        ),
        family="iii",
    )  # fmt: skip
    dirty = pa.table(
        {
            " Reg. Code ": [("N-01", "S-02", "E-03", "W-04")[i % 4] for i in range(32)],
            "Amt $ (k)": [14 + (i * 9) % 31 for i in range(32)],
            "yr-mo": [f"2024-{i % 12 + 1:02d}" for i in range(32)],
        }
    )
    dirty = _nested(
        dirty, "meta{}", lambda i: {"src": f"batch-{i % 3}", "ok": i % 5 != 0}
    )
    add(
        "ho-23", dirty,
        "total the amounts for each region code",
        "Total the amounts for each region code.",
        stratum=com, cell=4, intent="comparison across categories", shape="nested",
        frame=_frame(
            "Bar Chart",
            {"x": " Reg. Code ", "y": "amount_total"},
            _group(" Reg. Code ", "amount_total", "sum", "Amt $ (k)"),
        ),
        family="iv",
    )  # fmt: skip
    dirty_wide = pa.table(
        {"dt ": _months(10)}
        | {"Unnamed: 1": [100 + 20 * ((i * 3) % 7) for i in range(10)]}
        | {f"Unnamed: {k}": [(i * k) % 13 for i in range(10)] for k in range(2, 9)}
    )
    add(
        "ho-24", dirty_wide,
        "plot the totals over time",
        "Plot the totals over time.",
        stratum=com, cell=4, intent="trend over time", shape="wide",
        frame=_frame(
            "Line Chart",
            {"x": "dt ", "y": "totals_sum"},
            _group("dt ", "totals_sum", "sum", "Unnamed: 1"),
        ),
        family="iv",
    )  # fmt: skip

    # ---- adversarial (6): cell 1 x1, cell 2 x2, cell 4 x3 (i, ii, iii)
    members = [f"member-{i:02d}" for i in range(30)]
    skills = ["backend", "frontend", "data"]
    rows = [
        (m, skills[j])
        for i, m in enumerate(members)
        for j in range(3)
        if (i * (j + 1) + j) % 4 != 0
    ]
    add(
        "ho-25",
        pa.table({"member": [r[0] for r in rows], "team": [r[1] for r in rows]}),
        "which members belong to the backend and frontend teams but not the data team",
        "Which members belong to the backend and frontend teams but not the data team?",
        stratum=adv, cell=1, intent=OVERLAP, shape="long",
        frame=None, expressible=["Venn", "Euler", "UpSet"],
    )  # fmt: skip
    baskets = pa.table(
        {
            "order_id": [f"o{i:03d}" for i in range(40)],
            "basket": [
                json.dumps(
                    {
                        "tier": ("bronze", "silver", "gold")[i % 3],
                        "items": 1 + (i * 5) % 9,
                    }
                )
                for i in range(40)
            ],
        }
    )
    sql = (
        "SELECT json_extract_string(basket, '$.tier') AS tier, "
        "avg(CAST(json_extract_string(basket, '$.items') AS DOUBLE)) AS avg_items "
        "FROM source GROUP BY tier ORDER BY tier"
    )
    add(
        "ho-26", baskets,
        "what is the average basket size for each customer tier",
        "What is the average basket size for each customer tier?",
        stratum=adv, cell=2, intent="comparison across categories", shape="nested",
        frame=_frame("Bar Chart", {"x": "tier", "y": "avg_items"}, {"raw_sql": sql}),
        sql=sql,
    )  # fmt: skip
    periods = ["p1", "p2", "p3", "p4", "p5"]
    shops = pa.table(
        {"shop": [f"shop {c}" for c in "ABCDEFGH"]}
        | {
            p: [200 + 30 * ((i + k * 2) % 6) for i in range(8)]
            for k, p in enumerate(periods)
        }
    )
    sql = (
        "SELECT shop, period, sales FROM source "
        f"UNPIVOT (sales FOR period IN ({', '.join(periods)}))"
    )
    add(
        "ho-27", shops,
        "plot each shop's sales by period",
        "Plot each shop's sales by period.",
        stratum=adv, cell=2, intent="trend over time", shape="wide",
        frame=_frame(
            "Line Chart", {"x": "period", "y": "sales", "color": "shop"}, {"raw_sql": sql}
        ),
        sql=sql,
    )  # fmt: skip
    divisions = ["ops", "tech", "people"]
    add(
        "ho-28",
        pa.table(
            {
                "division": [divisions[i % 3] for i in range(18)],
                "team": [f"{divisions[i % 3]}-{i // 3 + 1}" for i in range(18)],
                "expense": [7 + (i * 13) % 29 for i in range(18)],
            }
        ),
        "draw a sunburst of expenses by division and team",
        "Draw a sunburst of expenses by division and team.",
        stratum=adv, cell=4, intent="part-to-whole", shape="long",
        frame=_frame(
            "Stacked Bar Chart",
            {"x": "division", "y": "expense", "color": "team"},
            {},
        ),
        family="i",
    )  # fmt: skip
    add(
        "ho-29",
        pa.table(
            {
                "month": [f"2024-{i % 12 + 1:02d}" for i in range(48)],
                "region": [("north", "south", "east", "west")[i % 4] for i in range(48)],
                "product": [("A", "B", "C")[i % 3] for i in range(48)],
                "revenue": [700 + (i * 53) % 900 for i in range(48)],
                "cost": [400 + (i * 29) % 500 for i in range(48)],
                "units": [20 + (i * 7) % 40 for i in range(48)],
                "returns": [i % 6 for i in range(48)],
            }
        ),
        "give me the key numbers",
        "Give me the key numbers.",
        stratum=adv, cell=4, intent="comparison across categories", shape="long",
        frame=_frame(
            "Bar Chart",
            {"x": "region", "y": "revenue_total"},
            _group("region", "revenue_total", "sum", "revenue"),
        ),
        family="ii", degree=4,
    )  # fmt: skip
    wh = _nested(
        pa.table(
            {
                "warehouse": [
                    ("Leeds", "Derby", "Hull", "York")[i % 4] for i in range(40)
                ],
                "week": [i // 4 + 1 for i in range(40)],
                "orders": [120 + (i * 31) % 90 for i in range(40)],
                "returns": [4 + (i * 3) % 11 for i in range(40)],
            }
        ),
        "dock",
        lambda i: {"bay": i % 6, "shift": ("am", "pm")[i % 2]},
    )
    add(
        "ho-30", wh,
        "which warehouse ships the most orders and is that growing and how does it compare with returns",
        "Which warehouse ships the most orders, is that growing, and how does it compare with returns?",
        stratum=adv, cell=4, intent="comparison across categories", shape="nested",
        frame=_frame(
            "Bar Chart",
            {"x": "warehouse", "y": "orders_total"},
            _group("warehouse", "orders_total", "sum", "orders", sort=_desc("orders_total")),
        ),
        family="iii",
    )  # fmt: skip
    return specs


def _holdout() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in _holdout_specs():
        path, digest = _write(f"holdout-{spec['key'][3:]}", spec["table"])
        frame = spec["frame"]
        out.append(
            {
                "id": spec["key"],
                "instruction": spec["rewritten"],
                "source": "authored",
                "source_id": f"authored-{spec['key']}",
                "query_original": spec["original"],
                "query_rewritten": spec["rewritten"],
                "stratum": spec["stratum"],
                "cell": spec["cell"],
                "cell_family": spec["family"],
                "intent": spec["intent"],
                "shape": spec["shape"],
                "dataset_path": path,
                "dataset_sha256": digest,
                "reference_frame": frame,
                "expressible_if": spec["expressible"],
                "ambiguity_degree": spec["degree"],
                "expected_outcome": "miss" if frame is None else "hit",
                "expected_bucket": 1 if frame is None else None,
            }
        )
    return out


# ------------------------------------------------------------- smoke + orders


def _pick(rng: random.Random, pool: list[str], k: int) -> list[str]:
    return rng.sample(sorted(pool), k)


def _smoke(requests: list[dict[str, Any]]) -> list[str]:
    rng = random.Random(SEEDS["smoke_ids"])
    chosen: set[str] = set()
    cell0 = [r for r in requests if r["cell"] == 0]
    for intent in sorted({r["intent"] for r in cell0}):
        chosen.update(_pick(rng, [r["id"] for r in cell0 if r["intent"] == intent], 2))
    chosen.update(_pick(rng, [r["id"] for r in requests if r["cell"] == 1], 1))
    for stratum in ("common_path", "adversarial"):
        pool = [r["id"] for r in requests if r["cell"] == 2 and r["stratum"] == stratum]
        chosen.update(_pick(rng, pool, 2))
    chosen.update(_pick(rng, [r["id"] for r in requests if r["cell"] == 3], 1))
    families = {"common_path": ("ii", "iii", "iv"), "adversarial": ("i", "iii", "iv")}
    for stratum, fams in families.items():
        for fam in fams:
            pool = [
                r["id"]
                for r in requests
                if r["cell"] == 4
                and r["stratum"] == stratum
                and r["cell_family"] == fam
            ]
            chosen.update(_pick(rng, pool, 1))
    return [r["id"] for r in requests if r["id"] in chosen]


def _permutation(ids: list[str], seed: int) -> list[str]:
    out = list(ids)
    random.Random(seed).shuffle(out)
    return out


def _matrix(items: list[dict[str, Any]], stratum: str) -> list[int]:
    counts = Counter(r["cell"] for r in items if r["stratum"] == stratum)
    return [counts.get(c, 0) for c in range(5)]


def _summary(requests: list[dict[str, Any]], holdout: list[dict[str, Any]]) -> dict:
    strata = ("common_path", "adversarial")
    return {
        "matrix": {s: _matrix(requests, s) for s in strata},
        "shape_splits": {
            s: dict(Counter(r["shape"] for r in requests if r["stratum"] == s))
            for s in strata
        },
        "common_path_intent_counts": dict(
            Counter(r["intent"] for r in requests if r["stratum"] == "common_path")
        ),
        "cell4_family_table": {
            fam: [
                sum(
                    1
                    for r in requests
                    if r["cell"] == 4 and r["cell_family"] == fam and r["stratum"] == s
                )
                for s in strata
            ]
            for fam in ("i", "ii", "iii", "iv")
        },
        "holdout_mix": {s: _matrix(holdout, s) for s in strata},
    }


def _notice(requests: list[dict[str, Any]]) -> str:
    spider = sorted(r["dataset_path"] for r in requests if r["source"] == "nvbench1")
    lines = [
        "This directory carries mixed licences. It is a NOTICE, not a relicensing.",
        "",
        "nvBench 1.0 query text (source nvbench1)",
        "  Copyright the nvBench authors (TsinghuaDatabaseGroup/nvBench).",
        "  Licence: MIT, asserted in that repository's README.",
        "  query_original is that text; query_rewritten is a content-preserving",
        "  fluency rewrite by the chartagent authors.",
        "",
        "Tables extracted from nvBench 1.0 databases",
        "  Those tables descend from Spider (Yale / Yale-LILY).",
        "  Licence: CC BY-SA 4.0 (https://yale-lily.github.io/spider).",
        "  Share-alike and attribution apply to the Spider-derived files listed",
        "  below and to nothing else; they do not relicense the rest of this",
        "  Apache-2.0 repository. The Spider-derived files are exactly:",
        "",
        *[f"    {p}" for p in spider],
        "",
        "Authored requests and tables (source authored)",
        "  Copyright the chartagent authors.",
        "  Licence: Apache-2.0, as the rest of this repository. These are every",
        "  other file under eval/data/ (authored-*.parquet and holdout-*.parquet)",
        "  and every request whose source is authored, public or hold-out.",
        "",
        "Quda is not used. NLV Corpus is a register reference only and is not",
        "vendored. nvBench 2.0 is not vendored: HKUSTDial/nvBench-2.0 does not",
        "assert a commercially usable licence in the artefact itself, so the",
        "cell-4 ambiguity sentences were authored to the frozen degrees.",
        "",
    ]
    return "\n".join(lines)


def build() -> None:
    nv = _load("cases-nvbench.json")
    authored = _load("cases-authored-1.json")
    cell4 = _load("cases-cell4.json")
    requests = [
        _normal(r) for r in (*nv["requests"], *authored["cases"], *cell4["requests"])
    ]
    assert len(requests) == 150, len(requests)
    holdout = _holdout()
    assert len(holdout) == 30
    summary = _summary(requests, holdout)
    smoke = _smoke(requests)
    doc: dict[str, Any] = {
        "name": "eval-benchmark-v1",
        "adr": "ADR-0029",
        "authored_on": AUTHORED_ON,
        "flint_version": nv["flint_version"],
        "fixture_commit": nv["fixture_commit"],
        "n_public": len(requests),
        "n_smoke": len(smoke),
        "n_holdout": len(holdout),
        "seeds": SEEDS,
        "permutation_algorithm": (
            "random.Random(seed).shuffle over the ids in file order "
            "(requests for human_calibration_permutation, holdout_pool for "
            "holdout_permutation); smoke_ids use random.Random(seed).sample "
            "over sorted ids, listed in file order"
        ),
        "nvbench": nv["nvbench"],
        **summary,
        "requests": requests,
        "smoke_ids": smoke,
        "holdout_pool": holdout,
        "holdout_permutation": _permutation(
            [r["id"] for r in holdout], SEEDS["holdout_permutation"]
        ),
        "human_calibration_permutation": _permutation(
            [r["id"] for r in requests], SEEDS["human_calibration_permutation"]
        ),
    }
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    OUT.write_bytes(text.encode("utf-8"))
    NOTICE.write_bytes(_notice(requests).encode("utf-8"))
    print(f"wrote {OUT} ({len(requests)} public, {len(holdout)} hold-out)")
    print("sha256", hashlib.sha256(OUT.read_bytes()).hexdigest())


if __name__ == "__main__":
    build()
