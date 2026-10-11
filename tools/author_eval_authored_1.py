"""One-shot authoring of eval/cases-authored-1.json (issue #285, spec #282).

Writes the 14 cases this ticket owns and their pinned datasets under
eval/data/authored-*: 4 cell-1, 2 cell-3 (silent row drop), 8 adversarial
cell-2. IDs are prefixed ``auth-c1-`` / ``auth-c3-`` / ``auth-c2adv-``. The
output is a partial cases file that the later assembly ticket merges into
eval/pre-registration.json; it is not the freeze. Nothing here is reused from
corpus/data/. Not a library surface. Re-running after the tag is a freeze break.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from chartagent.frame.input import InputFrame
from chartagent.transform.engine import open_connection
from chartagent.transform.raw_sql import validate_raw_sql

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "eval" / "data"
OUT = REPO / "eval" / "cases-authored-1.json"
BASE = {"width": 640, "height": 400}

OVERLAP = "set overlap / intersection structure"
SIMPLEX = "compositional simplex"
OD_FLOW = "origin–destination flow on a geography"


def _write(name: str, table: pa.Table) -> tuple[str, str]:
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / f"{name}.parquet"
    pq.write_table(table, path)
    return f"eval/data/{name}.parquet", hashlib.sha256(path.read_bytes()).hexdigest()


def _frame(
    chart: str, encodings: dict[str, str], transform: dict[str, Any]
) -> dict[str, Any]:
    frame = {
        "chart_spec": {"chartType": chart, "encodings": encodings, "baseSize": BASE},
        "x_chartagent": {"transform": transform},
    }
    InputFrame.model_validate(frame)
    return frame


def _check_sql(table: pa.Table, sql: str) -> None:
    """The SQL must pass the raw_sql gate and run against the pinned table."""
    con = open_connection()
    try:
        validate_raw_sql(con, sql)
    finally:
        con.close()
    probe = duckdb.connect()
    try:
        probe.register("source", table)
        rows = probe.execute(sql).fetchall()
    finally:
        probe.close()
    assert rows, sql


def _cell1_tables() -> dict[str, pa.Table]:
    lists = ["newsletter", "podcast", "webinar"]
    long_rows = [
        (f"sub{i:03d}", lists[j])
        for i in range(40)
        for j in range(3)
        if (i * (j + 2) + j) % 3 != 0
    ]
    overlap_long = pa.table(
        {
            "subscriber": [r[0] for r in long_rows],
            "list_name": [r[1] for r in long_rows],
        }
    )
    clinics = [f"clinic_{c}" for c in "abcdefgh"]
    conditions = [
        "asthma", "diabetes", "migraine", "eczema", "anaemia", "arthritis",
        "gout", "insomnia", "rosacea", "sciatica", "tinnitus", "vertigo",
    ]  # fmt: skip
    overlap_wide = pa.table(
        {"condition": conditions}
        | {
            clinic: [(i * 3 + k) % 5 < 2 for i in range(len(conditions))]
            for k, clinic in enumerate(clinics)
        }
    )
    districts = [f"district {i:02d}" for i in range(1, 11)]
    left = [0.22, 0.35, 0.18, 0.41, 0.30, 0.12, 0.27, 0.38, 0.20, 0.33]
    centre = [0.48, 0.25, 0.42, 0.19, 0.36, 0.50, 0.31, 0.22, 0.45, 0.28]
    right = [round(1 - a - b, 2) for a, b in zip(left, centre, strict=True)]
    simplex = pa.table(
        {
            "district": districts,
            "share_left": left,
            "share_centre": centre,
            "share_right": right,
        }
    )
    for i in range(6):
        simplex = simplex.append_column(f"unused_{i}", pa.array([None] * 10))
    depots = ["Aston", "Brill", "Calder", "Dunmore", "Eskdale", "Fenwick", "Garth"]
    coords = {
        "Aston": (51.5, -0.1), "Brill": (51.8, -1.0), "Calder": (53.7, -1.9),
        "Dunmore": (55.9, -3.2), "Eskdale": (54.4, -3.3), "Fenwick": (55.6, -1.8),
        "Garth": (52.4, -1.5),
    }  # fmt: skip
    legs = [(a, b) for a in depots for b in depots if a != b][:21]
    flows = pa.table(
        {
            "origin": [a for a, _ in legs],
            "destination": [b for _, b in legs],
            "tonnes": [100 + 37 * i % 900 for i in range(len(legs))],
            "route": [
                json.dumps(
                    {
                        "from": list(coords[a]),
                        "to": list(coords[b]),
                        "mode": "road" if i % 3 else "rail",
                    }
                )
                for i, (a, b) in enumerate(legs)
            ],
        }
    )
    return {
        "c1-01": overlap_long,
        "c1-02": overlap_wide,
        "c1-03": simplex,
        "c1-04": flows,
    }


def _cell3_tables() -> dict[str, pa.Table]:
    stores = pa.table(
        {
            "store": [f"store-{i:03d}" for i in range(1, 161)],
            "region": [("north", "south", "east", "west")[i % 4] for i in range(160)],
            "revenue": [20000 + (i * 7919) % 48000 for i in range(160)],
        }
    )
    skus = [f"sku-{i:03d}" for i in range(1, 151)]
    qs = {
        f"units_q{q}": [(i * (q + 3) * 13) % 400 + 20 for i in range(150)]
        for q in range(1, 5)
    }
    products = pa.table(
        {"sku": skus}
        | qs
        | {"units_total": [sum(v) for v in zip(*qs.values(), strict=True)]}
    )
    return {"c3-01": stores, "c3-02": products}


def _cell2_tables() -> dict[str, tuple[pa.Table, str]]:
    channels = ["web", "email", "social", "search", "referral", "direct"]
    months = ["jan", "feb", "mar", "apr", "may", "jun"]
    visits = pa.table(
        {"channel": channels}
        | {
            m: [900 + 130 * ((i + j * 2) % 7) for i in range(6)]
            for j, m in enumerate(months)
        }
    )
    unpivot_sql = (
        "SELECT channel, month, visits FROM source "
        f"UNPIVOT (visits FOR month IN ({', '.join(months)}))"
    )
    scores = pa.table(
        {
            "student": [f"student {i:02d}" for i in range(1, 13)],
            "pre_score": [52, 61, 47, 70, 58, 66, 49, 73, 55, 63, 68, 51],
            "post_score": [60, 64, 59, 72, 69, 65, 58, 80, 61, 71, 70, 62],
        }
    )
    union_sql = (
        "SELECT student, 'before' AS phase, pre_score AS score FROM source "
        "UNION ALL SELECT student, 'after', post_score FROM source"
    )
    questions = [f"q{i}" for i in range(1, 9)]
    survey = pa.table(
        {"respondent": [f"r{i:02d}" for i in range(1, 17)]}
        | {
            q: [((i * (j + 2)) % 5 + 1) if (i + j) % 3 else None for i in range(16)]
            for j, q in enumerate(questions)
        }
    )
    for i in range(6):
        survey = survey.append_column(f"unused_{i}", pa.array([None] * 16))
    survey_sql = (
        "SELECT question, avg(rating) AS avg_rating FROM "
        f"(SELECT * FROM source UNPIVOT (rating FOR question IN ({', '.join(questions)}))) "
        "GROUP BY question ORDER BY question"
    )
    days = [f"2024-05-{d:02d}" for d in range(1, 15)]
    helpdesk = pa.table(
        {
            "day": pa.array(
                [__import__("datetime").date.fromisoformat(d) for d in days]
            ),
            "opened": [40 + (i * 7) % 23 for i in range(14)],
            "closed": [35 + (i * 11) % 29 for i in range(14)],
        }
    )
    for i in range(6):
        helpdesk = helpdesk.append_column(f"unused_{i}", pa.array([None] * 14))
    window_sql = (
        "SELECT day, 100.0 * SUM(closed) OVER (ORDER BY day) / SUM(closed) OVER () "
        "AS cumulative_pct FROM source"
    )
    catalogue = pa.table(
        {
            "sku": [f"item-{i:02d}" for i in range(1, 21)],
            "attrs": [
                json.dumps(
                    {
                        "price": 10 + (i * 17) % 60,
                        "rating": round(2.5 + ((i * 17) % 60) / 30 + (i % 3) * 0.2, 1),
                    }
                )
                for i in range(20)
            ],
        }
    )
    json_sql = (
        "SELECT CAST(json_extract_string(attrs, '$.price') AS DOUBLE) AS price, "
        "CAST(json_extract_string(attrs, '$.rating') AS DOUBLE) AS rating FROM source"
    )
    pool = ["python", "sql", "duckdb", "charts", "etl", "arrow", "rust", "testing"]
    articles = pa.table(
        {
            "article": [f"post-{i:02d}" for i in range(1, 25)],
            "tags": [
                json.dumps([pool[(i + a) % 8] for a in range((i * 5) % 7 + 1)])
                for i in range(24)
            ],
        }
    )
    tags_sql = (
        "SELECT article, json_array_length(tags) AS tag_count FROM source "
        "ORDER BY tag_count DESC, article LIMIT 5"
    )
    orders = pa.table(
        {
            "order_id": [f"o{i:03d}" for i in range(1, 41)],
            "order_date": [
                f"{1 + (i * 5) % 28:02d}/{3 + i % 2:02d}/2024" for i in range(40)
            ],
            "amount": [round(20 + (i * 13.7) % 180, 2) for i in range(40)],
            "region": [("north", "south", "east", "west")[i % 4] for i in range(40)],
            "status": [("paid", "paid", "refunded")[i % 3] for i in range(40)],
            "channel": [("web", "app")[i % 2] for i in range(40)],
        }
    )
    weekly_sql = (
        "SELECT date_trunc('week', strptime(order_date, '%d/%m/%Y')) AS week, "
        "sum(amount) AS revenue FROM source GROUP BY week ORDER BY week"
    )
    league = pa.table(
        {
            "team": ["Ash", "Birch", "Cedar", "Dogwood", "Elm", "Fir", "Gum", "Hazel"],
            "played": [30] * 8,
            "points": [61, 55, 48, 44, 39, 35, 30, 22],
            "goals_for": [58, 49, 44, 41, 36, 33, 29, 24],
            "goals_against": [27, 31, 35, 38, 40, 44, 47, 52],
        }
    )
    diff_sql = (
        "SELECT team, (goals_for - goals_against) "
        "- avg(goals_for - goals_against) OVER () AS vs_average FROM source"
    )
    return {
        "c2adv-01": (visits, unpivot_sql),
        "c2adv-02": (scores, union_sql),
        "c2adv-03": (survey, survey_sql),
        "c2adv-04": (helpdesk, window_sql),
        "c2adv-05": (catalogue, json_sql),
        "c2adv-06": (articles, tags_sql),
        "c2adv-07": (orders, weekly_sql),
        "c2adv-08": (league, diff_sql),
    }


def build() -> None:
    c1 = _cell1_tables()
    c3 = _cell3_tables()
    c2 = _cell2_tables()
    for key, (table, sql) in c2.items():
        _check_sql(table, sql)
    paths = {
        key: _write(f"authored-{key}", table)
        for key, table in {**c1, **c3, **{k: v[0] for k, v in c2.items()}}.items()
    }

    def rec(
        key: str,
        *,
        source_id: str,
        original: str,
        rewritten: str,
        stratum: str,
        cell: int,
        intent: str,
        shape: str,
        frame: dict[str, Any] | None,
        cell_family: str | None = None,
        expressible: list[str] | None = None,
    ) -> dict[str, Any]:
        path, digest = paths[key]
        row: dict[str, Any] = {
            "id": f"auth-{key}",
            "instruction": rewritten,
            "source": "authored",
            "source_id": source_id,
            "query_original": original,
            "query_rewritten": rewritten,
            "stratum": stratum,
            "cell": cell,
            "cell_family": cell_family,
            "intent": intent,
            "shape": shape,
            "dataset_path": path,
            "dataset_sha256": digest,
            "reference_frame": frame,
            "expressible_if": expressible,
            "ambiguity_degree": None,
            "expected_outcome": "miss" if frame is None else "hit",
            "expected_bucket": 1 if frame is None else None,
        }
        return row

    cases = [
        rec(
            "c1-01",
            source_id="authored-c1-overlap-lists",
            original="which subscribers are on the newsletter and the podcast but not the webinar",
            rewritten="Which subscribers are on the newsletter and the podcast list but not the webinar list?",
            stratum="adversarial",
            cell=1,
            intent=OVERLAP,
            shape="long",
            frame=None,
            expressible=["Venn", "Euler", "UpSet"],
        ),
        rec(
            "c1-02",
            source_id="authored-c1-overlap-clinics",
            original="how do the eight clinics overlap in the conditions they treat",
            rewritten="How do the eight clinics overlap in the conditions they treat?",
            stratum="adversarial",
            cell=1,
            intent=OVERLAP,
            shape="wide",
            frame=None,
            expressible=["Venn", "Euler", "UpSet"],
        ),
        rec(
            "c1-03",
            source_id="authored-c1-simplex-vote",
            original="how the vote splits between the three parties in every district",
            rewritten="How does the vote split between the three parties in every district?",
            stratum="adversarial",
            cell=1,
            intent=SIMPLEX,
            shape="wide_sparse",
            frame=None,
            expressible=["Ternary"],
        ),
        rec(
            "c1-04",
            source_id="authored-c1-od-freight",
            original="where does freight travel between the seven depots",
            rewritten="Where does freight travel between the seven depots?",
            stratum="adversarial",
            cell=1,
            intent=OD_FLOW,
            shape="nested",
            frame=None,
            expressible=["Flow Map"],
        ),
        rec(
            "c3-01",
            source_id="authored-c3-silent-drop-stores",
            original="compare 2023 revenue across all of our stores",
            rewritten="Compare 2023 revenue across all of our stores.",
            stratum="common_path",
            cell=3,
            cell_family="silent_row_drop",
            intent="comparison across categories",
            shape="long",
            frame=_frame("Bar Chart", {"x": "store", "y": "revenue"}, {}),
        ),
        rec(
            "c3-02",
            source_id="authored-c3-silent-drop-skus",
            original="rank every product by total units sold",
            rewritten="Rank every product by total units sold.",
            stratum="common_path",
            cell=3,
            cell_family="silent_row_drop",
            intent="ranking / top-N",
            shape="wide",
            frame=_frame(
                "Bar Chart",
                {"x": "sku", "y": "units_total"},
                {"sort": [{"field": "units_total", "dir": "desc", "nulls": "last"}]},
            ),
        ),
        rec(
            "c2adv-01",
            source_id="authored-c2adv-unpivot-months",
            original="plot monthly visits for each acquisition channel",
            rewritten="Plot monthly visits for each acquisition channel.",
            stratum="adversarial",
            cell=2,
            intent="trend over time",
            shape="wide",
            frame=_frame(
                "Line Chart",
                {"x": "month", "y": "visits", "color": "channel"},
                {"raw_sql": c2["c2adv-01"][1]},
            ),
        ),
        rec(
            "c2adv-02",
            source_id="authored-c2adv-union-phases",
            original="compare each student's score before and after the course",
            rewritten="Compare each student's score before and after the course.",
            stratum="adversarial",
            cell=2,
            intent="comparison across categories",
            shape="wide",
            frame=_frame(
                "Grouped Bar Chart",
                {"x": "student", "y": "score", "group": "phase"},
                {"raw_sql": c2["c2adv-02"][1]},
            ),
        ),
        rec(
            "c2adv-03",
            source_id="authored-c2adv-unpivot-survey",
            original="what is the average rating for each survey question",
            rewritten="What is the average rating for each survey question?",
            stratum="adversarial",
            cell=2,
            intent="comparison across categories",
            shape="wide_sparse",
            frame=_frame(
                "Bar Chart",
                {"x": "question", "y": "avg_rating"},
                {"raw_sql": c2["c2adv-03"][1]},
            ),
        ),
        rec(
            "c2adv-04",
            source_id="authored-c2adv-window-closed",
            original="show the cumulative share of tickets closed by day",
            rewritten="Show the cumulative share of tickets closed by day.",
            stratum="adversarial",
            cell=2,
            intent="trend over time",
            shape="wide_sparse",
            frame=_frame(
                "Area Chart",
                {"x": "day", "y": "cumulative_pct"},
                {"raw_sql": c2["c2adv-04"][1]},
            ),
        ),
        rec(
            "c2adv-05",
            source_id="authored-c2adv-json-fields",
            original="is a higher price linked to a better rating",
            rewritten="Is a higher price linked to a better rating?",
            stratum="adversarial",
            cell=2,
            intent="correlation between measures",
            shape="nested",
            frame=_frame(
                "Scatter Plot",
                {"x": "price", "y": "rating"},
                {"raw_sql": c2["c2adv-05"][1]},
            ),
        ),
        rec(
            "c2adv-06",
            source_id="authored-c2adv-json-array",
            original="which five articles carry the most tags",
            rewritten="Which five articles carry the most tags?",
            stratum="adversarial",
            cell=2,
            intent="ranking / top-N",
            shape="nested",
            frame=_frame(
                "Bar Chart",
                {"x": "article", "y": "tag_count"},
                {"raw_sql": c2["c2adv-06"][1]},
            ),
        ),
        rec(
            "c2adv-07",
            source_id="authored-c2adv-strptime-weekly",
            original="plot weekly order revenue",
            rewritten="Plot weekly order revenue.",
            stratum="adversarial",
            cell=2,
            intent="trend over time",
            shape="wide",
            frame=_frame(
                "Line Chart",
                {"x": "week", "y": "revenue"},
                {"raw_sql": c2["c2adv-07"][1]},
            ),
        ),
        rec(
            "c2adv-08",
            source_id="authored-c2adv-window-vs-average",
            original="how far is each team's goal difference from the league average",
            rewritten="How far is each team's goal difference from the league average?",
            stratum="adversarial",
            cell=2,
            intent="comparison across categories",
            shape="wide",
            frame=_frame(
                "Bar Chart",
                {"x": "team", "y": "vs_average"},
                {"raw_sql": c2["c2adv-08"][1]},
            ),
        ),
    ]
    doc = {
        "id_prefix": "auth-",
        "dataset_prefix": "eval/data/authored-",
        "counts": {"cell1": 4, "cell3": 2, "cell2_adversarial": 8},
        "cases": cases,
    }
    OUT.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUT} ({len(cases)} cases)")


if __name__ == "__main__":
    build()
