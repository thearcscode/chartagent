from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

import chartagent
from chartagent.frame.input import DEFAULT_BASE_SIZE, BaseSize

_REPO = Path(__file__).resolve().parents[1]
_CHECK = _REPO / "tools" / "check_prereg.py"
_LEGAL_PATH = Path(__file__).with_name("data") / "prereg" / "legal.json"
_EMPTY_PATH = Path(__file__).with_name("data") / "prereg" / "empty.json"
_PRODUCTION = _REPO / "corpus" / "pre-registration.json"

_CARRYABLE = (
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
_CELL1_INTENTS = (
    "set overlap / intersection structure",
    "set overlap / intersection structure",
    "compositional simplex",
    "origin–destination flow on a geography",
)
_CELL1_EXPRESSIBLE = {
    "set overlap / intersection structure": ["Venn", "Euler", "UpSet"],
    "compositional simplex": ["Ternary"],
    "origin–destination flow on a geography": ["Flow Map"],
}
_CELL1_QUERIES = (
    (
        "which customers are in both campaigns but not the app",
        "Which customers appear in both campaigns but not the app?",
    ),
    (
        "which of the twelve segments overlap on more than two products",
        "Which of the twelve segments overlap on more than two products?",
    ),
    (
        "how the three ingredients mix in every blend",
        "How do the three ingredients mix in every blend?",
    ),
    (
        "commute flows between the five boroughs",
        "What are the commute flows between the five boroughs?",
    ),
)
_ADV_CELL3_FAMILIES = (
    "excel_empty_after_filter",
    "excel_pyramid_two_groups",
    "excel_candlestick_order",
    "echarts_boxplot",
)
_ADV_CELL4_FAMILIES = ("i", "i", "i", "ii", "iii", "iv")
_NAMED_FORMS = ("word cloud", "Marimekko", "waffle")


def _dump_size(size: BaseSize) -> dict[str, int]:
    return {"width": int(size.width), "height": int(size.height)}


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _frame(
    *, raw_sql: str | None = None, base_size: dict[str, Any] | None = None
) -> dict[str, Any]:
    transform: dict[str, Any] = {"raw_sql": raw_sql} if raw_sql is not None else {}
    return {
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": {"x": "quarter", "y": "revenue"},
            "baseSize": (
                base_size if base_size is not None else _dump_size(DEFAULT_BASE_SIZE)
            ),
        },
        "x_chartagent": {"transform": transform},
    }


def _request(
    *,
    index: int,
    stratum: str,
    cell: int,
    shape: str,
    intent: str,
    source: str = "nvbench1",
    cell_family: str | None = None,
    ambiguity_degree: int | None = None,
    named_form: str | None = None,
    cell1_slot: int | None = None,
) -> dict[str, Any]:
    rid = f"r{index:02d}"
    if cell == 1:
        assert cell1_slot is not None
        original, rewritten = _CELL1_QUERIES[cell1_slot]
        frame = None
        expressible = list(_CELL1_EXPRESSIBLE[intent])
        outcome, bucket = "miss", 1
    else:
        original = f"sales by quarter for {rid}"
        rewritten = f"Show sales by quarter for {rid}."
        if named_form is not None:
            original = f"show {named_form} of category share for {rid}"
            rewritten = f"Show a {named_form} of category share for {rid}."
        raw_sql = "SELECT quarter, revenue FROM source" if cell == 2 else None
        overflow = (
            _dump_size(_tool().OVERFLOW_BASE_SIZE)
            if cell_family == "discrete_overflow"
            else None
        )
        frame = _frame(raw_sql=raw_sql, base_size=overflow)
        expressible = None
        outcome, bucket = "hit", None
    row: dict[str, Any] = {
        "id": rid,
        "source": source,
        "source_id": f"nv-{rid}",
        "query_original": original,
        "query_rewritten": rewritten,
        "stratum": stratum,
        "cell": cell,
        "intent": intent,
        "shape": shape,
        "dataset_path": f"corpus/data/{rid}.parquet",
        "dataset_sha256": _sha(rid),
        "reference_frame": frame,
        "expected_outcome": outcome,
    }
    if cell_family is not None:
        row["cell_family"] = cell_family
    if ambiguity_degree is not None:
        row["ambiguity_degree"] = ambiguity_degree
    if expressible is not None:
        row["expressible_if"] = expressible
    if bucket is not None:
        row["expected_bucket"] = bucket
    return row


def _legal() -> dict[str, Any]:
    requests: list[dict[str, Any]] = []
    common_cells = [0] * 22 + [2] * 4 + [3] * 2 + [4] * 2
    common_shapes = ["long"] * 12 + ["wide"] * 12 + ["nested"] * 3 + ["wide_sparse"] * 3
    for i, (cell, shape) in enumerate(zip(common_cells, common_shapes, strict=True)):
        family = None
        degree = None
        if cell == 3:
            family = "discrete_overflow"
        elif cell == 4:
            family = "ii"
            degree = 2
        requests.append(
            _request(
                index=i + 1,
                stratum="common_path",
                cell=cell,
                shape=shape,
                intent=_CARRYABLE[i % len(_CARRYABLE)],
                cell_family=family,
                ambiguity_degree=degree,
            )
        )
    adv_cells = [1] * 4 + [2] * 6 + [3] * 4 + [4] * 6
    adv_shapes = ["long"] * 4 + ["wide"] * 6 + ["nested"] * 4 + ["wide_sparse"] * 6
    cell1_n = 0
    cell3_n = 0
    cell4_n = 0
    for j, (cell, shape) in enumerate(zip(adv_cells, adv_shapes, strict=True)):
        family = None
        degree = None
        named = None
        cell1_slot = None
        source = "nvbench1"
        if cell == 1:
            intent = _CELL1_INTENTS[cell1_n]
            cell1_slot = cell1_n
            cell1_n += 1
            source = "authored"
        elif cell == 3:
            family = _ADV_CELL3_FAMILIES[cell3_n]
            cell3_n += 1
            intent = _CARRYABLE[j % len(_CARRYABLE)]
        elif cell == 4:
            family = _ADV_CELL4_FAMILIES[cell4_n]
            if family == "ii":
                degree = 4
                source = "authored"
            elif family == "i":
                named = _NAMED_FORMS[cell4_n]
            cell4_n += 1
            intent = _CARRYABLE[j % len(_CARRYABLE)]
        else:
            intent = _CARRYABLE[j % len(_CARRYABLE)]
        requests.append(
            _request(
                index=31 + j,
                stratum="adversarial",
                cell=cell,
                shape=shape,
                intent=intent,
                source=source,
                cell_family=family,
                ambiguity_degree=degree,
                named_form=named,
                cell1_slot=cell1_slot,
            )
        )

    reserve_specs = (
        (0, "common_path", None),
        (2, "common_path", None),
        (1, "adversarial", None),
        (3, "adversarial", "excel_empty_after_filter"),
        (4, "adversarial", "ii"),
    )
    reserves: list[dict[str, Any]] = []
    for order, (cell, stratum, family) in enumerate(reserve_specs, start=1):
        sid = f"s{order:02d}"
        if cell == 1:
            intent = _CELL1_INTENTS[0]
            original, rewritten = _CELL1_QUERIES[0]
            frame = None
            extra: dict[str, Any] = {
                "expressible_if": list(_CELL1_EXPRESSIBLE[intent]),
                "expected_outcome": "miss",
                "expected_bucket": 1,
            }
        else:
            intent = _CARRYABLE[0]
            original = f"sales by quarter for {sid}"
            rewritten = f"Show sales by quarter for {sid}."
            raw_sql = "SELECT quarter, revenue FROM source" if cell == 2 else None
            frame = _frame(raw_sql=raw_sql)
            extra = {"expected_outcome": "hit"}
        row: dict[str, Any] = {
            "id": sid,
            "source": "authored",
            "source_id": f"res-{sid}",
            "query_original": original,
            "query_rewritten": rewritten,
            "stratum": stratum,
            "cell": cell,
            "intent": intent,
            "shape": "long",
            "dataset_path": f"corpus/data/{sid}.parquet",
            "dataset_sha256": _sha(sid),
            "reference_frame": frame,
            "replaces": {"cell": cell, "stratum": stratum},
            "draw_order": order,
            **extra,
        }
        if family is not None:
            row["cell_family"] = family
        if family == "ii":
            row["ambiguity_degree"] = 4 if stratum == "adversarial" else 2
        reserves.append(row)

    return {
        "flint_version": "0.5.1",
        "fixture_commit": "34ef451",
        "requests": requests,
        "reserves": reserves,
    }


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_prereg", _CHECK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_file(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_CHECK), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )


def _run(doc: dict[str, Any], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "pre-registration.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return _run_file(path)


def test_harness_is_not_on_the_public_surface() -> None:
    assert "check_prereg" not in chartagent.__all__
    with pytest.raises(ModuleNotFoundError):
        __import__("chartagent.check_prereg")


def test_committed_legal_fixture_matches_builder() -> None:
    committed = json.loads(_LEGAL_PATH.read_text(encoding="utf-8"))
    assert committed == _legal()


def test_legal_fixture_exits_zero() -> None:
    result = _run_file(_LEGAL_PATH)
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_production_prereg_exits_zero() -> None:
    assert _PRODUCTION.is_file()
    result = _run_file(_PRODUCTION)
    assert result.returncode == 0
    assert "OK" in result.stdout
    doc = json.loads(_PRODUCTION.read_text(encoding="utf-8"))
    shape_by_digest: dict[str, str] = {}
    for item in (*doc["requests"], *doc["reserves"]):
        path = _REPO / item["dataset_path"]
        assert path.is_file(), item["dataset_path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == item["dataset_sha256"], item["id"]
        prior = shape_by_digest.get(digest)
        assert prior in (None, item["shape"]), item["id"]
        shape_by_digest[digest] = item["shape"]


def test_empty_fixture_is_rejected() -> None:
    result = _run_file(_EMPTY_PATH)
    assert result.returncode == 1
    assert "SCHEMA" in result.stdout


def test_wrong_matrix_is_rejected(tmp_path: Path) -> None:
    doc = _legal()
    target = next(
        item
        for item in doc["requests"]
        if item["stratum"] == "common_path" and item["cell"] == 0
    )
    target["cell"] = 3
    target["cell_family"] = "discrete_overflow"
    result = _run(doc, tmp_path)
    assert result.returncode == 1
    assert "MATRIX" in result.stdout


def test_null_count_must_be_four(tmp_path: Path) -> None:
    doc = _legal()
    target = next(
        item
        for item in doc["requests"]
        if item["stratum"] == "common_path" and item["cell"] == 0
    )
    target["reference_frame"] = None
    target["expected_outcome"] = "miss"
    target["expected_bucket"] = 1
    target["expressible_if"] = ["Venn"]
    result = _run(doc, tmp_path)
    assert result.returncode == 1
    assert "NULL_FRAMES" in result.stdout


def test_null_frame_requires_expressible_if(tmp_path: Path) -> None:
    doc = _legal()
    target = next(item for item in doc["requests"] if item["cell"] == 1)
    target["expressible_if"] = []
    result = _run(doc, tmp_path)
    assert result.returncode == 1
    assert "EXPRESSIBLE_IF" in result.stdout


def test_non_null_frame_must_carry_basesize(tmp_path: Path) -> None:
    doc = _legal()
    target = next(item for item in doc["requests"] if item["cell"] == 0)
    frame = cast(dict[str, Any], target["reference_frame"])
    del frame["chart_spec"]["baseSize"]
    result = _run(doc, tmp_path)
    assert result.returncode == 1
    assert "BASE_SIZE" in result.stdout


def test_non_null_frame_basesize_must_match_default(tmp_path: Path) -> None:
    doc = _legal()
    target = next(item for item in doc["requests"] if item["cell"] == 0)
    frame = cast(dict[str, Any], target["reference_frame"])
    frame["chart_spec"]["baseSize"] = {
        "width": DEFAULT_BASE_SIZE.width + 1,
        "height": DEFAULT_BASE_SIZE.height,
    }
    result = _run(doc, tmp_path)
    assert result.returncode == 1
    assert "BASE_SIZE" in result.stdout


def test_discrete_overflow_frame_must_pin_overflow_base_size(tmp_path: Path) -> None:
    doc = _legal()
    target = next(
        item
        for item in doc["requests"]
        if item.get("cell_family") == "discrete_overflow"
    )
    frame = cast(dict[str, Any], target["reference_frame"])
    frame["chart_spec"]["baseSize"] = _dump_size(DEFAULT_BASE_SIZE)
    result = _run(doc, tmp_path)
    assert result.returncode == 1
    assert "BASE_SIZE" in result.stdout


def test_non_null_frame_must_validate_against_the_facade(tmp_path: Path) -> None:
    doc = _legal()
    target = next(item for item in doc["requests"] if item["cell"] == 0)
    frame = cast(dict[str, Any], target["reference_frame"])
    frame["chart_spec"]["chartType"] = "Not A Chart"
    result = _run(doc, tmp_path)
    assert result.returncode == 1
    assert "FACADE" in result.stdout


def test_intent_map_fails_when_the_pin_gains_a_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from chartagent.frame import _generated

    monkeypatch.setattr(
        _generated,
        "CHART_TYPES",
        [*_generated.CHART_TYPES, "Venn"],
    )
    issues = _tool().validate(_LEGAL_PATH)
    assert any(line.startswith("INTENT_MAP") for line in issues)


def test_five_reserves_must_key_an_occupied_cell(tmp_path: Path) -> None:
    doc = _legal()
    doc["reserves"][0]["replaces"] = {"cell": 1, "stratum": "common_path"}
    doc["reserves"][0]["cell"] = 1
    doc["reserves"][0]["stratum"] = "common_path"
    doc["reserves"][0]["reference_frame"] = None
    doc["reserves"][0]["expressible_if"] = ["Venn"]
    doc["reserves"][0]["intent"] = _CELL1_INTENTS[0]
    doc["reserves"][0]["expected_outcome"] = "miss"
    doc["reserves"][0]["expected_bucket"] = 1
    doc["reserves"][0].pop("cell_family", None)
    result = _run(doc, tmp_path)
    assert result.returncode == 1
    assert "RESERVE" in result.stdout


def test_wrong_shape_marginals_are_rejected(tmp_path: Path) -> None:
    doc = _legal()
    long = next(
        item
        for item in doc["requests"]
        if item["stratum"] == "common_path" and item["shape"] == "long"
    )
    long["shape"] = "nested"
    result = _run(doc, tmp_path)
    assert result.returncode == 1
    assert "SHAPE" in result.stdout


def test_every_carryable_intent_is_floored_at_one(tmp_path: Path) -> None:
    doc = _legal()
    missing = "ranking / top-N"
    for item in doc["requests"]:
        if item["stratum"] == "common_path" and item["intent"] == missing:
            item["intent"] = "trend over time"
    result = _run(doc, tmp_path)
    assert result.returncode == 1
    assert "INTENT_FLOOR" in result.stdout
    assert missing in result.stdout


def test_cell1_may_not_name_a_missing_chart_type(tmp_path: Path) -> None:
    doc = _legal()
    target = next(item for item in doc["requests"] if item["cell"] == 1)
    target["query_original"] = "make me a Venn of campaign overlap"
    target["query_rewritten"] = "Make me a Venn of campaign overlap."
    result = _run(doc, tmp_path)
    assert result.returncode == 1
    assert "CELL1_TYPE" in result.stdout
    assert "venn" in result.stdout.lower()


def test_cell1_may_not_name_marimekko(tmp_path: Path) -> None:
    doc = _legal()
    target = next(item for item in doc["requests"] if item["cell"] == 1)
    target["query_original"] = "make me a Marimekko of campaign overlap"
    target["query_rewritten"] = "Make me a Marimekko of campaign overlap."
    result = _run(doc, tmp_path)
    assert result.returncode == 1
    assert "CELL1_TYPE" in result.stdout


def test_word_cloud_is_not_a_legal_cell1_intent(tmp_path: Path) -> None:
    doc = _legal()
    target = next(item for item in doc["requests"] if item["cell"] == 1)
    target["intent"] = "word cloud"
    result = _run(doc, tmp_path)
    assert result.returncode == 1
    assert "CELL1_INTENT" in result.stdout


def test_cell2_rejects_sql_the_locks_refuse(tmp_path: Path) -> None:
    doc = _legal()
    target = next(item for item in doc["requests"] if item["cell"] == 2)
    frame = cast(dict[str, Any], target["reference_frame"])
    frame["x_chartagent"]["transform"] = {"raw_sql": "SELECT 1; SELECT 2"}
    result = _run(doc, tmp_path)
    assert result.returncode == 1
    assert "CELL2_SQL" in result.stdout


def test_family_ii_common_path_degree_must_be_two(tmp_path: Path) -> None:
    doc = _legal()
    target = next(
        item
        for item in doc["requests"]
        if item.get("cell_family") == "ii" and item["stratum"] == "common_path"
    )
    target["ambiguity_degree"] = 4
    result = _run(doc, tmp_path)
    assert result.returncode == 1
    assert "AMBIGUITY" in result.stdout


def test_family_ii_adversarial_degree_must_be_at_least_four(
    tmp_path: Path,
) -> None:
    doc = _legal()
    target = next(
        item
        for item in doc["requests"]
        if item.get("cell_family") == "ii" and item["stratum"] == "adversarial"
    )
    target["ambiguity_degree"] = 2
    result = _run(doc, tmp_path)
    assert result.returncode == 1
    assert "AMBIGUITY" in result.stdout


def test_expected_outcome_is_derived_from_the_frame(tmp_path: Path) -> None:
    doc = _legal()
    target = next(item for item in doc["requests"] if item["cell"] == 0)
    target["expected_outcome"] = "miss"
    target["expected_bucket"] = 1
    result = _run(doc, tmp_path)
    assert result.returncode == 1
    assert "EXPECTED" in result.stdout


def test_usage_without_a_path_exits_two() -> None:
    result = subprocess.run(
        [sys.executable, str(_CHECK)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "usage" in result.stderr.lower()
