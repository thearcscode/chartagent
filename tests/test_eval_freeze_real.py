"""The committed eval/pre-registration.json, its validator and the gate (#287)."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parents[1]
_FREEZE = _REPO / "eval" / "pre-registration.json"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _REPO / "tools" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def check() -> ModuleType:
    return _load("check_eval_freeze")


@pytest.fixture(scope="module")
def score() -> ModuleType:
    return _load("score_eval")


@pytest.fixture(scope="module")
def prereg() -> dict[str, Any]:
    return json.loads(_FREEZE.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture
def instruments(tmp_path: Path) -> dict[str, Path]:
    # No injection-suite request list is committed anywhere; an empty one is the
    # honest instrument, so the other two overlap checks still run for real.
    injection = tmp_path / "injection.json"
    injection.write_text("[]", encoding="utf-8")
    return {"injection-suite": injection}


def _mutated(tmp_path: Path, doc: dict[str, Any]) -> Path:
    path = tmp_path / "pre-registration.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_real_freeze_is_legal(check: ModuleType, instruments: dict[str, Path]) -> None:
    assert check.validate(_FREEZE, _REPO, instruments) == []


def test_miscounted_cell_is_named(
    check: ModuleType,
    prereg: dict[str, Any],
    instruments: dict[str, Path],
    tmp_path: Path,
) -> None:
    doc = copy.deepcopy(prereg)
    victim = next(r for r in doc["requests"] if r["cell"] == 0)
    victim["cell"] = 2
    issues = check.validate(_mutated(tmp_path, doc), _REPO, instruments)
    assert any(i.startswith("MATRIX") for i in issues)


def test_duplicated_id_is_named(
    check: ModuleType,
    prereg: dict[str, Any],
    instruments: dict[str, Path],
    tmp_path: Path,
) -> None:
    doc = copy.deepcopy(prereg)
    doc["requests"][1]["id"] = doc["requests"][0]["id"]
    issues = check.validate(_mutated(tmp_path, doc), _REPO, instruments)
    assert any(i.startswith("IDS") and "duplicate" in i for i in issues)


def test_tampered_dataset_hash_is_named(
    check: ModuleType,
    prereg: dict[str, Any],
    instruments: dict[str, Path],
    tmp_path: Path,
) -> None:
    doc = copy.deepcopy(prereg)
    doc["holdout_pool"][0]["dataset_sha256"] = "0" * 64
    issues = check.validate(_mutated(tmp_path, doc), _REPO, instruments)
    assert any(i.startswith("DATASET") and "sha256" in i for i in issues)


def test_every_dataset_digest_matches_for_all_180_cases(
    score: ModuleType, prereg: dict[str, Any]
) -> None:
    cases = [*prereg["requests"], *prereg["holdout_pool"]]
    assert len(cases) == 180
    actual = score._dataset_digests(_REPO, prereg)
    assert all(actual[c["id"]] == c["dataset_sha256"] for c in cases)


def test_freeze_digest_is_lf_stable(score: ModuleType) -> None:
    raw = _FREEZE.read_bytes()
    assert b"\r" not in raw
    assert score.digest(raw) == hashlib.sha256(raw).hexdigest()
    assert score.digest(raw.replace(b"\n", b"\r\n")) == score.digest(raw)


def test_synthetic_outputs_for_the_150_pass_the_gate_id_and_size_checks(
    score: ModuleType, prereg: dict[str, Any]
) -> None:
    assert score._prereg_size_issues(prereg) == []
    pairs = {(r["id"], q) for r in prereg["requests"] for q in score.QUALITIES}
    assert score._id_issues(prereg, "publish", pairs) == []
    smoke = {(i, "balanced") for i in prereg["smoke_ids"]}
    assert score._id_issues(prereg, "smoke", smoke) == []
    pool = prereg["holdout_permutation"][: score.HOLDOUT_SIZE]
    holdout = {(i, q) for i in pool for q in score.QUALITIES}
    assert score._id_issues(prereg, "holdout", holdout) == []


def test_permutations_and_seeds_are_recorded(prereg: dict[str, Any]) -> None:
    assert set(prereg["seeds"]) == {
        "smoke_ids",
        "holdout_permutation",
        "human_calibration_permutation",
    }
    public = [r["id"] for r in prereg["requests"]]
    assert sorted(prereg["human_calibration_permutation"]) == sorted(public)
    assert prereg["human_calibration_permutation"] != public
    assert not set(prereg["holdout_permutation"]) & set(public)
