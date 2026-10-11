"""One-shot authoring of the 34 cell-4 cases for the eval freeze (issue #286).

Writes ``eval/cases-cell4.json`` (a partial cases file, IDs ``c4-01``..``c4-34``)
and the pinned authored tables ``eval/data/authored-c4-NN.parquet``. Nothing is
drawn from ``corpus/data/`` and no nvBench rows are used: every table and every
sentence is authored. The merge into ``eval/pre-registration.json`` is another
ticket's job.

Not a library surface. Re-running after the ``eval-benchmark-v1`` tag is a
freeze break.

Cell-4 allocation (ADR-0029 section 6, no cell-4-specific shape or intent
allocation in the appendix, so this is the authoring choice):

* common path (16), shapes 4 long / 4 wide / 4 nested / 4 wide_sparse,
  intents trend 5, comparison 6, correlation 1, part-to-whole 2, ranking 2;
* adversarial (18), shapes 5 long / 4 wide / 3 nested / 6 wide_sparse
  (the budget #285 left to reach 6/9/6/9).

Common-path residual for the nvBench ticket after cell-3 (long 1, wide 1):
long 43, wide 43, nested 8, wide_sparse 8.

Family (iii) frames answer the FIRST question of the sentence. Family (ii)
frames pick one of the defensible readings; the degree records how many there
are. Every frame is menu-expressible (no ``raw_sql``) and is executed against
its table here, so each encoded column exists in the transform output.
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from chartagent.frame.input import InputFrame
from chartagent.transform.engine import (
    describe_source,
    open_connection,
    register_source,
)
from chartagent.transform.menu import run_transform

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "eval" / "data"
OUT = REPO / "eval" / "cases-cell4.json"
BASE = {"width": 640, "height": 400}

TREND = "trend over time"
COMPARE = "comparison across categories"
DIST = "distribution of one measure"
CORR = "correlation between measures"
PART = "part-to-whole"
RANK = "ranking / top-N"
FLOW = "flow or transition between states"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frame(
    chart: str, encodings: dict[str, str], transform: dict[str, Any]
) -> dict[str, Any]:
    frame = {
        "chart_spec": {"chartType": chart, "encodings": encodings, "baseSize": BASE},
        "x_chartagent": {"transform": transform},
    }
    InputFrame.model_validate(frame)
    return frame


def _sum(group: str, field: str, out: str, **extra: Any) -> dict[str, Any]:
    return {
        "group_by": [group],
        "aggregate": [{"name": out, "op": "sum", "field": field}],
        **extra,
    }


def _mean(group: str, field: str, out: str) -> dict[str, Any]:
    return {
        "group_by": [group],
        "aggregate": [{"name": out, "op": "mean", "field": field}],
    }


def _count(group: str, out: str = "n") -> dict[str, Any]:
    return {"group_by": [group], "aggregate": [{"name": out, "op": "count"}]}


def _desc(field: str) -> list[dict[str, str]]:
    return [{"field": field, "dir": "desc", "nulls": "last"}]


def _sparse(table: pa.Table, n: int = 8) -> pa.Table:
    for i in range(n):
        table = table.append_column(f"unused_{i}", pa.array([None] * table.num_rows))
    return table


def _nested(table: pa.Table, extras: dict[str, list[Any]]) -> pa.Table:
    rows = table.num_rows
    blobs = [
        json.dumps({key: values[i] for key, values in extras.items()}, sort_keys=True)
        for i in range(rows)
    ]
    return table.append_column("details", pa.array(blobs))


def _months(start: date, n: int) -> list[date]:
    out: list[date] = []
    year, month = start.year, start.month
    for _ in range(n):
        out.append(date(year, month, 1))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


def _cases() -> list[dict[str, Any]]:
    """The 34 authored cases, in ID order. Tables are built per case."""
    cases: list[dict[str, Any]] = []

    def add(
        *,
        stratum: str,
        family: str,
        intent: str,
        shape: str,
        original: str,
        rewritten: str,
        table: pa.Table,
        frame: dict[str, Any],
        degree: int | None = None,
    ) -> None:
        cases.append(
            {
                "stratum": stratum,
                "family": family,
                "intent": intent,
                "shape": shape,
                "original": original,
                "rewritten": rewritten,
                "table": table,
                "frame": frame,
                "degree": degree,
            }
        )

    c, a = "common_path", "adversarial"

    # ---- common path, family (ii): unstated measure or grain, degree 2 ------
    r = _rng(1)
    products = ["kettle", "toaster", "blender", "mixer", "grill", "fryer"]
    add(
        stratum=c, family="ii", intent=RANK, shape="long", degree=2,
        original="which product sells best",
        rewritten="Which product sells best?",
        table=pa.table(
            {
                "month": [m for m in range(1, 7) for _ in products],
                "product": products * 6,
                "units": [r.randint(20, 90) for _ in range(36)],
                "revenue": [r.randint(900, 5200) for _ in range(36)],
            }
        ),
        frame=_frame(
            "Bar Chart",
            {"x": "product", "y": "total_revenue"},
            _sum("product", "revenue", "total_revenue", sort=_desc("total_revenue")),
        ),
    )
    r = _rng(2)
    start = date(2024, 1, 1)
    add(
        stratum=c, family="ii", intent=TREND, shape="long", degree=2,
        original="how are orders trending",
        rewritten="How are orders trending?",
        table=pa.table(
            {
                "order_date": [start + timedelta(days=r.randint(0, 239)) for _ in range(90)],
                "channel": [r.choice(["web", "phone", "store"]) for _ in range(90)],
                "order_value": [round(r.uniform(15, 400), 2) for _ in range(90)],
            }
        ),
        frame=_frame(
            "Line Chart",
            {"x": "month", "y": "n"},
            {
                "bin": [{"name": "month", "field": "order_date", "unit": "month"}],
                **_count("month"),
            },
        ),
    )
    r = _rng(3)
    stores = ["Harbour", "Uptown", "Riverside", "Old Town", "Airport"]
    add(
        stratum=c, family="ii", intent=COMPARE, shape="long", degree=2,
        original="compare the stores",
        rewritten="Compare the stores.",
        table=pa.table(
            {
                "store": [s for s in stores for _ in range(8)],
                "week": [w for _ in stores for w in range(1, 9)],
                "footfall": [r.randint(800, 4000) for _ in range(40)],
                "sales": [r.randint(6000, 31000) for _ in range(40)],
            }
        ),
        frame=_frame(
            "Bar Chart",
            {"x": "store", "y": "total_sales"},
            _sum("store", "sales", "total_sales"),
        ),
    )
    r = _rng(4)
    years = list(range(2015, 2025))
    add(
        stratum=c, family="ii", intent=TREND, shape="wide", degree=2,
        original="show the growth",
        rewritten="Show the growth.",
        table=pa.table(
            {
                "year": years,
                "revenue": [1200 + 140 * i + r.randint(-40, 40) for i in range(10)],
                "cost": [900 + 90 * i + r.randint(-40, 40) for i in range(10)],
                "profit": [300 + 50 * i + r.randint(-20, 20) for i in range(10)],
                "headcount": [40 + 3 * i for i in range(10)],
                "marketing_spend": [r.randint(60, 140) for _ in range(10)],
                "rd_spend": [r.randint(80, 200) for _ in range(10)],
                "customers": [500 + 70 * i for i in range(10)],
            }
        ),
        frame=_frame("Line Chart", {"x": "year", "y": "revenue"}, {}),
    )
    r = _rng(5)
    depts = ["Finance", "Legal", "Ops", "Sales", "Support", "People", "Product"]
    add(
        stratum=c, family="ii", intent=COMPARE, shape="wide", degree=2,
        original="how do the departments compare",
        rewritten="How do the departments compare?",
        table=pa.table(
            {
                "department": depts,
                "budget": [r.randint(200, 900) for _ in depts],
                "actual_spend": [r.randint(180, 950) for _ in depts],
                "headcount": [r.randint(4, 60) for _ in depts],
                "attrition_rate": [round(r.uniform(0.02, 0.2), 3) for _ in depts],
                "avg_tenure": [round(r.uniform(1, 9), 1) for _ in depts],
                "open_roles": [r.randint(0, 8) for _ in depts],
            }
        ),
        frame=_frame("Bar Chart", {"x": "department", "y": "actual_spend"}, {}),
    )
    r = _rng(6)
    n = 24
    add(
        stratum=c, family="ii", intent=CORR, shape="wide", degree=2,
        original="does price matter",
        rewritten="Does price matter?",
        table=pa.table(
            {
                "product": [f"sku-{i:02d}" for i in range(n)],
                "price": [round(r.uniform(5, 120), 2) for _ in range(n)],
                "units_sold": [r.randint(30, 900) for _ in range(n)],
                "rating": [round(r.uniform(2.5, 5), 1) for _ in range(n)],
                "returns": [r.randint(0, 40) for _ in range(n)],
                "weight_kg": [round(r.uniform(0.1, 4), 2) for _ in range(n)],
                "shelf_days": [r.randint(5, 120) for _ in range(n)],
            }
        ),
        frame=_frame("Scatter Plot", {"x": "price", "y": "units_sold"}, {}),
    )
    r = _rng(7)
    days = [date(2024, 3, 1) + timedelta(days=d) for d in range(20) for _ in range(2)]
    base = pa.table(
        {
            "day": days,
            "visits": [r.randint(300, 2600) for _ in days],
            "signups": [r.randint(5, 140) for _ in days],
        }
    )
    add(
        stratum=c, family="ii", intent=TREND, shape="nested", degree=2,
        original="how is traffic doing",
        rewritten="How is traffic doing?",
        table=_nested(
            base,
            {
                "device": [r.choice(["mobile", "desktop"]) for _ in days],
                "browser": [r.choice(["firefox", "safari", "chrome"]) for _ in days],
            },
        ),
        frame=_frame(
            "Line Chart", {"x": "day", "y": "visits_total"}, _sum("day", "visits", "visits_total")
        ),
    )
    r = _rng(8)
    teams = ["Alpha", "Bravo", "Cedar", "Delta"]
    reps = [t for t in teams for _ in range(5)]
    base = pa.table(
        {
            "team": reps,
            "rep": [f"rep-{i:02d}" for i in range(20)],
            "sales": [r.randint(20, 240) * 1000 for _ in range(20)],
        }
    )
    add(
        stratum=c, family="ii", intent=COMPARE, shape="nested", degree=2,
        original="show sales by team",
        rewritten="Show sales by team.",
        table=_nested(
            base,
            {
                "region": [r.choice(["east", "west"]) for _ in reps],
                "quarter": [r.choice(["Q1", "Q2", "Q3"]) for _ in reps],
            },
        ),
        frame=_frame(
            "Bar Chart", {"x": "team", "y": "sales_total"}, _sum("team", "sales", "sales_total")
        ),
    )
    r = _rng(9)
    ms = _months(date(2023, 1, 1), 12)
    dd = ["Eng", "Sales", "Ops"]
    add(
        stratum=c, family="ii", intent=TREND, shape="wide_sparse", degree=2,
        original="how has headcount changed",
        rewritten="How has headcount changed?",
        table=_sparse(
            pa.table(
                {
                    "month": [m for m in ms for _ in dd],
                    "dept": dd * 12,
                    "headcount": [r.randint(8, 70) for _ in range(36)],
                }
            )
        ),
        frame=_frame(
            "Line Chart",
            {"x": "month", "y": "headcount_total"},
            _sum("month", "headcount", "headcount_total"),
        ),
    )
    r = _rng(10)
    regions = ["North", "South", "East", "West", "Central"]
    add(
        stratum=c, family="ii", intent=COMPARE, shape="wide_sparse", degree=2,
        original="compare the regions",
        rewritten="Compare the regions.",
        table=_sparse(
            pa.table(
                {
                    "region": [g for g in regions for _ in range(4)],
                    "quarter": ["Q1", "Q2", "Q3", "Q4"] * 5,
                    "revenue": [r.randint(100, 900) * 100 for _ in range(20)],
                    "margin_pct": [round(r.uniform(4, 31), 1) for _ in range(20)],
                }
            )
        ),
        frame=_frame(
            "Bar Chart",
            {"x": "region", "y": "revenue_total"},
            _sum("region", "revenue", "revenue_total"),
        ),
    )

    # ---- common path, family (iii): compound ask ---------------------------
    r = _rng(11)
    lines = ["audio", "video", "gaming"]
    ms = _months(date(2024, 1, 1), 10)
    add(
        stratum=c, family="iii", intent=TREND, shape="long",
        original="how did monthly revenue move and which product line is the biggest",
        rewritten="How did monthly revenue move, and which product line is the biggest?",
        table=pa.table(
            {
                "month": [m for m in ms for _ in lines],
                "product_line": lines * 10,
                "revenue": [r.randint(40, 300) * 1000 for _ in range(30)],
            }
        ),
        frame=_frame(
            "Line Chart",
            {"x": "month", "y": "revenue_total"},
            _sum("month", "revenue", "revenue_total"),
        ),
    )
    r = _rng(12)
    add(
        stratum=c, family="iii", intent=COMPARE, shape="wide",
        original="compare cost across departments and also tell me who has the most staff",
        rewritten="Compare cost across departments, and also tell me which one has the most staff.",
        table=pa.table(
            {
                "department": depts,
                "cost": [r.randint(100, 800) for _ in depts],
                "headcount": [r.randint(4, 60) for _ in depts],
                "budget": [r.randint(100, 900) for _ in depts],
                "overtime_hours": [r.randint(0, 400) for _ in depts],
                "travel": [r.randint(2, 90) for _ in depts],
                "training": [r.randint(2, 50) for _ in depts],
            }
        ),
        frame=_frame("Bar Chart", {"x": "department", "y": "cost"}, {}),
    )
    r = _rng(13)
    n = 40
    base = pa.table(
        {
            "ticket_id": list(range(1001, 1001 + n)),
            "channel": [r.choice(["email", "chat", "phone", "portal"]) for _ in range(n)],
            "hours_to_close": [round(r.uniform(0.5, 72), 1) for _ in range(n)],
        }
    )
    add(
        stratum=c, family="iii", intent=PART, shape="nested",
        original="what share of tickets does each channel handle and how long do they take to close",
        rewritten="What share of tickets does each channel handle, and how long do they take to close?",
        table=_nested(
            base,
            {
                "priority": [r.choice(["low", "high", "urgent"]) for _ in range(n)],
                "agent": [f"agent-{r.randint(1, 6)}" for _ in range(n)],
            },
        ),
        frame=_frame("Pie Chart", {"color": "channel", "size": "n"}, _count("channel")),
    )
    r = _rng(14)
    custs = ["Acme", "Birch", "Cobalt", "Dune", "Ember", "Fjord", "Gable", "Hollow"]
    n = 48
    add(
        stratum=c, family="iii", intent=RANK, shape="wide_sparse",
        original="who are the five biggest customers and when did each last order",
        rewritten="Who are the five biggest customers, and when did each of them last order?",
        table=_sparse(
            pa.table(
                {
                    "customer": [r.choice(custs) for _ in range(n)],
                    "order_date": [date(2024, 1, 1) + timedelta(days=r.randint(0, 300)) for _ in range(n)],
                    "amount": [r.randint(200, 9000) for _ in range(n)],
                }
            ),
            6,
        ),
        frame=_frame(
            "Bar Chart",
            {"x": "customer", "y": "spend_total"},
            _sum("customer", "amount", "spend_total", sort=_desc("spend_total"), limit={"count": 5, "offset": 0}),
        ),
    )

    # ---- common path, family (iv): hostile metadata -------------------------
    r = _rng(15)
    cats = ["Rent", "Payroll", "Software", "Travel", "Marketing"]
    n = 25
    base = pa.table(
        {
            "Unnamed: 0": [cats[i % 5] for i in range(n)],
            "Unnamed: 1": [r.randint(200, 6000) for _ in range(n)],
        }
    )
    add(
        stratum=c, family="iv", intent=PART, shape="nested",
        original="show the share of each category",
        rewritten="Show the share of each category.",
        table=_nested(
            base,
            {
                "Unnamed: 2": [r.choice(["paid", "due"]) for _ in range(n)],
                "Unnamed: 3": [r.randint(1, 4) for _ in range(n)],
            },
        ),
        frame=_frame(
            "Pie Chart",
            {"color": "Unnamed: 0", "size": "total"},
            _sum("Unnamed: 0", "Unnamed: 1", "total"),
        ),
    )
    r = _rng(16)
    n = 30
    add(
        stratum=c, family="iv", intent=COMPARE, shape="wide_sparse",
        original="compare the amount across stores",
        rewritten="Compare the amount across stores.",
        table=_sparse(
            pa.table(
                {
                    "Store #": [f"S{r.randint(1, 6)}" for _ in range(n)],
                    "Amt ($)": [r.randint(50, 2500) for _ in range(n)],
                    "Dt.": [f"2024-0{r.randint(1, 9)}-{r.randint(10, 28)}" for _ in range(n)],
                }
            ),
            7,
        ),
        frame=_frame(
            "Bar Chart",
            {"x": "Store #", "y": "amt_total"},
            _sum("Store #", "Amt ($)", "amt_total"),
        ),
    )

    # ---- adversarial, family (i): a named form the pin lacks -----------------
    plans = ["free", "pro", "team", "enterprise"]
    pairs = [(f, t) for f in plans for t in plans if f != t]
    r = _rng(17)
    add(
        stratum=a, family="i", intent=FLOW, shape="long",
        original="draw an alluvial diagram of customers moving between plan tiers",
        rewritten="Draw an alluvial diagram of customers moving between plan tiers.",
        table=pa.table(
            {
                "from_plan": [p[0] for p in pairs],
                "to_plan": [p[1] for p in pairs],
                "customers": [r.randint(5, 220) for _ in pairs],
            }
        ),
        frame=_frame(
            "Stacked Bar Chart", {"x": "from_plan", "y": "customers", "color": "to_plan"}, {}
        ),
    )
    r = _rng(18)
    ds = [date(2024, 1, 1) + timedelta(days=d) for d in range(120)]
    add(
        stratum=a, family="i", intent=DIST, shape="wide_sparse",
        original="make a ridgeline plot of daily temperature by month",
        rewritten="Make a ridgeline plot of daily temperature by month.",
        table=_sparse(
            pa.table(
                {
                    "obs_date": ds,
                    "temp_c": [round(2 + d * 0.12 + r.uniform(-4, 4), 1) for d in range(120)],
                }
            )
        ),
        frame=_frame(
            "Boxplot",
            {"x": "month", "y": "temp_c"},
            {"bin": [{"name": "month", "field": "obs_date", "unit": "month"}]},
        ),
    )
    r = _rng(19)
    n = 40
    add(
        stratum=a, family="i", intent=DIST, shape="wide",
        original="show a beeswarm of salaries by department",
        rewritten="Show a beeswarm of salaries by department.",
        table=pa.table(
            {
                "employee": [f"emp-{i:03d}" for i in range(n)],
                "department": [r.choice(depts[:5]) for _ in range(n)],
                "salary": [r.randint(42, 160) * 1000 for _ in range(n)],
                "tenure_years": [r.randint(0, 20) for _ in range(n)],
                "age": [r.randint(22, 64) for _ in range(n)],
                "bonus": [r.randint(0, 20) * 500 for _ in range(n)],
                "level": [r.randint(1, 7) for _ in range(n)],
            }
        ),
        frame=_frame("Strip Plot", {"x": "department", "y": "salary"}, {}),
    )
    r = _rng(20)
    centres = ["CC-100", "CC-210", "CC-305", "CC-410", "CC-520", "CC-615"]
    n = 36
    add(
        stratum=a, family="i", intent=PART, shape="wide_sparse",
        original="give me a circle packing of spend by cost centre",
        rewritten="Give me a circle packing of spend by cost centre.",
        table=_sparse(
            pa.table(
                {
                    "cost_centre": [r.choice(centres) for _ in range(n)],
                    "spend": [r.randint(100, 8000) for _ in range(n)],
                    "invoice": [f"inv-{i:04d}" for i in range(n)],
                }
            ),
            7,
        ),
        frame=_frame(
            "Pie Chart", {"color": "cost_centre", "size": "spend_total"}, _sum("cost_centre", "spend", "spend_total")
        ),
    )
    r = _rng(21)
    servers = ["web-1", "web-2", "db-1"]
    n = 72
    base = pa.table(
        {
            "server": [s for s in servers for _ in range(24)],
            "hour": [h for _ in servers for h in range(24)],
            "load": [round(r.uniform(0.1, 0.95), 2) for _ in range(n)],
        }
    )
    add(
        stratum=a, family="i", intent=TREND, shape="nested",
        original="draw a horizon chart of server load by hour",
        rewritten="Draw a horizon chart of server load by hour.",
        table=_nested(
            base,
            {
                "dc": [r.choice(["fra", "iad"]) for _ in range(n)],
                "rack": [r.randint(1, 12) for _ in range(n)],
            },
        ),
        frame=_frame("Area Chart", {"x": "hour", "y": "load_avg"}, _mean("hour", "load", "load_avg")),
    )
    r = _rng(22)
    n = 60
    add(
        stratum=a, family="i", intent=PART, shape="long",
        original="make a pictogram of how people answered",
        rewritten="Make a pictogram of how people answered.",
        table=pa.table(
            {
                "respondent": list(range(1, n + 1)),
                "answer": [r.choice(["agree", "neutral", "disagree", "unsure"]) for _ in range(n)],
                "age_band": [r.choice(["18-29", "30-44", "45-59", "60+"]) for _ in range(n)],
                "region": [r.choice(regions) for _ in range(n)],
            }
        ),
        frame=_frame("Pie Chart", {"color": "answer", "size": "n"}, _count("answer")),
    )
    r = _rng(23)
    n = 50
    add(
        stratum=a, family="i", intent=CORR, shape="long",
        original="plot a hexbin of height against weight",
        rewritten="Plot a hexbin of height against weight.",
        table=pa.table(
            {
                "person": [f"p-{i:03d}" for i in range(n)],
                "height_cm": [r.randint(150, 195) for _ in range(n)],
                "weight_kg": [r.randint(48, 105) for _ in range(n)],
            }
        ),
        frame=_frame("Scatter Plot", {"x": "height_cm", "y": "weight_kg"}, {}),
    )
    r = _rng(24)
    n = 40
    add(
        stratum=a, family="i", intent=COMPARE, shape="wide_sparse",
        original="show a radial bar chart of sales by region",
        rewritten="Show a radial bar chart of sales by region.",
        table=_sparse(
            pa.table(
                {
                    "region": [r.choice(regions) for _ in range(n)],
                    "sales": [r.randint(10, 400) * 100 for _ in range(n)],
                    "order_no": [f"o-{i:04d}" for i in range(n)],
                }
            ),
            7,
        ),
        frame=_frame("Bar Chart", {"x": "region", "y": "sales_total"}, _sum("region", "sales", "sales_total")),
    )

    # ---- adversarial, family (ii): unstated measure or grain, degree >= 4 ----
    r = _rng(25)
    ms = _months(date(2024, 1, 1), 8)
    ps = ["core", "plus", "max"]
    rs = ["EMEA", "AMER", "APAC"]
    rows = [(m, g, p) for m in ms for g in rs for p in ps]
    add(
        stratum=a, family="ii", intent=TREND, shape="long", degree=4,
        original="give me an overview of the business",
        rewritten="Give me an overview of the business.",
        table=pa.table(
            {
                "month": [x[0] for x in rows],
                "region": [x[1] for x in rows],
                "product": [x[2] for x in rows],
                "revenue": [r.randint(20, 200) * 1000 for _ in rows],
                "cost": [r.randint(10, 150) * 1000 for _ in rows],
                "units": [r.randint(100, 2000) for _ in rows],
                "new_customers": [r.randint(0, 80) for _ in rows],
            }
        ),
        frame=_frame(
            "Line Chart", {"x": "month", "y": "revenue_total"}, _sum("month", "revenue", "revenue_total")
        ),
    )
    r = _rng(26)
    tm = ["Atlas", "Borealis", "Cirrus", "Dynamo", "Eclipse"]
    rows2 = [(t, q) for t in tm for q in ("Q1", "Q2", "Q3", "Q4")]
    add(
        stratum=a, family="ii", intent=COMPARE, shape="wide_sparse", degree=5,
        original="show me how we're doing",
        rewritten="Show me how we're doing.",
        table=_sparse(
            pa.table(
                {
                    "team": [x[0] for x in rows2],
                    "quarter": [x[1] for x in rows2],
                    "revenue": [r.randint(50, 400) * 1000 for _ in rows2],
                    "nps": [r.randint(-10, 70) for _ in rows2],
                    "churn_pct": [round(r.uniform(0.5, 9), 1) for _ in rows2],
                    "tickets": [r.randint(10, 600) for _ in rows2],
                }
            ),
            6,
        ),
        frame=_frame("Bar Chart", {"x": "team", "y": "revenue_total"}, _sum("team", "revenue", "revenue_total")),
    )

    # ---- adversarial, family (iii): compound ask -----------------------------
    r = _rng(27)
    ms = _months(date(2024, 1, 1), 6)
    rows = [(g, m) for g in rs + ["LATAM"] for m in ms]
    add(
        stratum=a, family="iii", intent=COMPARE, shape="long",
        original="which region earns the most and has its trend been rising",
        rewritten="Which region earns the most, and has its trend been rising?",
        table=pa.table(
            {
                "region": [x[0] for x in rows],
                "month": [x[1] for x in rows],
                "revenue": [r.randint(30, 260) * 1000 for _ in rows],
            }
        ),
        frame=_frame(
            "Bar Chart",
            {"x": "region", "y": "revenue_total"},
            _sum("region", "revenue", "revenue_total", sort=_desc("revenue_total")),
        ),
    )
    r = _rng(28)
    add(
        stratum=a, family="iii", intent=TREND, shape="wide",
        original="how did sales and headcount move over the years and are they correlated",
        rewritten="How did sales and headcount move over the years, and are they correlated?",
        table=pa.table(
            {
                "year": list(range(2012, 2025)),
                "sales": [900 + 85 * i + r.randint(-60, 60) for i in range(13)],
                "headcount": [35 + 2 * i + r.randint(-2, 2) for i in range(13)],
                "returns": [r.randint(10, 80) for _ in range(13)],
                "ad_spend": [r.randint(50, 220) for _ in range(13)],
                "stores": [10 + i for i in range(13)],
                "complaints": [r.randint(3, 60) for _ in range(13)],
            }
        ),
        frame=_frame("Line Chart", {"x": "year", "y": "sales"}, {}),
    )
    r = _rng(29)
    n = 50
    ctry = ["Germany", "France", "Spain", "Italy", "Poland"]
    base = pa.table(
        {
            "order_id": list(range(5001, 5001 + n)),
            "country": [r.choice(ctry) for _ in range(n)],
            "amount": [r.randint(10, 500) for _ in range(n)],
            "refunded": [r.choice([0, 0, 0, 1]) for _ in range(n)],
        }
    )
    add(
        stratum=a, family="iii", intent=PART, shape="nested",
        original="what share of orders come from each country and which country refunds the most",
        rewritten="What share of orders come from each country, and which country refunds the most?",
        table=_nested(
            base,
            {
                "coupon": [r.choice(["none", "SPRING", "VIP"]) for _ in range(n)],
                "carrier": [r.choice(["dhl", "ups"]) for _ in range(n)],
            },
        ),
        frame=_frame("Pie Chart", {"color": "country", "size": "n"}, _count("country")),
    )
    r = _rng(30)
    n = 40
    add(
        stratum=a, family="iii", intent=CORR, shape="wide_sparse",
        original="does tenure relate to salary and how does it differ by gender",
        rewritten="Does tenure relate to salary, and how does that differ by gender?",
        table=_sparse(
            pa.table(
                {
                    "employee": [f"e-{i:03d}" for i in range(n)],
                    "tenure": [r.randint(0, 25) for _ in range(n)],
                    "salary": [r.randint(40, 170) * 1000 for _ in range(n)],
                    "gender": [r.choice(["F", "M", "X"]) for _ in range(n)],
                }
            ),
            7,
        ),
        frame=_frame("Scatter Plot", {"x": "tenure", "y": "salary", "color": "gender"}, {}),
    )

    # ---- adversarial, family (iv): hostile metadata --------------------------
    r = _rng(31)
    n = 36
    add(
        stratum=a, family="iv", intent=TREND, shape="wide",
        original="plot the figures over time",
        rewritten="Plot the figures over time.",
        table=pa.table(
            {
                "Unnamed: 0": [f"2024-{1 + i // 4:02d}-{1 + (i % 4) * 7:02d}" for i in range(n)],
                "Unnamed: 1": [r.randint(500, 9000) for _ in range(n)],
                "Unnamed: 2": [r.choice(["ok", "late", "hold"]) for _ in range(n)],
                "Unnamed: 3": [r.choice(["A", "B"]) for _ in range(n)],
                "Unnamed: 4": [f"ref-{r.randint(100, 999)}" for _ in range(n)],
                "Unnamed: 5": [r.choice(["north", "south"]) for _ in range(n)],
                "Unnamed: 6": [None] * n,
            }
        ),
        frame=_frame(
            "Line Chart",
            {"x": "Unnamed: 0", "y": "figures_total"},
            _sum("Unnamed: 0", "Unnamed: 1", "figures_total"),
        ),
    )
    r = _rng(32)
    n = 30
    add(
        stratum=a, family="iv", intent=COMPARE, shape="wide",
        original="compare revenue across regions",
        rewritten="Compare revenue across regions.",
        table=pa.table(
            {
                "REGION": [r.choice(["nord", "sud", "est", "ouest"]) for _ in range(n)],
                "Rev ($)": [r.randint(1000, 90000) for _ in range(n)],
                "Cost ($)": [r.randint(500, 60000) for _ in range(n)],
                "date ": [f"{r.randint(1, 28):02d}/{r.randint(1, 12):02d}/2024" for _ in range(n)],
                "Qty.": [r.randint(1, 300) for _ in range(n)],
                "SKU - main": [f"k{r.randint(1, 9)}" for _ in range(n)],
                "Notes ": [None] * n,
            }
        ),
        frame=_frame("Bar Chart", {"x": "REGION", "y": "rev_total"}, _sum("REGION", "Rev ($)", "rev_total")),
    )
    r = _rng(33)
    n = 30
    base = pa.table(
        {
            "col_1": [f"item-{i:02d}" for i in range(n)],
            "col_2": [r.choice(["x", "y", "z"]) for _ in range(n)],
            "col_3": [r.randint(5, 900) for _ in range(n)],
        }
    )
    add(
        stratum=a, family="iv", intent=RANK, shape="nested",
        original="rank the entries by the number and show the top five",
        rewritten="Rank the entries by the number and show the top five.",
        table=_nested(
            base,
            {
                "col_4": [r.choice(["a", "b"]) for _ in range(n)],
                "col_5": [r.randint(0, 3) for _ in range(n)],
            },
        ),
        frame=_frame(
            "Bar Chart",
            {"x": "col_1", "y": "col_3"},
            {"sort": _desc("col_3"), "limit": {"count": 5, "offset": 0}},
        ),
    )
    r = _rng(34)
    n = 32
    add(
        stratum=a, family="iv", intent=TREND, shape="wide_sparse",
        original="how did it change month to month",
        rewritten="How did it change month to month?",
        table=_sparse(
            pa.table(
                {
                    "date": [f"2024-{1 + i // 4:02d}-{10 + (i % 4)}" for i in range(n)],
                    "v": [r.randint(10, 500) for _ in range(n)],
                }
            ),
            8,
        ),
        frame=_frame("Line Chart", {"x": "date", "y": "v_total"}, _sum("date", "v", "v_total")),
    )
    return cases


def _execute(frame: dict[str, Any], path: Path) -> list[str]:
    """Run the frame's transform on the pinned table; return its output columns."""
    connection = open_connection()
    try:
        register_source(connection, str(path))
        types, schema = describe_source(connection)
        table, _ = run_transform(
            connection,
            frame["x_chartagent"]["transform"],
            source_types=types,
            source_schema=schema,
            timeout=10.0,
        )
        return list(table.column_names)
    finally:
        connection.close()


def build() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for index, case in enumerate(_cases(), start=1):
        rid = f"c4-{index:02d}"
        path = DATA / f"authored-c4-{index:02d}.parquet"
        pq.write_table(case["table"], path, compression="none")
        columns = _execute(case["frame"], path)
        for channel, field in case["frame"]["chart_spec"]["encodings"].items():
            assert field in columns, f"{rid}: {channel}={field!r} not in {columns}"
        record: dict[str, Any] = {
            "id": rid,
            "instruction": case["rewritten"],
            "source": "authored",
            "source_id": f"authored-c4-{index:02d}-{case['family']}",
            "query_original": case["original"],
            "query_rewritten": case["rewritten"],
            "stratum": case["stratum"],
            "cell": 4,
            "cell_family": case["family"],
            "intent": case["intent"],
            "shape": case["shape"],
            "dataset_path": f"eval/data/authored-c4-{index:02d}.parquet",
            "dataset_sha256": _sha(path),
            "reference_frame": case["frame"],
            "expected_outcome": "hit",
        }
        if case["degree"] is not None:
            record["ambiguity_degree"] = case["degree"]
        records.append(record)
    OUT.write_text(
        json.dumps({"requests": records}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT} ({len(records)} cases)")


if __name__ == "__main__":
    build()
