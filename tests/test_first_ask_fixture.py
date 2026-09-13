"""Structural shape of the first-ask fixture and instruction set (issue #145)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import duckdb

from chartagent.profile import profile_source
from chartagent.profile.models import NumberColumn, StringColumn, TemporalColumn
from chartagent.transform.menu import TRANSFORM_SLOTS

_FIXTURES = Path(__file__).with_name("data")
_FIXTURE = _FIXTURES / "orders_dated.csv"
_INSTRUCTIONS = _FIXTURES / "first_ask" / "instructions.json"

_KNOWN_FIXTURES = frozenset(
    {"sales.csv", "sales_by_region.csv", "sales.parquet", "orders_dated.csv"}
)
_KNOWN_SLOTS = frozenset({*TRANSFORM_SLOTS, "raw_sql"})

# Exact DSL tokens: unambiguous jargon, safe to ban as substrings.
_BANNED_PHRASES = (
    "group by",
    "group_by",
    "having",
    "aggregate",
    "derive",
    "raw_sql",
    "count_distinct",
    "window function",
)
# Single-word slot names that are also ordinary English: banned as whole
# words only, so a phrase like "the last five" doesn't trip a false match.
_BANNED_WORDS = (
    "sort",
    "filter",
    "bin",
    "limit",
    "case",
    "transform",
    "fragment",
    "menu",
    "expr",
    "slot",
)


def _entries() -> list[dict[str, Any]]:
    return cast(
        "list[dict[str, Any]]", json.loads(_INSTRUCTIONS.read_text(encoding="utf-8"))
    )


def _columns() -> dict[str, object]:
    profile = profile_source(_FIXTURE)
    return {column.name: column for column in profile.columns}


def test_fixture_has_a_date_and_a_timestamp_column() -> None:
    columns = _columns()
    assert isinstance(columns["order_date"], TemporalColumn)
    assert isinstance(columns["order_ts"], TemporalColumn)
    assert columns["order_date"].bucket == "date"
    assert columns["order_ts"].bucket == "timestamp"


def test_fixture_has_a_nullable_numeric_column() -> None:
    column = _columns()["amount"]
    assert isinstance(column, NumberColumn)
    assert column.null_rate > 0


def test_fixture_has_a_string_category_column() -> None:
    assert isinstance(_columns()["channel"], StringColumn)


def test_fixture_bins_by_month_and_by_day_into_more_than_one_bucket() -> None:
    connection = duckdb.connect()
    quoted = str(_FIXTURE).replace("'", "''")
    row = connection.sql(
        f"SELECT COUNT(DISTINCT date_trunc('month', order_date)), "
        f"COUNT(DISTINCT date_trunc('day', order_date)) "
        f"FROM read_csv_auto('{quoted}')"
    ).fetchone()
    assert row is not None
    months, days = row
    assert months > 1
    assert days > 1


def test_fixture_is_small_enough_to_commit() -> None:
    assert _FIXTURE.stat().st_size < 10_000


def test_instruction_count_is_between_20_and_30() -> None:
    assert 20 <= len(_entries()) <= 30


def test_instruction_ids_are_unique() -> None:
    ids = [entry["id"] for entry in _entries()]
    assert len(ids) == len(set(ids))


def test_every_entry_has_exactly_the_documented_fields() -> None:
    for entry in _entries():
        assert set(entry) == {"id", "fixture", "instruction", "slots"}


def test_every_fixture_reference_is_a_committed_fixture() -> None:
    for entry in _entries():
        assert entry["fixture"] in _KNOWN_FIXTURES, entry["id"]


def test_every_slot_tag_is_a_real_menu_slot_or_raw_sql() -> None:
    for entry in _entries():
        slots = cast("list[str]", entry["slots"])
        assert slots, entry["id"]
        assert set(slots) <= _KNOWN_SLOTS, entry["id"]


def test_every_menu_slot_and_raw_sql_is_covered_at_least_once() -> None:
    covered: set[str] = set()
    for entry in _entries():
        covered.update(cast("list[str]", entry["slots"]))
    assert covered == _KNOWN_SLOTS


def test_having_is_covered_over_a_derived_column() -> None:
    # having filters the group stage's output; the ticket wants at least
    # one entry where that output includes a column made by `derive`, not
    # only by `aggregate` -- otherwise "having over a derived column"
    # collapses into "having over an aggregate".
    assert any(
        {"derive", "having"} <= set(cast("list[str]", entry["slots"]))
        for entry in _entries()
    )


def test_no_instruction_names_the_menu_vocabulary() -> None:
    for entry in _entries():
        text = str(entry["instruction"]).lower()
        for phrase in _BANNED_PHRASES:
            assert phrase not in text, (entry["id"], phrase)
        for word in _BANNED_WORDS:
            assert re.search(rf"\b{word}\b", text) is None, (entry["id"], word)


def test_no_entry_carries_an_expected_answer() -> None:
    forbidden = {
        "chart",
        "chart_type",
        "charttype",
        "expected",
        "expected_chart",
        "transform",
    }
    for entry in _entries():
        assert forbidden.isdisjoint(entry), entry["id"]
