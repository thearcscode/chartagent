from __future__ import annotations

import os
import time
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import chartagent
from chartagent.errors import DataSourceError
from chartagent.profile import profile_source, untrusted_paths
from chartagent.profile.models import (
    ALL_MODELS,
    SATURATION_CAP,
    BooleanColumn,
    NumberColumn,
    OtherColumn,
    Profile,
    StringColumn,
    StringStats,
    TemporalColumn,
    TopValue,
)

_FIXTURES = Path(__file__).with_name("data")


def test_profile_source_is_not_on_the_public_surface() -> None:
    assert "profile_source" not in chartagent.__all__
    assert "Profile" not in chartagent.__all__
    assert "profile" not in chartagent.__all__
    assert not callable(getattr(chartagent, "profile", None))


def test_small_source_artifact_has_no_identity_or_truncation() -> None:
    profile = profile_source(_FIXTURES / "sales.csv")
    dumped = profile.model_dump()
    assert set(dumped) == {"row_count", "columns", "sample_rows"}
    assert "truncation" not in dumped
    assert "path" not in dumped
    assert "source" not in dumped
    assert "generated_at" not in dumped
    assert "elapsed" not in dumped
    assert "profile_version" not in dumped
    assert profile.row_count == 2
    assert len(profile.columns) == 2
    assert profile.sample_rows


def test_parquet_and_arrow_and_rows_all_profile() -> None:
    parquet = profile_source(_FIXTURES / "sales.parquet")
    arrow = profile_source(pa.table({"quarter": ["Q1", "Q2"], "revenue": [100, 200]}))
    rows = profile_source(
        [{"quarter": "Q1", "revenue": 100}, {"quarter": "Q2", "revenue": 200}]
    )
    assert parquet.row_count == arrow.row_count == rows.row_count == 2


def test_duplicate_parquet_ids_are_id_and_id_1(tmp_path: Path) -> None:
    path = tmp_path / "dup.parquet"
    table = pa.table(
        [pa.array([1, 2]), pa.array(["a", "b"])],
        schema=pa.schema([pa.field("id", pa.int64()), pa.field("id", pa.string())]),
    )
    pq.write_table(table, path)
    profile = profile_source(path)
    assert [column.name for column in profile.columns] == ["id", "id_1"]
    assert [column.bucket for column in profile.columns] == ["number", "string"]


def test_columns_are_five_variants_on_the_seven_buckets() -> None:
    profile = profile_source(
        pa.table(
            {
                "n": pa.array([1], type=pa.int32()),
                "s": pa.array(["Q1"], type=pa.string()),
                "b": pa.array([True], type=pa.bool_()),
                "d": pa.array([date(2020, 1, 1)]),
                "ts": pa.array(
                    [datetime(2020, 1, 1)],
                    type=pa.timestamp("us"),
                ),
                "tz": pa.array(
                    [datetime(2020, 1, 1, tzinfo=UTC)],
                    type=pa.timestamp("us", tz="UTC"),
                ),
                "blob": pa.array([b"x"], type=pa.binary()),
                "ids": pa.array([[1, 2]], type=pa.list_(pa.int64())),
            }
        )
    )
    by_name = {column.name: column for column in profile.columns}
    assert isinstance(by_name["n"], NumberColumn)
    assert isinstance(by_name["s"], StringColumn)
    assert isinstance(by_name["b"], BooleanColumn)
    assert isinstance(by_name["d"], TemporalColumn)
    assert by_name["d"].bucket == "date"
    assert isinstance(by_name["ts"], TemporalColumn)
    assert by_name["ts"].bucket == "timestamp"
    assert isinstance(by_name["tz"], TemporalColumn)
    assert by_name["tz"].bucket == "timestamptz"
    assert isinstance(by_name["blob"], OtherColumn)
    assert isinstance(by_name["ids"], OtherColumn)
    other = by_name["ids"]
    assert set(other.model_dump()) == {"name", "bucket", "reported_type"}
    assert other.reported_type.endswith("]")


def test_unreadable_source_raises() -> None:
    with pytest.raises(DataSourceError):
        profile_source(_FIXTURES / "no-such-source.csv")


def test_distinct_is_exact_at_1000_and_saturated_at_1001() -> None:
    under = profile_source(pa.table({"n": list(range(1000))}))
    under_col = under.columns[0]
    assert isinstance(under_col, NumberColumn)
    assert under_col.distinct == 1000
    assert under_col.saturated is False
    at_cap = profile_source(pa.table({"n": list(range(1001))}))
    at_cap_col = at_cap.columns[0]
    assert isinstance(at_cap_col, NumberColumn)
    assert at_cap_col.distinct == 1001
    assert at_cap_col.saturated is True
    above = profile_source(pa.table({"n": list(range(2000))}))
    above_col = above.columns[0]
    assert isinstance(above_col, NumberColumn)
    assert above_col.distinct == 1001
    assert above_col.saturated is True


def test_min_max_are_exact_and_percentiles_follow_the_column_kind() -> None:
    profile = profile_source(
        pa.table(
            {
                "n": [2, 5, 9],
                "d": [date(2020, 1, 1), date(2020, 6, 15), date(2020, 12, 31)],
                "flag": [True, False, True],
                "payload": pa.array([b"a", b"b", b"c"], type=pa.binary()),
            }
        )
    )
    by_name = {column.name: column for column in profile.columns}
    number = by_name["n"]
    assert isinstance(number, NumberColumn)
    assert number.stats is not None
    assert number.stats.min == 2.0
    assert number.stats.max == 9.0
    assert number.stats.min <= number.stats.p01 <= number.stats.p50
    assert number.stats.p50 <= number.stats.p99 <= number.stats.max
    temporal = by_name["d"]
    assert isinstance(temporal, TemporalColumn)
    assert temporal.stats is not None
    assert temporal.stats.min == "2020-01-01"
    assert temporal.stats.max == "2020-12-31"
    flag = by_name["flag"]
    assert isinstance(flag, BooleanColumn)
    assert "stats" not in flag.model_dump()
    payload = by_name["payload"]
    assert isinstance(payload, OtherColumn)
    assert "stats" not in payload.model_dump()


def test_constant_column_has_distinct_one_and_min_equals_max() -> None:
    profile = profile_source(pa.table({"n": [7, 7, 7, 7]}))
    column = profile.columns[0]
    assert isinstance(column, NumberColumn)
    assert column.distinct == 1
    assert column.stats is not None
    assert column.stats.min == column.stats.max == 7.0
    assert column.stats.p01 == column.stats.p99 == 7.0


@pytest.mark.parametrize("tz", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_timestamptz_extrema_use_trailing_z_regardless_of_host_tz(tz: str) -> None:
    original = os.environ.get("TZ")
    os.environ["TZ"] = tz
    if hasattr(time, "tzset"):
        time.tzset()
    try:
        instant = datetime(2020, 1, 15, 6, 30, tzinfo=UTC)
        profile = profile_source(
            pa.table(
                {
                    "ts": pa.array([instant], type=pa.timestamp("us", tz="UTC")),
                    "n": [1],
                }
            )
        )
        column = next(col for col in profile.columns if col.name == "ts")
        assert isinstance(column, TemporalColumn)
        assert column.stats is not None
        assert column.stats.min.endswith("Z")
        assert column.stats.min.startswith("2020-01-15T06:30:00")
        assert column.stats.max == column.stats.min
        sample = profile.sample_rows[0]["ts"]
        assert isinstance(sample, str)
        assert sample.endswith("Z")
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        if hasattr(time, "tzset"):
            time.tzset()


def test_string_top_excludes_null_and_coverage_matches_a_hand_fraction() -> None:
    rows: list[dict[str, object]] = []
    for letter in "abcdefghij":
        rows.extend({"region": letter} for _ in range(8))
    for letter in "klmnopqrst":
        rows.extend({"region": letter} for _ in range(2))
    rows.extend({"region": None} for _ in range(5))
    profile = profile_source(rows)
    column = profile.columns[0]
    assert isinstance(column, StringColumn)
    assert column.top is not None
    assert all(item.value is not None for item in column.top)
    assert [item.value for item in column.top] == list("abcdefghij")
    assert all(item.count == 8 for item in column.top)
    assert column.stats is not None
    assert column.stats.top_k_coverage == 0.8


def test_boolean_top_is_complete_including_null() -> None:
    profile = profile_source(pa.table({"flag": [True, True, False, None]}))
    column = profile.columns[0]
    assert isinstance(column, BooleanColumn)
    assert column.top is not None
    by_value = {item.value: item.count for item in column.top}
    assert by_value[True] == 2
    assert by_value[False] == 1
    assert by_value[None] == 1
    assert len(column.top) == 3


def test_iso8601_parse_rate_is_varchar_only() -> None:
    varchar = profile_source(
        pa.table(
            {
                "dates": ["2020-01-15"] * 12,
                "labels": ["north"] * 12,
                "slashes": ["03/04/2020"] * 12,
                "ids": pa.array(
                    [uuid.UUID("550e8400-e29b-41d4-a716-446655440000")] * 12,
                    type=pa.uuid(),
                ),
            }
        )
    )
    by_name = {column.name: column for column in varchar.columns}
    dates = by_name["dates"]
    assert isinstance(dates, StringColumn)
    assert dates.stats is not None
    assert dates.stats.iso8601_parse_rate == 1.0
    labels = by_name["labels"]
    assert isinstance(labels, StringColumn)
    assert labels.stats is not None
    assert labels.stats.iso8601_parse_rate == 0.0
    slashes = by_name["slashes"]
    assert isinstance(slashes, StringColumn)
    assert slashes.stats is not None
    assert slashes.stats.iso8601_parse_rate == 0.0
    ids = by_name["ids"]
    assert isinstance(ids, StringColumn)
    assert ids.stats is not None
    dumped = ids.stats.model_dump()
    assert "iso8601_parse_rate" in dumped
    assert dumped["iso8601_parse_rate"] is None
    number = profile_source(pa.table({"n": [1, 2, 3]}))
    assert "iso8601_parse_rate" not in number.columns[0].model_dump()


def test_saturation_cap_stays_at_1001() -> None:
    assert SATURATION_CAP == 1001


def test_sample_is_ten_rows_or_the_whole_table() -> None:
    small = profile_source(pa.table({"n": list(range(5))}))
    assert len(small.sample_rows) == 5
    large = profile_source(pa.table({"n": list(range(50))}))
    assert len(large.sample_rows) == 10


def test_sample_mean_position_is_uniform_not_the_file_head() -> None:
    table = pa.table({"id": list(range(2000))})
    means: list[float] = []
    for _ in range(40):
        profile = profile_source(table)
        positions = [int(row["id"]) for row in profile.sample_rows]
        means.append(sum(positions) / len(positions) / 1999)
    mean_position = sum(means) / len(means)
    assert 0.40 < mean_position < 0.60


def test_zero_rows_all_other_and_constant_all_succeed() -> None:
    zero = profile_source(
        pa.table(
            {
                "n": pa.array([], type=pa.int32()),
                "s": pa.array([], type=pa.string()),
            }
        )
    )
    assert zero.row_count == 0
    assert zero.sample_rows == []
    for column in zero.columns:
        if isinstance(column, NumberColumn):
            assert column.stats is None
        elif isinstance(column, StringColumn):
            assert column.stats is None
            assert column.top is None
        elif isinstance(column, BooleanColumn):
            assert column.top is None
    blobs = profile_source(
        pa.table({"payload": pa.array([b"a", b"b"], type=pa.binary())})
    )
    assert blobs.row_count == 2
    assert isinstance(blobs.columns[0], OtherColumn)
    assert blobs.sample_rows == []


def test_every_model_field_is_classified() -> None:
    for model in ALL_MODELS:
        declared = set(model.model_fields)
        classified = set(model.TRUSTED) | set(model.UNTRUSTED)
        missing = declared - classified
        unknown = classified - declared
        assert not missing, f"{model.__name__}: unclassified {sorted(missing)}"
        assert not unknown, f"{model.__name__}: extra {sorted(unknown)}"
        overlap = set(model.TRUSTED) & set(model.UNTRUSTED)
        assert not overlap, f"{model.__name__}: both sets {sorted(overlap)}"


def test_named_taint_memberships() -> None:
    assert "top_k_coverage" in StringStats.TRUSTED
    assert "iso8601_parse_rate" in StringStats.TRUSTED
    assert "min" in StringStats.UNTRUSTED
    assert "max" in StringStats.UNTRUSTED
    assert "value" in TopValue.UNTRUSTED
    assert "sample_rows" in Profile.UNTRUSTED
    for model in (
        NumberColumn,
        TemporalColumn,
        StringColumn,
        BooleanColumn,
        OtherColumn,
    ):
        assert "name" in model.UNTRUSTED
        assert "reported_type" in model.UNTRUSTED
    paths = untrusted_paths()
    assert any("sample_rows" in path for path in paths)
    assert any(path.endswith(".name") for path in paths)
    assert any("top[].value" in path for path in paths)
