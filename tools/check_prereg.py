"""Validate a corpus pre-registration file (ADR-0014).

Exit 0 = the file is a legal candidate.
Exit 1 = a named check failed.
Exit 2 = usage error.

    python tools/check_prereg.py <pre-registration.json>

Adds nothing to chartagent.__all__. The production fifty-request file is
not this tool's to author.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from chartagent.errors import ChartAgentError, RawSqlRejectedError
from chartagent.frame.input import InputFrame
from chartagent.transform.engine import open_connection
from chartagent.transform.raw_sql import validate_raw_sql

COMMON_MATRIX = (22, 0, 4, 2, 2)
ADVERSARIAL_MATRIX = (0, 4, 6, 4, 6)
COMMON_SHAPES = {"long": 12, "wide": 12, "nested": 3, "wide_sparse": 3}
ADVERSARIAL_SHAPES = {"long": 4, "wide": 6, "nested": 4, "wide_sparse": 6}
CARRYABLE_INTENTS = (
    "trend over time",
    "comparison across categories",
    "distribution of one measure",
    "correlation between measures",
    "part-to-whole",
    "ranking / top-N",
    "flow or transition between states",
    "geographic distribution",
    "single value against a target",
)
CELL1_INTENTS = (
    "set overlap / intersection structure",
    "compositional simplex",
    "origin–destination flow on a geography",
)
CELL1_SLOT_COUNTS = {
    "set overlap / intersection structure": 2,
    "compositional simplex": 1,
    "origin–destination flow on a geography": 1,
}
CELL3_FAMILIES = frozenset(
    {
        "discrete_overflow",
        "excel_empty_after_filter",
        "excel_pyramid_two_groups",
        "excel_candlestick_order",
        "echarts_boxplot",
    }
)
CELL4_FAMILIES = frozenset({"i", "ii", "iii", "iv"})
FORBIDDEN_CELL1_TYPES = (
    "word cloud",
    "marimekko",
    "waffle",
    "venn",
    "euler",
    "upset",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

INTENT_MAP: dict[str, tuple[str, ...]] = {
    "trend over time": (
        "Line Chart",
        "Area Chart",
        "Range Area Chart",
        "Streamgraph",
        "Bump Chart",
        "Calendar Heatmap",
        "Sparkline",
        "Candlestick Chart",
    ),
    "comparison across categories": (
        "Bar Chart",
        "Grouped Bar Chart",
        "Stacked Bar Chart",
        "Combo Chart",
        "Lollipop Chart",
        "Slope Chart",
        "Radar Chart",
        "Waterfall Chart",
        "Gantt Chart",
        "Bar Table",
    ),
    "distribution of one measure": (
        "Histogram",
        "Boxplot",
        "Violin Plot",
        "Density Plot",
        "Strip Plot",
        "ECDF Plot",
    ),
    "correlation between measures": (
        "Scatter Plot",
        "Bubble Chart",
        "Regression",
        "Connected Scatter Plot",
        "Density Contour",
        "Parallel Coordinates",
        "Heatmap",
    ),
    "part-to-whole": (
        "Pie Chart",
        "Donut Chart",
        "Doughnut Chart",
        "Treemap",
        "Sunburst Chart",
        "Rose Chart",
    ),
    "ranking / top-N": (
        "Ranged Dot Plot",
        "Pyramid Chart",
    ),
    "flow or transition between states": (
        "Sankey Diagram",
        "Funnel Chart",
        "Network Graph",
        "Tree",
    ),
    "geographic distribution": (
        "Choropleth",
        "Map",
    ),
    "single value against a target": (
        "KPI Card",
        "Gauge Chart",
        "Bullet Chart",
    ),
}

Stratum = Literal["common_path", "adversarial"]
Shape = Literal["long", "wide", "nested", "wide_sparse"]
Source = Literal["nvbench1", "nvbench2", "authored"]
Cell = Literal[0, 1, 2, 3, 4]
Outcome = Literal["hit", "miss"]


class Replaces(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cell: Cell
    stratum: Stratum


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    source: Source
    source_id: str
    query_original: str
    query_rewritten: str
    stratum: Stratum
    cell: Cell
    cell_family: str | None = None
    intent: str
    shape: Shape
    dataset_path: str
    dataset_sha256: str
    reference_frame: dict[str, Any] | None
    expressible_if: list[str] | None = None
    ambiguity_degree: int | None = None
    expected_outcome: Outcome
    expected_bucket: int | None = None

    @field_validator(
        "id", "source_id", "query_original", "query_rewritten", "dataset_path"
    )
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be non-empty")
        return value

    @field_validator("dataset_sha256")
    @classmethod
    def _sha256(cls, value: str) -> str:
        if SHA256_RE.fullmatch(value) is None:
            raise ValueError("must be a lowercase sha256 hex digest")
        return value


class Reserve(Request):
    replaces: Replaces
    draw_order: int = Field(ge=1)


class PreRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flint_version: str
    fixture_commit: str
    requests: list[Request]
    reserves: list[Reserve]

    @field_validator("flint_version", "fixture_commit")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be non-empty")
        return value


Request.model_rebuild()
Reserve.model_rebuild()
PreRegistration.model_rebuild()


def _union_chart_types() -> frozenset[str]:
    from chartagent.frame._generated import CHART_TYPES

    return frozenset(CHART_TYPES)


def validate(path: Path) -> list[str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"PARSE              {exc}"]
    if not isinstance(raw, dict):
        return ["SCHEMA             top level must be an object"]
    try:
        doc = PreRegistration.model_validate(raw)
    except ValidationError as exc:
        return [
            f"SCHEMA             {err['loc']}: {err['msg']}" for err in exc.errors()
        ]
    return _check(doc)


def _check(doc: PreRegistration) -> list[str]:
    issues: list[str] = []
    issues.extend(_check_intent_map())
    issues.extend(_check_matrix(doc.requests))
    issues.extend(_check_nulls(doc.requests))
    issues.extend(_check_shapes(doc.requests))
    issues.extend(_check_intent_floor(doc.requests))
    issues.extend(_check_cell1(doc.requests))
    issues.extend(_check_ambiguity(doc.requests))
    issues.extend(_check_reserves(doc))
    connection = open_connection()
    try:
        for item in (*doc.requests, *doc.reserves):
            issues.extend(_check_request(item, connection))
    finally:
        connection.close()
    return issues


def _check_intent_map() -> list[str]:
    assigned: dict[str, str] = {}
    issues: list[str] = []
    for intent, types in INTENT_MAP.items():
        if intent not in CARRYABLE_INTENTS:
            issues.append(f"INTENT_MAP         unknown intent {intent!r}")
        for chart in types:
            if chart in assigned:
                issues.append(f"INTENT_MAP         {chart!r} assigned twice")
            assigned[chart] = intent
    union = _union_chart_types()
    extra = sorted(set(assigned) - union)
    missing = sorted(union - set(assigned))
    if extra:
        issues.append(f"INTENT_MAP         leftover: {', '.join(extra)}")
    if missing:
        issues.append(f"INTENT_MAP         unassigned: {', '.join(missing)}")
    return issues


def _matrix(requests: list[Request], stratum: Stratum) -> tuple[int, ...]:
    counts = [0, 0, 0, 0, 0]
    for item in requests:
        if item.stratum == stratum:
            counts[item.cell] += 1
    return tuple(counts)


def _check_matrix(requests: list[Request]) -> list[str]:
    issues: list[str] = []
    if len(requests) != 50:
        issues.append(f"MATRIX             n={len(requests)}, want 50")
    common = _matrix(requests, "common_path")
    adversarial = _matrix(requests, "adversarial")
    if common != COMMON_MATRIX:
        issues.append(
            f"MATRIX             common_path {list(common)}, want {list(COMMON_MATRIX)}"
        )
    if adversarial != ADVERSARIAL_MATRIX:
        issues.append(
            "MATRIX             adversarial "
            f"{list(adversarial)}, want {list(ADVERSARIAL_MATRIX)}"
        )
    return issues


def _check_nulls(requests: list[Request]) -> list[str]:
    nulls = [item for item in requests if item.reference_frame is None]
    issues: list[str] = []
    if len(nulls) != 4:
        issues.append(f"NULL_FRAMES        {len(nulls)} null frames, want 4")
    for item in nulls:
        if item.cell != 1:
            issues.append(
                f"NULL_FRAMES        {item.id}: null frame is cell {item.cell}"
            )
    for item in requests:
        if item.cell == 1 and item.reference_frame is not None:
            issues.append(f"NULL_FRAMES        {item.id}: cell 1 frame is not null")
        if item.cell == 1:
            names = item.expressible_if or []
            if not names:
                issues.append(
                    f"EXPRESSIBLE_IF     {item.id}: cell 1 needs a non-empty list"
                )
        elif item.expressible_if is not None:
            issues.append(
                f"EXPRESSIBLE_IF     {item.id}: only cell 1 carries expressible_if"
            )
    return issues


def _shape_counts(requests: list[Request], stratum: Stratum) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in requests:
        if item.stratum == stratum:
            counts[item.shape] += 1
    return dict(counts)


def _check_shapes(requests: list[Request]) -> list[str]:
    issues: list[str] = []
    for stratum, want in (
        ("common_path", COMMON_SHAPES),
        ("adversarial", ADVERSARIAL_SHAPES),
    ):
        got = _shape_counts(requests, stratum)
        if got != want:
            issues.append(f"SHAPE              {stratum} {got}, want {want}")
    return issues


def _check_intent_floor(requests: list[Request]) -> list[str]:
    # ADR-0014 D9 floors the nine carryable intents on the common-path 30.
    present = {
        item.intent
        for item in requests
        if item.stratum == "common_path" and item.intent in CARRYABLE_INTENTS
    }
    missing = [name for name in CARRYABLE_INTENTS if name not in present]
    if missing:
        return [f"INTENT_FLOOR       missing from common_path: {', '.join(missing)}"]
    return []


def _check_cell1(requests: list[Request]) -> list[str]:
    issues: list[str] = []
    cell1 = [item for item in requests if item.cell == 1]
    counts: Counter[str] = Counter(item.intent for item in cell1)
    if dict(counts) != CELL1_SLOT_COUNTS:
        issues.append(
            f"CELL1_SLOT         intent split {dict(counts)}, want {CELL1_SLOT_COUNTS}"
        )
    return issues


def _check_ambiguity(requests: list[Request]) -> list[str]:
    issues: list[str] = []
    common_ii = [
        item
        for item in requests
        if item.cell_family == "ii" and item.stratum == "common_path"
    ]
    adv_ii = [
        item
        for item in requests
        if item.cell_family == "ii" and item.stratum == "adversarial"
    ]
    if len(common_ii) != 2 or len(adv_ii) != 1:
        issues.append(
            "AMBIGUITY          family (ii) slots "
            f"common {len(common_ii)} adversarial {len(adv_ii)}, want 2 and 1"
        )
    return issues


def _occupied(requests: list[Request]) -> set[tuple[int, str]]:
    return {(item.cell, item.stratum) for item in requests}


def _check_reserves(doc: PreRegistration) -> list[str]:
    issues: list[str] = []
    if len(doc.reserves) != 5:
        issues.append(f"RESERVE            {len(doc.reserves)} reserves, want 5")
    orders = [item.draw_order for item in doc.reserves]
    if len(doc.reserves) == 5 and sorted(orders) != [1, 2, 3, 4, 5]:
        issues.append(f"RESERVE            draw_order {sorted(orders)}, want 1..5")
    occupied = _occupied(doc.requests)
    for item in doc.reserves:
        key = (item.replaces.cell, item.replaces.stratum)
        if key not in occupied:
            issues.append(f"RESERVE            {item.id}: {key} is empty in the matrix")
        if item.cell != item.replaces.cell or item.stratum != item.replaces.stratum:
            issues.append(
                f"RESERVE            {item.id}: record is cell {item.cell} "
                f"{item.stratum}, replaces {key}"
            )
    ids = [item.id for item in doc.requests]
    if len(ids) != len(set(ids)):
        issues.append("SCHEMA             request ids are not unique")
    reserve_ids = [item.id for item in doc.reserves]
    if len(reserve_ids) != len(set(reserve_ids)):
        issues.append("SCHEMA             reserve ids are not unique")
    overlap = set(ids) & set(reserve_ids)
    if overlap:
        issues.append(f"SCHEMA             ids shared with reserves: {sorted(overlap)}")
    return issues


def _check_request(item: Request, connection: duckdb.DuckDBPyConnection) -> list[str]:
    issues: list[str] = []
    issues.extend(_check_family(item))
    issues.extend(_check_intent(item))
    issues.extend(_check_expected(item))
    if item.cell == 1:
        issues.extend(_check_cell1_request(item))
    if item.reference_frame is not None:
        issues.extend(_check_frame(item))
        if item.cell == 2:
            issues.extend(_check_cell2_sql(item, connection))
    elif item.cell == 2:
        issues.append(f"CELL2_SQL          {item.id}: cell 2 has no frame to check")
    if item.cell_family == "ii":
        issues.extend(_check_degree(item))
    return issues


def _check_family(item: Request) -> list[str]:
    if item.cell in {3, 4}:
        if item.cell_family is None:
            return [f"SCHEMA             {item.id}: cell {item.cell} needs cell_family"]
        allowed = CELL3_FAMILIES if item.cell == 3 else CELL4_FAMILIES
        if item.cell_family not in allowed:
            return [
                f"SCHEMA             {item.id}: cell_family "
                f"{item.cell_family!r} is not valid for cell {item.cell}"
            ]
        return []
    if item.cell_family is not None:
        return [
            f"SCHEMA             {item.id}: cell {item.cell} must not set cell_family"
        ]
    return []


def _check_intent(item: Request) -> list[str]:
    if item.cell == 1:
        if item.intent not in CELL1_INTENTS:
            return [f"CELL1_INTENT       {item.id}: {item.intent!r}"]
        return []
    if item.intent not in CARRYABLE_INTENTS:
        return [
            f"SCHEMA             {item.id}: {item.intent!r} is not a carryable intent"
        ]
    return []


def _check_expected(item: Request) -> list[str]:
    if item.reference_frame is None:
        want_outcome, want_bucket = "miss", 1
    else:
        want_outcome, want_bucket = "hit", None
    issues: list[str] = []
    if item.expected_outcome != want_outcome:
        issues.append(
            f"EXPECTED           {item.id}: recorded {item.expected_outcome}, "
            f"frame derives {want_outcome}"
        )
    if item.expected_bucket != want_bucket:
        issues.append(
            f"EXPECTED           {item.id}: recorded bucket {item.expected_bucket}, "
            f"frame derives {want_bucket}"
        )
    return issues


def _check_cell1_request(item: Request) -> list[str]:
    blob = f"{item.query_original}\n{item.query_rewritten}\n{item.intent}".lower()
    hit = [name for name in FORBIDDEN_CELL1_TYPES if name in blob]
    for name in sorted(_union_chart_types()):
        if re.search(rf"\b{re.escape(name.lower())}\b", blob):
            hit.append(name)
    if hit:
        return [f"CELL1_TYPE         {item.id}: names {', '.join(hit)}"]
    return []


def _check_degree(item: Request) -> list[str]:
    degree = item.ambiguity_degree
    if degree is None:
        return [f"AMBIGUITY          {item.id}: family (ii) needs ambiguity_degree"]
    if item.stratum == "common_path" and degree != 2:
        return [
            f"AMBIGUITY          {item.id}: common-path (ii) degree {degree}, want 2"
        ]
    if item.stratum == "adversarial" and degree < 4:
        return [
            f"AMBIGUITY          {item.id}: adversarial (ii) degree {degree}, want >= 4"
        ]
    return []


def _check_frame(item: Request) -> list[str]:
    frame = item.reference_frame
    assert frame is not None
    issues: list[str] = []
    spec = frame.get("chart_spec")
    if not isinstance(spec, Mapping) or spec.get("baseSize") is None:
        issues.append(f"BASE_SIZE          {item.id}: chart_spec.baseSize is required")
    xc = frame.get("x_chartagent")
    if not isinstance(xc, Mapping) or "transform" not in xc:
        issues.append(
            f"TRANSFORM          {item.id}: x_chartagent.transform is required"
        )
    try:
        InputFrame.model_validate(frame)
    except ChartAgentError as exc:
        issues.append(f"FACADE             {item.id}: {exc}")
    return issues


def _check_cell2_sql(item: Request, connection: duckdb.DuckDBPyConnection) -> list[str]:
    frame = item.reference_frame
    assert frame is not None
    xc = frame.get("x_chartagent")
    transform = xc.get("transform") if isinstance(xc, Mapping) else None
    if not isinstance(transform, Mapping) or "raw_sql" not in transform:
        return [f"CELL2_SQL          {item.id}: cell 2 needs transform.raw_sql"]
    others = tuple(key for key in transform if key != "raw_sql")
    if others:
        return [f"CELL2_SQL          {item.id}: raw_sql cannot mix with {others}"]
    sql = transform["raw_sql"]
    if not isinstance(sql, str):
        return [f"CELL2_SQL          {item.id}: raw_sql must be a string"]
    try:
        validate_raw_sql(connection, sql)
    except RawSqlRejectedError as exc:
        return [f"CELL2_SQL          {item.id}: {exc.reason}"]
    return []


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(
            "usage: python tools/check_prereg.py <pre-registration.json>",
            file=sys.stderr,
        )
        return 2
    path = Path(args[0])
    issues = validate(path)
    print(path)
    for line in issues:
        print("  " + line)
    if issues:
        print(f"\nFAIL — {len(issues)} check(s) failed.")
        return 1
    print("\nOK — pre-registration is legal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
