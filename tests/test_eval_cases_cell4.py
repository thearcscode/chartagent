"""The authored cell-4 partial cases file is legal under the freeze validator."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_CASES = _REPO / "eval" / "cases-cell4.json"


def _validator():
    spec = importlib.util.spec_from_file_location(
        "_freeze_validator", _REPO / "tools" / "check_eval_freeze.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker():
    return _validator()


@pytest.fixture(scope="module")
def requests(checker):
    raw = json.loads(_CASES.read_text(encoding="utf-8"))["requests"]
    return [checker.Request.model_validate(item) for item in raw]


def test_family_table_and_degrees(checker, requests) -> None:
    assert len(requests) == 34
    assert checker._check_cell34(requests) == []


def test_each_case_is_legal(checker, requests) -> None:
    sib = checker._sibling()
    connection = checker.open_connection()
    try:
        for item in requests:
            assert checker._check_request(item, sib, connection) == []
    finally:
        connection.close()


def test_data_pinned_authored_and_disjoint(checker, requests) -> None:
    class _Doc:
        holdout_pool: list = []

    doc = _Doc()
    doc.requests = requests  # type: ignore[attr-defined]
    assert checker._check_datasets(doc, _REPO) == []  # type: ignore[arg-type]
    assert checker._check_excel(doc) == []  # type: ignore[arg-type]
    assert all(
        i.dataset_path.startswith("eval/data/authored-c4-") for i in requests
    )
    assert len({i.dataset_sha256 for i in requests}) == 34
    corpus = {
        p.read_bytes() for p in (_REPO / "corpus" / "data").iterdir() if p.is_file()
    }
    assert not any((_REPO / i.dataset_path).read_bytes() in corpus for i in requests)


def test_strata_split(requests) -> None:
    assert Counter(i.stratum for i in requests) == {"common_path": 16, "adversarial": 18}
