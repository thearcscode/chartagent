"""One-shot authoring of corpus/pre-registration.json (issue #85).

Reads nvBench 1.0 sqlite extracts from /tmp/nvbench/db and writes parquet
files, the pre-registration, NOTICE, and the dated authoring note.
Not a library surface. Re-running after the tag is cut is a freeze break.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from chartagent.frame.input import InputFrame
from chartagent.transform.engine import open_connection
from chartagent.transform.raw_sql import validate_raw_sql

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "corpus" / "data"
DB = Path("/tmp/nvbench/db")
BASE = {"width": 640, "height": 400}
SMALL = {"width": 180, "height": 90}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(name: str, table: pa.Table) -> tuple[str, str]:
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / f"{name}.parquet"
    pq.write_table(table, path)
    rel = f"corpus/data/{name}.parquet"
    return rel, _sha(path)


def _sql_table(db: str, query: str) -> pa.Table:
    con = sqlite3.connect(DB / f"{db}.sqlite")
    try:
        cur = con.execute(query)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    finally:
        con.close()
    columns: dict[str, list[Any]] = {col: [] for col in cols}
    for row in rows:
        for i, col in enumerate(cols):
            value = row[i]
            columns[col].append(None if value == "" else value)
    return pa.table(columns)


def _frame(
    chart: str,
    encodings: dict[str, str],
    transform: dict[str, Any],
    *,
    size: dict[str, int] | None = None,
) -> dict[str, Any]:
    frame = {
        "chart_spec": {
            "chartType": chart,
            "encodings": encodings,
            "baseSize": size or BASE,
        },
        "x_chartagent": {"transform": transform},
    }
    InputFrame.model_validate(frame)
    return frame


def _group_count(field: str, out: str = "n") -> dict[str, Any]:
    return {
        "group_by": [field],
        "aggregate": [{"name": out, "op": "count"}],
    }


def _group_sum(group: str, field: str, out: str) -> dict[str, Any]:
    return {
        "group_by": [group],
        "aggregate": [{"name": out, "op": "sum", "field": field}],
    }


def _group_avg(group: str, field: str, out: str) -> dict[str, Any]:
    return {
        "group_by": [group],
        "aggregate": [{"name": out, "op": "mean", "field": field}],
    }


def _group_max(group: str, field: str, out: str) -> dict[str, Any]:
    return {
        "group_by": [group],
        "aggregate": [{"name": out, "op": "max", "field": field}],
    }


def _with_json(table: pa.Table, extras: list[str], col: str = "details") -> pa.Table:
    keep = [name for name in table.column_names if name not in extras]
    con = duckdb.connect()
    con.register("t", table)
    quoted = ", ".join(f"'{name}', {name}" for name in extras)
    out = con.execute(
        f"SELECT {', '.join(keep)}, json_object({quoted}) AS {col} FROM t"
    ).to_arrow_table()
    con.close()
    return out


def _add_sparse(table: pa.Table, n: int = 8) -> pa.Table:
    for i in range(n):
        table = table.append_column(f"unused_{i}", pa.array([None] * table.num_rows))
    return table


def _counts_one_row(pairs: list[tuple[str, int]]) -> pa.Table:
    return pa.table({key: [value] for key, value in pairs})


def _unpivot_sql(columns: list[str], *, value: str, name: str) -> str:
    return (
        f"SELECT {name}, {value} FROM source "
        f"UNPIVOT ({value} FOR {name} IN ({', '.join(columns)}))"
    )


def _check_sql(sql: str) -> None:
    con = open_connection()
    try:
        validate_raw_sql(con, sql)
    finally:
        con.close()


def build() -> None:
    DATA.mkdir(parents=True, exist_ok=True)

    faculty = _sql_table("activity_1", "SELECT FacID, Lname, Fname, Rank, Sex, Building FROM Faculty")
    faculty_students = _sql_table(
        "activity_1",
        "SELECT T1.Rank, T1.Sex, T1.Building, T1.FacID, T2.StuID "
        "FROM Faculty AS T1 JOIN Student AS T2 ON T1.FacID = T2.Advisor",
    )
    hof = _sql_table("baseball_1", "SELECT player_id, yearid, votes, inducted, category FROM hall_of_fame")
    home = _sql_table(
        "baseball_1",
        "SELECT year, league_id, team_id, games, openings, attendance FROM home_game",
    )
    mill = _sql_table("architecture", "SELECT id, name, type, built_year, location FROM mill")
    architect_bridge = _sql_table(
        "architecture",
        "SELECT T1.id AS architect_id, T1.name, T1.nationality, "
        "T2.id AS bridge_id, T2.length_meters "
        "FROM architect AS T1 JOIN bridge AS T2 ON T1.id = T2.architect_id",
    )
    bookings = _sql_table(
        "apartment_rentals",
        "SELECT apt_booking_id, booking_status_code, booking_start_date, guest_id FROM Apartment_Bookings",
    )
    guests = _sql_table(
        "apartment_rentals",
        "SELECT guest_id, gender_code, date_of_birth FROM Guests",
    )
    apartments = _sql_table(
        "apartment_rentals",
        "SELECT apt_id, apt_number, bathroom_count, bedroom_count, room_count FROM Apartments",
    )
    allergy_student = _sql_table(
        "allergy_1",
        "SELECT StuID, LName, Age, Sex, city_code FROM Student",
    )
    people = _sql_table("candidate_poll", "SELECT People_ID, Name, Height, Weight, Date_of_Birth FROM people")
    body = _sql_table("body_builder", "SELECT Body_Builder_ID, Snatch, Clean_Jerk, Total FROM body_builder")
    cars = _sql_table("car_1", "SELECT Id, Cylinders, Accelerate, Weight, Year FROM cars_data")
    countries = _sql_table(
        "car_1",
        "SELECT T1.CountryName, T1.CountryId, T2.Id AS maker_id "
        "FROM COUNTRIES AS T1 JOIN CAR_MAKERS AS T2 ON T1.CountryId = T2.Country",
    )
    climber = _sql_table("climbing", "SELECT Climber_ID, Name, Country, Time, Points FROM climber")
    singer = _sql_table(
        "concert_singer",
        "SELECT Singer_ID, Name, Country, Age, Song_release_year, Is_male FROM singer",
    )
    customers = _sql_table(
        "driving_school",
        "SELECT customer_id, customer_status_code, amount_outstanding, date_became_customer FROM Customers",
    )
    station = _sql_table(
        "bike_1",
        "SELECT id, name, lat, long, dock_count, city FROM station",
    )
    trip = _sql_table(
        "bike_1",
        "SELECT id, start_station_name, start_station_id, duration FROM trip",
    )
    weather = _sql_table(
        "bike_1",
        "SELECT date, max_temperature_f, zip_code FROM weather",
    )
    farm_city = _sql_table(
        "farm",
        "SELECT Official_Name, Status, Population, Area_km_2 FROM city",
    )

    # Wide rank extract for cell-2 unpivot (one row, ranks as columns).
    rank_wide = pa.table(
        {
            "Professor": [27],
            "AsstProf": [15],
            "AssocProf": [8],
            "Instructor": [8],
        }
    )
    # Non-ISO booking months.
    month_rows = [
        ("Jan 2016", 3),
        ("Feb 2016", 2),
        ("Mar 2016", 4),
        ("Apr 2016", 1),
        ("May 2016", 5),
    ]
    months = pa.table(
        {
            "period": [r[0] for r in month_rows],
            "bookings": [r[1] for r in month_rows],
        }
    )
    # Authored datasets.
    campaigns = pa.table(
        {
            "customer": ["a", "a", "b", "b", "c", "d", "e"] * 2,
            "set_name": ["spring", "app", "spring", "fall", "app", "spring", "fall"]
            + ["spring", "app", "fall", "app", "spring", "fall", "app"],
        }
    )
    segments = pa.table(
        {
            "segment": [f"s{i}" for i in range(12) for _ in range(4)],
            "product": [f"p{(i + j) % 9}" for i in range(12) for j in range(4)],
        }
    )
    blends = pa.table(
        {
            "blend": ["A", "B", "C", "D", "E"],
            "clay": [0.5, 0.2, 0.1, 0.33, 0.6],
            "silt": [0.3, 0.5, 0.4, 0.33, 0.2],
            "sand": [0.2, 0.3, 0.5, 0.34, 0.2],
        }
    )
    commute = pa.table(
        {
            "origin": ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"],
            "destination": ["Brooklyn", "Manhattan", "Manhattan", "Manhattan", "Manhattan"],
            "riders": [12000, 9000, 8000, 7000, 2000],
        }
    )
    sales_wide = pa.table(
        {
            "region": ["north", "south", "east", "west"],
            "q1": [10, 12, 8, 9],
            "q2": [11, 9, 14, 7],
            "q3": [13, 15, 10, 8],
            "q4": [16, 11, 12, 10],
        }
    )
    ohlc = pa.table(
        {
            "session": ["2024-03-04", "2024-03-01", "2024-03-03", "2024-03-02"],
            "open": [10.0, 11.0, 10.5, 12.0],
            "high": [12.0, 11.5, 11.0, 12.5],
            "low": [9.5, 10.0, 10.0, 11.0],
            "close": [11.5, 10.2, 10.8, 11.2],
        }
    )
    scores = pa.table(
        {
            "cohort": ["A"] * 20 + ["B"] * 20 + ["C"] * 20,
            "score": list(range(20)) + list(range(5, 25)) + list(range(10, 30)),
        }
    )
    pyramid = pa.table(
        {
            "band": ["under 18", "18-34", "35-54", "55+"] * 2,
            "people": [20, 40, 35, 15, 18, 38, 32, 14],
            "sex": ["M"] * 4 + ["F"] * 4,
        }
    )
    empty_filter = pa.table(
        {
            "region": ["north", "south"],
            "revenue": [100, 80],
        }
    )
    hostile = pa.table(
        {
            "Unnamed: 3": ["alpha", "beta", "gamma", "delta"],
            "date": ["Q1", "Q2", "Q3", "Q4"],
            "amount": [10, 20, 15, 25],
        }
    )
    words = pa.table(
        {
            "term": ["refund", "shipping", "size", "quality", "delay"],
            "mentions": [40, 28, 22, 18, 12],
        }
    )
    waffle_src = pa.table(
        {
            "category": ["win", "loss", "draw"],
            "n": [12, 7, 3],
        }
    )
    compound = pa.table(
        {
            "month": ["2024-01", "2024-02", "2024-03", "2024-04"],
            "revenue": [100, 120, 90, 140],
            "churn": [0.04, 0.05, 0.06, 0.03],
        }
    )
    perf = pa.table(
        {
            "team": ["red", "blue", "green", "gold"],
            "revenue": [10, 20, 15, 25],
            "profit": [2, 5, 3, 8],
            "nps": [30, 40, 25, 50],
            "tickets": [4, 2, 7, 1],
        }
    )

    con = duckdb.connect()
    con.register("g", guests)
    guest_year_pairs = [
        (f"y_{year}", int(count))
        for year, count in con.execute(
            "SELECT strftime(try_cast(date_of_birth AS TIMESTAMP), '%Y') AS y, "
            "count(*) FROM g WHERE gender_code = 'Male' AND y IS NOT NULL "
            "GROUP BY y ORDER BY y"
        ).fetchall()
    ]
    con.register("h", hof)
    hof_year_pairs = [
        (f"y_{year}", int(count))
        for year, count in con.execute(
            "SELECT yearid, count(*) FROM h GROUP BY yearid ORDER BY yearid"
        ).fetchall()
    ]
    con.register("f", faculty)
    asst_pairs = [
        (str(sex), int(count))
        for sex, count in con.execute(
            "SELECT Sex, count(*) FROM f WHERE Rank = 'AsstProf' GROUP BY Sex"
        ).fetchall()
    ]
    con.close()
    guest_year_wide = _counts_one_row(guest_year_pairs)
    hof_year_wide = _counts_one_row(hof_year_pairs)
    asst_sex_wide = _counts_one_row(asst_pairs)

    unpivot_sql = _unpivot_sql(
        ["Professor", "AsstProf", "AssocProf", "Instructor"],
        value="faculty_count",
        name="rank",
    )
    guest_unpivot_sql = _unpivot_sql(
        [key for key, _ in guest_year_pairs], value="n", name="year_label"
    )
    hof_unpivot_sql = _unpivot_sql(
        [key for key, _ in hof_year_pairs], value="n", name="year_label"
    )
    asst_unpivot_sql = _unpivot_sql(
        [key for key, _ in asst_pairs], value="n", name="sex"
    )
    union_sql = (
        "SELECT region, 'q1' AS quarter, q1 AS revenue FROM source "
        "UNION ALL SELECT region, 'q2', q2 FROM source "
        "UNION ALL SELECT region, 'q3', q3 FROM source "
        "UNION ALL SELECT region, 'q4', q4 FROM source"
    )
    strptime_plain_sql = (
        "SELECT strptime(period, '%b %Y') AS month, bookings FROM source"
    )
    window_sql = (
        "SELECT yearid, n, SUM(n) OVER (ORDER BY yearid) AS running "
        "FROM (SELECT yearid, count(*) AS n FROM source GROUP BY yearid)"
    )
    pivot_sql = (
        "PIVOT source ON Sex IN ('M', 'F') USING count(*) GROUP BY Rank"
    )
    cond_sql = (
        "SELECT Rank, "
        "count(*) FILTER (WHERE Sex = 'M') AS men, "
        "count(*) FILTER (WHERE Sex = 'F') AS women "
        "FROM source GROUP BY Rank"
    )
    for sql in (
        unpivot_sql,
        guest_unpivot_sql,
        hof_unpivot_sql,
        asst_unpivot_sql,
        union_sql,
        strptime_plain_sql,
        window_sql,
        pivot_sql,
        cond_sql,
    ):
        _check_sql(sql)

    paths: dict[str, tuple[str, str]] = {}

    def pin(rid: str, table: pa.Table) -> None:
        paths[rid] = _write(rid, table)

    pin("r01", hof)
    pin("r02", mill)
    pin("r03", home)
    pin("r04", faculty_students)
    pin("r05", bookings)
    pin("r06", cars)
    pin("r07", countries)
    pin("r08", singer)
    pin("r09", allergy_student)
    pin("r10", people)
    pin("r11", body)
    pin("r12", faculty)
    pin("r13", faculty)
    pin("r14", _with_json(singer, ["Song_release_year", "Is_male"]))
    pin("r15", trip)
    pin("r16", architect_bridge)
    pin("r17", customers)
    pin("r18", climber)  # Time + Points: wide measures
    pin("r19", station)
    pin("r20", _with_json(allergy_student, ["LName", "Sex"]))
    pin("r21", _add_sparse(faculty, 8))
    pin("r22", _add_sparse(apartments, 8))
    pin("r23", rank_wide)
    pin("r24", guest_year_wide)
    pin("r25", hof_year_wide)
    pin("r26", _add_sparse(asst_sex_wide, 6))
    pin("r27", home)
    pin("r28", weather)
    pin("r29", faculty)
    pin("r30", _with_json(home, ["league_id", "team_id"]))
    pin("r31", campaigns)
    pin("r32", segments)
    pin("r33", blends)
    pin("r34", commute)
    pin("r35", sales_wide)
    pin("r36", sales_wide)
    pin("r37", months)
    pin("r38", _add_sparse(hof, 6))
    pin("r39", _add_sparse(faculty, 6))
    pin("r40", _add_sparse(faculty, 6))
    pin("r41", _with_json(empty_filter.append_column("note", pa.array(["x", "y"])), ["note"]))
    pin("r42", _with_json(pyramid.append_column("note", pa.array(["x"] * 8)), ["note"]))
    pin("r43", ohlc)
    pin(
        "r44",
        _with_json(
            scores.append_column("note", pa.array(["x"] * scores.num_rows)),
            ["note"],
        ),
    )
    pin("r45", _add_sparse(words, 6))
    share_long = pa.table(
        {
            "category": ["hardware", "hardware", "clothes", "clothes", "food", "food", "other", "other"],
            "region": ["north", "south"] * 4,
            "share": [20, 15, 10, 25, 30, 10, 5, 8],
        }
    )
    pin("r46", _add_sparse(share_long, 6))
    pin("r47", waffle_src)
    pin("r48", _add_sparse(perf, 6))
    pin("r49", _with_json(compound, ["churn"]))
    pin("r50", hostile)
    pin("s01", farm_city)
    pin("s02", sales_wide)
    pin("s03", campaigns)
    pin("s04", empty_filter)
    pin("s05", _add_sparse(perf, 6))

    def rec(
        rid: str,
        *,
        source: str,
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
        degree: int | None = None,
        replaces: dict[str, Any] | None = None,
        draw_order: int | None = None,
    ) -> dict[str, Any]:
        path, digest = paths[rid]
        row: dict[str, Any] = {
            "id": rid,
            "source": source,
            "source_id": source_id,
            "query_original": original,
            "query_rewritten": rewritten,
            "stratum": stratum,
            "cell": cell,
            "intent": intent,
            "shape": shape,
            "dataset_path": path,
            "dataset_sha256": digest,
            "reference_frame": frame,
            "expected_outcome": "miss" if frame is None else "hit",
        }
        if cell_family is not None:
            row["cell_family"] = cell_family
        if expressible is not None:
            row["expressible_if"] = expressible
            row["expected_bucket"] = 1
        if degree is not None:
            row["ambiguity_degree"] = degree
        if replaces is not None:
            row["replaces"] = replaces
        if draw_order is not None:
            row["draw_order"] = draw_order
        return row

    requests = [
        rec(
            "r01",
            source="nvbench1",
            source_id="156@2",
            original="How many players enter hall of fame each year. Show the tendency.",
            rewritten="How many players enter the hall of fame each year? Show the tendency.",
            stratum="common_path",
            cell=0,
            intent="trend over time",
            shape="long",
            frame=_frame(
                "Line Chart",
                {"x": "yearid", "y": "n"},
                _group_count("yearid"),
            ),
        ),
        rec(
            "r02",
            source="nvbench1",
            source_id="108@0",
            original="How many mills of 'Grondzeiler' type are built in each year? Give me the trend.",
            rewritten="How many mills of Grondzeiler type were built in each year? Give me the trend.",
            stratum="common_path",
            cell=0,
            intent="trend over time",
            shape="long",
            frame=_frame(
                "Line Chart",
                {"x": "built_year", "y": "n"},
                {
                    "filter": {
                        "kind": "eq",
                        "args": [
                            {"kind": "col", "name": "type"},
                            {"kind": "lit", "value": "Grondzeiler"},
                        ],
                    },
                    **_group_count("built_year"),
                },
            ),
        ),
        rec(
            "r03",
            source="nvbench1",
            source_id="171@3",
            original="For each year, return the year and the average number of attendance at home games.",
            rewritten="For each year, return the year and the average number of attendance at home games.",
            stratum="common_path",
            cell=0,
            intent="trend over time",
            shape="wide",
            frame=_frame(
                "Line Chart",
                {"x": "year", "y": "avg_attendance"},
                _group_avg("year", "attendance", "avg_attendance"),
            ),
        ),
        rec(
            "r04",
            source="nvbench1",
            source_id="5@2",
            original="how many students are advised by each rank of faculty? List the rank and the number of students.",
            rewritten="How many students are advised by each rank of faculty? List the rank and the number of students.",
            stratum="common_path",
            cell=0,
            intent="comparison across categories",
            shape="long",
            frame=_frame(
                "Bar Chart",
                {"x": "Rank", "y": "n"},
                _group_count("Rank"),
            ),
        ),
        rec(
            "r05",
            source="nvbench1",
            source_id="74@5",
            original="How many bookings does each booking status have? List the booking status code and the number of corresponding bookings.",
            rewritten="How many bookings does each booking status have? List the booking status code and the number of bookings.",
            stratum="common_path",
            cell=0,
            intent="flow or transition between states",
            shape="long",
            frame=_frame(
                "Funnel Chart",
                {"y": "booking_status_code", "size": "n"},
                _group_count("booking_status_code"),
            ),
        ),
        rec(
            "r06",
            source="nvbench1",
            source_id="432@3",
            original="what is the maximum accelerate for all the different cylinders?",
            rewritten="What is the maximum accelerate for all the different cylinders?",
            stratum="common_path",
            cell=0,
            intent="comparison across categories",
            shape="wide",
            frame=_frame(
                "Bar Chart",
                {"x": "Cylinders", "y": "max_accelerate"},
                _group_max("Cylinders", "Accelerate", "max_accelerate"),
            ),
        ),
        rec(
            "r07",
            source="nvbench1",
            source_id="411@1",
            original="what are the countries having at least one car maker? List name and id.",
            rewritten="What are the countries that have at least one car maker? List name and id.",
            stratum="common_path",
            cell=0,
            intent="comparison across categories",
            shape="long",
            frame=_frame(
                "Bar Chart",
                {"x": "CountryName", "y": "n"},
                _group_count("CountryName"),
            ),
        ),
        rec(
            "r08",
            source="nvbench1",
            source_id="696@2",
            original="Show the average of age from each country",
            rewritten="Show the average age from each country.",
            stratum="common_path",
            cell=0,
            intent="comparison across categories",
            shape="wide",
            frame=_frame(
                "Bar Chart",
                {"x": "Country", "y": "avg_age"},
                _group_avg("Country", "Age", "avg_age"),
            ),
        ),
        rec(
            "r09",
            source="nvbench1",
            source_id="62@2",
            original="how old is each student and how many students are each age?",
            rewritten="How old is each student, and how many students are each age?",
            stratum="common_path",
            cell=0,
            intent="distribution of one measure",
            shape="long",
            frame=_frame("Histogram", {"x": "Age"}, {}),
        ),
        rec(
            "r10",
            source="nvbench1",
            source_id="390@3",
            original="What is the relationship between  Height and  Weight ?",
            rewritten="What is the relationship between Height and Weight?",
            stratum="common_path",
            cell=0,
            intent="correlation between measures",
            shape="wide",
            frame=_frame("Scatter Plot", {"x": "Height", "y": "Weight"}, {}),
        ),
        rec(
            "r11",
            source="nvbench1",
            source_id="353@2",
            original="What is the relationship between  Clean_Jerk and  Total ?",
            rewritten="What is the relationship between Clean_Jerk and Total?",
            stratum="common_path",
            cell=0,
            intent="correlation between measures",
            shape="wide",
            frame=_frame("Scatter Plot", {"x": "Clean_Jerk", "y": "Total"}, {}),
        ),
        rec(
            "r12",
            source="nvbench1",
            source_id="20@2",
            original="I want to know the proportion of faculty members for each sex.",
            rewritten="I want to know the proportion of faculty members for each sex.",
            stratum="common_path",
            cell=0,
            intent="part-to-whole",
            shape="long",
            frame=_frame(
                "Pie Chart",
                {"color": "Sex", "size": "n"},
                _group_count("Sex"),
            ),
        ),
        rec(
            "r13",
            source="nvbench1",
            source_id="19@2",
            original="I want to know the proportion of faculty members for each rank.",
            rewritten="I want to know the proportion of faculty members for each rank.",
            stratum="common_path",
            cell=0,
            intent="part-to-whole",
            shape="long",
            frame=_frame(
                "Pie Chart",
                {"color": "Rank", "size": "n"},
                _group_count("Rank"),
            ),
        ),
        rec(
            "r14",
            source="nvbench1",
            source_id="689@1",
            original="Show all countries and the number of singers in each country. Show the proportion.",
            rewritten="Show all countries and the number of singers in each country. Show the proportion.",
            stratum="common_path",
            cell=0,
            intent="part-to-whole",
            shape="nested",
            frame=_frame(
                "Pie Chart",
                {"color": "Country", "size": "n"},
                _group_count("Country"),
            ),
        ),
        rec(
            "r15",
            source="nvbench1",
            source_id="310@0",
            original="Find the ids and names of stations from which at least 200 trips started.",
            rewritten="Find the ids and names of stations from which at least 200 trips started.",
            stratum="common_path",
            cell=0,
            intent="ranking / top-N",
            shape="long",
            frame=_frame(
                "Lollipop Chart",
                {"x": "start_station_name", "y": "n"},
                {
                    **_group_count("start_station_name"),
                    "having": {
                        "kind": "gte",
                        "args": [
                            {"kind": "col", "name": "n"},
                            {"kind": "lit", "value": 200},
                        ],
                    },
                    "sort": [{"field": "n", "dir": "desc", "nulls": "last"}],
                },
            ),
        ),
        rec(
            "r16",
            source="nvbench1",
            source_id="113@1",
            original="What are the ids and names of the architects who built at least 3 bridges . Show the proportion.",
            rewritten="What are the ids and names of the architects who built at least 3 bridges? Show the proportion.",
            stratum="common_path",
            cell=0,
            intent="ranking / top-N",
            shape="wide",
            frame=_frame(
                "Bar Chart",
                {"x": "name", "y": "n"},
                {
                    **_group_count("name"),
                    "having": {
                        "kind": "gte",
                        "args": [
                            {"kind": "col", "name": "n"},
                            {"kind": "lit", "value": 3},
                        ],
                    },
                },
            ),
        ),
        rec(
            "r17",
            source="nvbench1",
            source_id="1244@2",
            original="For each customer status code, how many customers are classified that way. Show the proportion.",
            rewritten="For each customer status code, how many customers are classified that way? Show the proportion.",
            stratum="common_path",
            cell=0,
            intent="part-to-whole",
            shape="long",
            frame=_frame(
                "Pie Chart",
                {"color": "customer_status_code", "size": "n"},
                _group_count("customer_status_code"),
            ),
        ),
        rec(
            "r18",
            source="nvbench1",
            source_id="485@2",
            original="How many climbers are from each country.",
            rewritten="How many climbers are from each country?",
            stratum="common_path",
            cell=0,
            intent="geographic distribution",
            shape="wide",
            frame=_frame(
                "Choropleth",
                {"id": "Country", "color": "n"},
                _group_count("Country"),
            ),
        ),
        rec(
            "r19",
            source="nvbench1",
            source_id="307@2",
            original="Show maximal lat from each city",
            rewritten="Show the maximal lat from each city.",
            stratum="common_path",
            cell=0,
            intent="comparison across categories",
            shape="wide",
            frame=_frame(
                "Bar Chart",
                {"x": "city", "y": "lat_max"},
                _group_max("city", "lat", "lat_max"),
            ),
        ),
        rec(
            "r20",
            source="nvbench1",
            source_id="59@4",
            original="How many students live in each city.",
            rewritten="How many students live in each city?",
            stratum="common_path",
            cell=0,
            intent="comparison across categories",
            shape="nested",
            frame=_frame(
                "Bar Chart",
                {"x": "city_code", "y": "n"},
                _group_count("city_code"),
            ),
        ),
        rec(
            "r21",
            source="nvbench1",
            source_id="9@2",
            original="Show how many rank from each rank",
            rewritten="Show how many rank from each rank.",
            stratum="common_path",
            cell=0,
            intent="comparison across categories",
            shape="wide_sparse",
            frame=_frame(
                "Bar Chart",
                {"x": "Rank", "y": "n"},
                _group_count("Rank"),
            ),
        ),
        rec(
            "r22",
            source="nvbench1",
            source_id="97@1",
            original="Return the apartment number and the number of rooms for each apartment.",
            rewritten="Return the apartment number and the number of rooms for each apartment.",
            stratum="common_path",
            cell=0,
            intent="single value against a target",
            shape="wide_sparse",
            frame=_frame(
                "Bullet Chart",
                {"y": "apt_number", "x": "room_count", "goal": "bedroom_count"},
                {},
            ),
        ),
        rec(
            "r23",
            source="nvbench1",
            source_id="14@0",
            original="Show the proportion of the number of ranks for each rank.",
            rewritten="Show the proportion of the number of ranks for each rank.",
            stratum="common_path",
            cell=2,
            intent="part-to-whole",
            shape="wide",
            frame=_frame(
                "Pie Chart",
                {"color": "rank", "size": "faculty_count"},
                {"raw_sql": unpivot_sql},
            ),
        ),
        rec(
            "r24",
            source="nvbench1",
            source_id="80@1",
            original="Return the number of the date of birth for all the guests with gender code \"Male\".",
            rewritten="Return the number of the date of birth for all the guests with gender code Male.",
            stratum="common_path",
            cell=2,
            intent="trend over time",
            shape="wide",
            frame=_frame(
                "Line Chart",
                {"x": "year_label", "y": "n"},
                {"raw_sql": guest_unpivot_sql},
            ),
        ),
        rec(
            "r25",
            source="nvbench1",
            source_id="157@1",
            original="I want to see trend of the number of yearid by yearid",
            rewritten="I want to see the trend of the number of yearid by yearid.",
            stratum="common_path",
            cell=2,
            intent="trend over time",
            shape="wide",
            frame=_frame(
                "Line Chart",
                {"x": "year_label", "y": "n"},
                {"raw_sql": hof_unpivot_sql},
            ),
        ),
        rec(
            "r26",
            source="nvbench1",
            source_id="21@1",
            original="Show the number of male and female assistant professors.",
            rewritten="Show the number of male and female assistant professors.",
            stratum="common_path",
            cell=2,
            intent="part-to-whole",
            shape="wide_sparse",
            frame=_frame(
                "Pie Chart",
                {"color": "sex", "size": "n"},
                {"raw_sql": asst_unpivot_sql},
            ),
        ),
        rec(
            "r27",
            source="nvbench1",
            source_id="169@0",
            original="Show the trend about the number of attendance at home games change over the years, bin year into year interval.",
            rewritten="Show the trend of how the number of attendance at home games changes over the years; bin year into a year interval.",
            stratum="common_path",
            cell=3,
            intent="trend over time",
            shape="wide",
            cell_family="discrete_overflow",
            frame=_frame(
                "Bar Chart",
                {"x": "year", "y": "attendance_sum"},
                _group_sum("year", "attendance", "attendance_sum"),
                size=SMALL,
            ),
        ),
        rec(
            "r28",
            source="nvbench1",
            source_id="314@3",
            original="Give me the number of the dates when the max temperature was higher than 85.",
            rewritten="Give me the number of the dates when the max temperature was higher than 85.",
            stratum="common_path",
            cell=3,
            intent="comparison across categories",
            shape="long",
            cell_family="discrete_overflow",
            frame=_frame(
                "Bar Chart",
                {"x": "date", "y": "n"},
                {
                    "filter": {
                        "kind": "gt",
                        "args": [
                            {"kind": "col", "name": "max_temperature_f"},
                            {"kind": "lit", "value": 85},
                        ],
                    },
                    **_group_count("date"),
                },
                size=SMALL,
            ),
        ),
        rec(
            "r29",
            source="authored",
            source_id="authored-ii-a",
            original="show faculty numbers",
            rewritten="Show faculty numbers.",
            stratum="common_path",
            cell=4,
            intent="comparison across categories",
            shape="long",
            cell_family="ii",
            degree=2,
            frame=_frame(
                "Bar Chart",
                {"x": "Rank", "y": "n"},
                _group_count("Rank"),
            ),
        ),
        rec(
            "r30",
            source="authored",
            source_id="authored-ii-b",
            original="how is attendance doing",
            rewritten="How is attendance doing?",
            stratum="common_path",
            cell=4,
            intent="trend over time",
            shape="nested",
            cell_family="ii",
            degree=2,
            frame=_frame(
                "Line Chart",
                {"x": "year", "y": "attendance_sum"},
                _group_sum("year", "attendance", "attendance_sum"),
            ),
        ),
        rec(
            "r31",
            source="authored",
            source_id="authored-overlap-3",
            original="which customers are in both campaigns but not the app",
            rewritten="Which customers appear in both campaigns but not the app?",
            stratum="adversarial",
            cell=1,
            intent="set overlap / intersection structure",
            shape="long",
            frame=None,
            expressible=["Venn", "Euler", "UpSet"],
        ),
        rec(
            "r32",
            source="authored",
            source_id="authored-overlap-12",
            original="which of the twelve segments overlap on more than two products",
            rewritten="Which of the twelve segments overlap on more than two products?",
            stratum="adversarial",
            cell=1,
            intent="set overlap / intersection structure",
            shape="long",
            frame=None,
            expressible=["Venn", "Euler", "UpSet"],
        ),
        rec(
            "r33",
            source="authored",
            source_id="authored-simplex",
            original="how the three ingredients mix in every blend",
            rewritten="How do the three ingredients mix in every blend?",
            stratum="adversarial",
            cell=1,
            intent="compositional simplex",
            shape="long",
            frame=None,
            expressible=["Ternary"],
        ),
        rec(
            "r34",
            source="authored",
            source_id="authored-od-flow",
            original="commute flows between the five boroughs",
            rewritten="What are the commute flows between the five boroughs?",
            stratum="adversarial",
            cell=1,
            intent="origin–destination flow on a geography",
            shape="long",
            frame=None,
            expressible=["Flow Map"],
        ),
        rec(
            "r35",
            source="authored",
            source_id="authored-unpivot",
            original="show quarterly revenue for each region",
            rewritten="Show quarterly revenue for each region.",
            stratum="adversarial",
            cell=2,
            intent="trend over time",
            shape="wide",
            frame=_frame(
                "Line Chart",
                {"x": "quarter", "y": "revenue", "color": "region"},
                {"raw_sql": union_sql},
            ),
        ),
        rec(
            "r36",
            source="authored",
            source_id="authored-union",
            original="compare the four quarters of revenue across regions",
            rewritten="Compare the four quarters of revenue across regions.",
            stratum="adversarial",
            cell=2,
            intent="comparison across categories",
            shape="wide",
            frame=_frame(
                "Grouped Bar Chart",
                {"x": "quarter", "y": "revenue", "group": "region"},
                {"raw_sql": union_sql},
            ),
        ),
        rec(
            "r37",
            source="authored",
            source_id="authored-strptime",
            original="plot bookings by month for these month labels",
            rewritten="Plot bookings by month for these month labels.",
            stratum="adversarial",
            cell=2,
            intent="trend over time",
            shape="wide",
            frame=_frame(
                "Line Chart",
                {"x": "month", "y": "bookings"},
                {"raw_sql": strptime_plain_sql},
            ),
        ),
        rec(
            "r38",
            source="authored",
            source_id="authored-window",
            original="show a running total of hall of fame entries by year",
            rewritten="Show a running total of hall of fame entries by year.",
            stratum="adversarial",
            cell=2,
            intent="trend over time",
            shape="wide_sparse",
            frame=_frame(
                "Area Chart",
                {"x": "yearid", "y": "running"},
                {"raw_sql": window_sql},
            ),
        ),
        rec(
            "r39",
            source="authored",
            source_id="authored-pivot",
            original="count faculty by rank with men and women as columns",
            rewritten="Count faculty by rank, with men and women as columns.",
            stratum="adversarial",
            cell=2,
            intent="comparison across categories",
            shape="wide_sparse",
            frame=_frame(
                "Bar Chart",
                {"x": "Rank", "y": "M"},
                {"raw_sql": pivot_sql},
            ),
        ),
        rec(
            "r40",
            source="authored",
            source_id="authored-conditional",
            original="count men and women in each faculty rank",
            rewritten="Count men and women in each faculty rank.",
            stratum="adversarial",
            cell=2,
            intent="comparison across categories",
            shape="wide_sparse",
            frame=_frame(
                "Bar Chart",
                {"x": "Rank", "y": "men"},
                {"raw_sql": cond_sql},
            ),
        ),
        rec(
            "r41",
            source="authored",
            source_id="authored-empty-filter",
            original="show revenue for the west region only",
            rewritten="Show revenue for the west region only.",
            stratum="adversarial",
            cell=3,
            intent="comparison across categories",
            shape="nested",
            cell_family="excel_empty_after_filter",
            frame=_frame(
                "Bar Chart",
                {"x": "region", "y": "revenue"},
                {
                    "filter": {
                        "kind": "eq",
                        "args": [
                            {"kind": "col", "name": "region"},
                            {"kind": "lit", "value": "west"},
                        ],
                    }
                },
            ),
        ),
        rec(
            "r42",
            source="authored",
            source_id="authored-pyramid",
            original="show headcount in each age band",
            rewritten="Show headcount in each age band.",
            stratum="adversarial",
            cell=3,
            intent="ranking / top-N",
            shape="nested",
            cell_family="excel_pyramid_two_groups",
            frame=_frame(
                "Pyramid Chart",
                {"x": "band", "y": "people", "color": "sex"},
                {},
            ),
        ),
        rec(
            "r43",
            source="authored",
            source_id="authored-candlestick",
            original="show the session open high low and close",
            rewritten="Show the session open, high, low, and close.",
            stratum="adversarial",
            cell=3,
            intent="trend over time",
            shape="wide",
            cell_family="excel_candlestick_order",
            frame=_frame(
                "Candlestick Chart",
                {
                    "x": "session",
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                },
                {},
            ),
        ),
        rec(
            "r44",
            source="authored",
            source_id="authored-boxplot",
            original="compare the score spread across the three cohorts",
            rewritten="Compare the score spread across the three cohorts.",
            stratum="adversarial",
            cell=3,
            intent="distribution of one measure",
            shape="nested",
            cell_family="echarts_boxplot",
            frame=_frame("Boxplot", {"x": "cohort", "y": "score"}, {}),
        ),
        rec(
            "r45",
            source="authored",
            source_id="authored-wordcloud",
            original="show a word cloud of support mentions",
            rewritten="Show a word cloud of support mentions.",
            stratum="adversarial",
            cell=4,
            intent="ranking / top-N",
            shape="wide_sparse",
            cell_family="i",
            frame=_frame(
                "Bar Chart",
                {"x": "term", "y": "mentions"},
                {"sort": [{"field": "mentions", "dir": "desc", "nulls": "last"}]},
            ),
        ),
        rec(
            "r46",
            source="authored",
            source_id="authored-marimekko",
            original="draw a Marimekko of category share by region",
            rewritten="Draw a Marimekko of category share by region.",
            stratum="adversarial",
            cell=4,
            intent="part-to-whole",
            shape="wide_sparse",
            cell_family="i",
            frame=_frame(
                "Stacked Bar Chart",
                {"x": "category", "y": "share", "color": "region"},
                {},
            ),
        ),
        rec(
            "r47",
            source="authored",
            source_id="authored-waffle",
            original="make a waffle of match outcomes",
            rewritten="Make a waffle of match outcomes.",
            stratum="adversarial",
            cell=4,
            intent="part-to-whole",
            shape="wide",
            cell_family="i",
            frame=_frame(
                "Pie Chart",
                {"color": "category", "size": "n"},
                {},
            ),
        ),
        rec(
            "r48",
            source="authored",
            source_id="authored-ii-c",
            original="show performance",
            rewritten="Show performance.",
            stratum="adversarial",
            cell=4,
            intent="comparison across categories",
            shape="wide_sparse",
            cell_family="ii",
            degree=4,
            frame=_frame(
                "Bar Chart",
                {"x": "team", "y": "revenue"},
                {},
            ),
        ),
        rec(
            "r49",
            source="authored",
            source_id="authored-compound",
            original="how did revenue move and what happened to churn",
            rewritten="How did revenue move, and what happened to churn?",
            stratum="adversarial",
            cell=4,
            intent="trend over time",
            shape="nested",
            cell_family="iii",
            frame=_frame("Line Chart", {"x": "month", "y": "revenue"}, {}),
        ),
        rec(
            "r50",
            source="authored",
            source_id="authored-hostile",
            original="chart the amount by the date column",
            rewritten="Chart the amount by the date column.",
            stratum="adversarial",
            cell=4,
            intent="comparison across categories",
            shape="wide",
            cell_family="iv",
            frame=_frame("Bar Chart", {"x": "date", "y": "amount"}, {}),
        ),
    ]

    reserves = [
        rec(
            "s01",
            source="nvbench1",
            source_id="1383@3",
            original="I want to know the proportion of the average population for each status.",
            rewritten="I want to know the proportion of the average population for each status.",
            stratum="common_path",
            cell=0,
            intent="part-to-whole",
            shape="long",
            frame=_frame(
                "Pie Chart",
                {"color": "Status", "size": "avg_pop"},
                _group_avg("Status", "Population", "avg_pop"),
            ),
            replaces={"cell": 0, "stratum": "common_path"},
            draw_order=1,
        ),
        rec(
            "s02",
            source="authored",
            source_id="authored-reserve-unpivot",
            original="show each region's quarterly revenue as a series",
            rewritten="Show each region's quarterly revenue as a series.",
            stratum="common_path",
            cell=2,
            intent="trend over time",
            shape="wide",
            frame=_frame(
                "Line Chart",
                {"x": "quarter", "y": "revenue"},
                {"raw_sql": union_sql},
            ),
            replaces={"cell": 2, "stratum": "common_path"},
            draw_order=2,
        ),
        rec(
            "s03",
            source="authored",
            source_id="authored-reserve-overlap",
            original="which customers sit in spring and fall but not the app",
            rewritten="Which customers sit in spring and fall but not the app?",
            stratum="adversarial",
            cell=1,
            intent="set overlap / intersection structure",
            shape="long",
            frame=None,
            expressible=["Venn", "Euler", "UpSet"],
            replaces={"cell": 1, "stratum": "adversarial"},
            draw_order=3,
        ),
        rec(
            "s04",
            source="authored",
            source_id="authored-reserve-empty",
            original="show revenue after keeping only the missing region",
            rewritten="Show revenue after keeping only the missing region.",
            stratum="adversarial",
            cell=3,
            intent="comparison across categories",
            shape="long",
            cell_family="excel_empty_after_filter",
            frame=_frame(
                "Bar Chart",
                {"x": "region", "y": "revenue"},
                {
                    "filter": {
                        "kind": "eq",
                        "args": [
                            {"kind": "col", "name": "region"},
                            {"kind": "lit", "value": "missing"},
                        ],
                    }
                },
            ),
            replaces={"cell": 3, "stratum": "adversarial"},
            draw_order=4,
        ),
        rec(
            "s05",
            source="authored",
            source_id="authored-reserve-ii",
            original="what does the scorecard look like",
            rewritten="What does the scorecard look like?",
            stratum="adversarial",
            cell=4,
            intent="comparison across categories",
            shape="wide_sparse",
            cell_family="ii",
            degree=4,
            frame=_frame("Bar Chart", {"x": "team", "y": "nps"}, {}),
            replaces={"cell": 4, "stratum": "adversarial"},
            draw_order=5,
        ),
    ]

    doc = {
        "flint_version": "0.5.1",
        "fixture_commit": "34ef451",
        "requests": requests,
        "reserves": reserves,
    }
    out = REPO / "corpus" / "pre-registration.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")

    notice = REPO / "corpus" / "NOTICE"
    notice.write_text(
        """This directory carries mixed licences. It is a NOTICE, not a relicensing.

nvBench 1.0 query text (source nvbench1)
  Copyright the nvBench authors (TsinghuaDatabaseGroup/nvBench).
  Licence: MIT, asserted in that repository's README.

Tables extracted from nvBench 1.0 databases
  Those tables descend from Spider (Yale / Yale-LILY).
  Licence: CC BY-SA 4.0 (https://yale-lily.github.io/spider).
  Share-alike and attribution apply to those files, not to the rest of
  this Apache-2.0 repository.

Authored requests (source authored)
  Copyright the chartagent authors.
  Licence: Apache-2.0, as the rest of this repository.

Quda is not used. NLV Corpus is a register reference only and is not
vendored. nvBench 2.0 is not vendored: HKUSTDial/nvBench-2.0 does not
assert a commercially usable licence in the artefact itself, so the
three cell-4(ii) sentences were authored to the frozen degrees.
""",
        encoding="utf-8",
    )

    note = REPO / "corpus" / "pre-registration.md"
    note.write_text(
        """# corpus-prereg-v1 authoring note

**Date:** 2026-08-30.

This note is the dated companion to `corpus/pre-registration.json`.
The tag `corpus-prereg-v1` is cut on the commit that adds these bytes.
No planner prompt is committed before that tag.

## What was authored

Fifty requests and five reserves. Each request pins one dataset by
sha256, carries a shape label, and has a façade-valid reference frame —
or a null frame with `expressible_if` for the four cell-1 slots.
The freeze schema has no reason field (ADR-0014 appendix). The stated
reason is the cell-1 intent plus `expressible_if`: r31/r32 nothing in
the 48 encodes membership overlap (Venn/Euler/UpSet); r33 no simplex
geometry (Ternary); r34 Map and Choropleth place values, flow lines
are a layer (Flow Map).

The cell × stratum matrix is 22/0/4/2/2 and 0/4/6/4/6. Shape marginals
are common-path 12/12/3/3 and adversarial 4/6/4/6. The nine carryable
intents are floored at one each on the common-path 30. Designed
common-path counts: trend 7, comparison 9, distribution 1,
correlation 2, part-to-whole 6, ranking 2, flow 1, geographic 1,
single-value 1.

Cell-2 common-path slots are spreadsheet-wide one-row extracts of the
nvBench aggregate, then UNPIVOT (r23 ranks, r24 male-guest years,
r25 hall-of-fame years, r26 assistant-professor sexes). The menu
cannot melt those columns. Adversarial cell 2 keeps UNION ALL,
strptime, window, PIVOT … IN, and conditional aggregation. The
reserve for common-path cell 2 is UNION ALL.

r09 keeps nvBench's wording ("how old is each student and how many
students are each age?"). The gold vis is one Age-by-count chart, not
a cell-4(iii) compound ask. r22 is the single-value floor: Bullet of
room_count against bedroom_count, both columns already on Apartments.

## Sources

nvBench 1.0's unnamed-mark subset is the ID and dataset spine for the
common-path 30. Fluency rewrites do not add or remove a measure, a
grain, a filter, or a chart-type name. Both versions are stored.
nvBench gold vis, `chart`, and any `steps` reasoning are not the
reference frame.

Cell-4(ii) is three authored sentences (degrees 2, 2, and 4). nvBench
2.0 is not used. NLV Corpus is a register reference only. Quda is not
used.

## Reserves

Five reserves, keyed on `(cell, stratum)`, draw order 1–5:
common-path cell 0, common-path cell 2, adversarial cell 1,
adversarial cell 3, adversarial cell 4. Substitution is a lookup.
Dropping is the fallback when reserves are exhausted, and only for
unscoreability discovered before a run.

## Pin

Authoring pin: Flint `0.5.1` / fixture `34ef451`.
""",
        encoding="utf-8",
    )
    print(f"wrote {notice} and {note}")


if __name__ == "__main__":
    build()
