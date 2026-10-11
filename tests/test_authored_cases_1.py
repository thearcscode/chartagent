"""eval/cases-authored-1.json against the freeze validator's per-case checks
(issue #285). The validator is the real check; this assembles the partial file
into a Freeze-shaped object so its own checks run on our 14 cases."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parents[1]
_CASES = _REPO / "eval" / "cases-authored-1.json"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_check_eval_freeze_285", _REPO / "tools" / "check_eval_freeze.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return _tool()


@pytest.fixture(scope="module")
def raw() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = json.loads(_CASES.read_text(encoding="utf-8"))[
        "cases"
    ]
    return cases


@pytest.fixture(scope="module")
def doc(tool: ModuleType, raw: list[dict[str, Any]]) -> Any:
    return tool.Freeze.model_validate(
        {
            "flint_version": "0",
            "fixture_commit": "0",
            "requests": raw,
            "holdout_pool": [],
            "holdout_permutation": [],
            "smoke_ids": [],
            "human_calibration_permutation": [],
        }
    )


def test_counts_are_4_2_8(raw: list[dict[str, Any]]) -> None:
    by = Counter((c["stratum"], c["cell"]) for c in raw)
    assert by == {
        ("adversarial", 1): 4,
        ("common_path", 3): 2,
        ("adversarial", 2): 8,
    }
    assert len({c["id"] for c in raw}) == 14
    assert all(c["id"].startswith("auth-") for c in raw)


def test_adversarial_cell2_shapes_are_carryable(raw: list[dict[str, Any]]) -> None:
    shapes = {c["shape"] for c in raw if c["cell"] == 2}
    assert shapes <= {"wide", "wide_sparse", "nested"}


def test_cell1_is_the_three_intents(raw: list[dict[str, Any]]) -> None:
    assert Counter(c["intent"] for c in raw if c["cell"] == 1) == {
        "set overlap / intersection structure": 2,
        "compositional simplex": 1,
        "origin–destination flow on a geography": 1,
    }


@pytest.mark.parametrize(
    "check",
    ["_check_cell1", "_check_shapes", "_check_excel"],
)
def test_validator_group_checks_pass(tool: ModuleType, doc: Any, check: str) -> None:
    fn = getattr(tool, check)
    arg = doc if check == "_check_excel" else doc.requests
    issues = fn(arg)
    # _check_shapes also compares marginals against the full 150; only the
    # per-case cell-2 legality lines are in scope for a partial file.
    issues = [
        i for i in issues if not i.startswith("SHAPE              ") or ": cell-2" in i
    ]
    assert issues == []


def test_cell3_cases_are_silent_row_drop_on_the_common_path(
    tool: ModuleType, doc: Any
) -> None:
    issues = [i for i in tool._check_cell34(doc.requests) if i.startswith("CELL3")]
    assert issues == []
    assert {c.cell_family for c in doc.requests if c.cell == 3} == {"silent_row_drop"}


def test_every_case_passes_the_per_request_checks(tool: ModuleType, doc: Any) -> None:
    assert tool._check_requests(doc) == []


def test_datasets_are_pinned_under_eval_data(tool: ModuleType, doc: Any) -> None:
    assert tool._check_datasets(doc, _REPO) == []
    assert all(c.dataset_path.startswith("eval/data/authored-") for c in doc.requests)
    assert len({c.dataset_sha256 for c in doc.requests}) == 14


def test_disjoint_from_corpus_and_first_ask(tool: ModuleType, doc: Any) -> None:
    files = {
        "corpus-prereg-v1": _REPO / "corpus" / "pre-registration.json",
        "first-ask": _REPO / "tests" / "data" / "first_ask" / "instructions.json",
    }
    issues = tool._check_disjoint(doc, _REPO, files)
    # injection-suite has no file in the repo; every other line must be clean.
    assert [i for i in issues if "injection-suite" not in i] == []
