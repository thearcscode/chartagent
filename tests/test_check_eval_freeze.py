from __future__ import annotations

import copy
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
from chartagent.frame.input import DEFAULT_BASE_SIZE

_REPO = Path(__file__).resolve().parents[1]
_CHECK = _REPO / "tools" / "check_eval_freeze.py"

_INTENT_COUNTS = {
    "trend over time": 28,
    "comparison across categories": 36,
    "distribution of one measure": 4,
    "correlation between measures": 8,
    "part-to-whole": 24,
    "ranking / top-N": 8,
    "flow or transition between states": 4,
    "geographic distribution": 4,
    "single value against a target": 4,
}
_CARRYABLE = tuple(_INTENT_COUNTS)
_CELL1 = (
    ("set overlap / intersection structure", ["Venn", "Euler", "UpSet"]),
    ("set overlap / intersection structure", ["Venn", "Euler", "UpSet"]),
    ("compositional simplex", ["Ternary"]),
    ("origin–destination flow on a geography", ["Flow Map"]),
)
_CELL1_QUERIES = (
    "which customers are in both campaigns but not the app",
    "which of the twelve segments overlap on more than two products",
    "how the three ingredients mix in every blend",
    "commute flows between the five boroughs",
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _frame(raw_sql: str | None = None) -> dict[str, Any]:
    transform: dict[str, Any] = {"raw_sql": raw_sql} if raw_sql else {}
    return {
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": {"x": "quarter", "y": "revenue"},
            "baseSize": {
                "width": int(DEFAULT_BASE_SIZE.width),
                "height": int(DEFAULT_BASE_SIZE.height),
            },
        },
        "x_chartagent": {"transform": transform},
    }


class _Builder:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.n = 0

    def request(
        self,
        stratum: str,
        cell: int,
        shape: str,
        intent: str,
        *,
        prefix: str = "e",
        family: str | None = None,
        degree: int | None = None,
        cell1_slot: int = 0,
    ) -> dict[str, Any]:
        self.n += 1
        rid = f"{prefix}{self.n:03d}"
        data = f"data-{rid}".encode()
        path = f"eval/data/{rid}.parquet"
        (self.root / path).parent.mkdir(parents=True, exist_ok=True)
        (self.root / path).write_bytes(data)
        if cell == 1:
            intent, expressible = _CELL1[cell1_slot]
            original = _CELL1_QUERIES[cell1_slot] + f" ({rid})"
            frame = None
            outcome, bucket = "miss", 1
        else:
            original = f"sales by quarter for {rid}"
            frame = _frame("SELECT quarter, revenue FROM source" if cell == 2 else None)
            expressible = None
            outcome, bucket = "hit", None
        rewritten = original.capitalize() + "."
        return {
            "id": rid,
            "instruction": rewritten,
            "source": "authored" if cell else "nvbench1",
            "source_id": f"src-{rid}",
            "query_original": original,
            "query_rewritten": rewritten,
            "stratum": stratum,
            "cell": cell,
            "cell_family": family,
            "intent": intent,
            "shape": shape,
            "dataset_path": path,
            "dataset_sha256": _sha(data),
            "reference_frame": frame,
            "expressible_if": expressible,
            "ambiguity_degree": degree,
            "expected_outcome": outcome,
            "expected_bucket": bucket,
        }


def _rep(
    n: int, cell: int, family: str | None = None, degree: int | None = None
) -> list[tuple[int, str | None, int | None]]:
    return [(cell, family, degree)] * n


def _hrep(
    n: int, stratum: str, cell: int, family: str | None = None
) -> list[tuple[str, int, str | None]]:
    return [(stratum, cell, family)] * n


def _intents() -> list[str]:
    return [name for name, n in _INTENT_COUNTS.items() for _ in range(n)]


def _public(b: _Builder) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    intents = iter(_intents())
    common: list[tuple[int, str | None, int | None]] = (
        _rep(90, 0)
        + _rep(12, 2)
        + _rep(2, 3, "silent_row_drop")
        + _rep(10, 4, "ii", 2)
        + _rep(4, 4, "iii")
        + _rep(2, 4, "iv")
    )
    c2_shapes = iter(["wide"] * 6 + ["wide_sparse"] * 6)
    rest = iter(["long"] * 48 + ["wide"] * 42 + ["nested"] * 12 + ["wide_sparse"] * 6)
    for cell, family, degree in common:
        shape = next(c2_shapes) if cell == 2 else next(rest)
        out.append(
            b.request(
                "common_path",
                cell,
                shape,
                next(intents),
                family=family,
                degree=degree,
            )
        )
    adv: list[tuple[int, str | None, int | None]] = (
        _rep(4, 1)
        + _rep(8, 2)
        + _rep(8, 4, "i")
        + _rep(2, 4, "ii", 4)
        + _rep(4, 4, "iii")
        + _rep(4, 4, "iv")
    )
    c2_shapes = iter(["wide"] * 4 + ["wide_sparse"] * 4)
    rest = iter(["long"] * 6 + ["wide"] * 5 + ["nested"] * 6 + ["wide_sparse"] * 5)
    slot = 0
    for i, (cell, family, degree) in enumerate(adv):
        shape = next(c2_shapes) if cell == 2 else next(rest)
        out.append(
            b.request(
                "adversarial",
                cell,
                shape,
                _CARRYABLE[i % 9],
                family=family,
                degree=degree,
                cell1_slot=slot,
            )
        )
        slot += cell == 1
    return out


def _holdout(b: _Builder) -> list[dict[str, Any]]:
    plan: list[tuple[str, int, str | None]] = (
        _hrep(15, "common_path", 0)
        + _hrep(3, "common_path", 2)
        + _hrep(1, "common_path", 3, "silent_row_drop")
        + _hrep(5, "common_path", 4, "iii")
        + _hrep(1, "adversarial", 1)
        + _hrep(2, "adversarial", 2)
        + _hrep(3, "adversarial", 4, "i")
    )
    return [
        b.request(
            stratum,
            cell,
            "wide",
            _CARRYABLE[i % 9],
            prefix="h",
            family=family,
            degree=None,
        )
        for i, (stratum, cell, family) in enumerate(plan)
    ]


def _smoke(requests: list[dict[str, Any]]) -> list[str]:
    def pick(cell: int, stratum: str, n: int) -> list[str]:
        return [
            r["id"] for r in requests if r["cell"] == cell and r["stratum"] == stratum
        ][:n]

    return (
        pick(0, "common_path", 18)
        + pick(1, "adversarial", 1)
        + pick(2, "common_path", 2)
        + pick(2, "adversarial", 2)
        + pick(3, "common_path", 1)
        + pick(4, "common_path", 3)
        + pick(4, "adversarial", 3)
    )


def _instruments(root: Path) -> dict[str, Path]:
    corpus_bytes = b"corpus-bytes"
    (root / "corpus" / "data").mkdir(parents=True)
    (root / "corpus" / "data" / "r01.parquet").write_bytes(corpus_bytes)
    (root / "corpus" / "pre-registration.json").write_text(
        json.dumps(
            {
                "requests": [
                    {
                        "query_rewritten": "Corpus question.",
                        "dataset_sha256": _sha(corpus_bytes),
                    }
                ],
                "reserves": [
                    {
                        "query_rewritten": "Reserve question.",
                        "dataset_sha256": _sha(b"reserve"),
                    }
                ],
            }
        )
    )
    fa = root / "tests" / "data" / "first_ask"
    fa.mkdir(parents=True)
    (fa / "sales.csv").write_bytes(b"fixture-bytes")
    (fa / "instructions.json").write_text(
        json.dumps(
            [{"id": "fa01", "fixture": "sales.csv", "instruction": "First ask."}]
        )
    )
    injection = root / "injection.json"
    injection.write_text(
        json.dumps([{"instruction": "Ignore all.", "dataset_sha256": _sha(b"inj")}])
    )
    return {"injection-suite": injection}


def _freeze(root: Path) -> dict[str, Any]:
    b = _Builder(root)
    requests = _public(b)
    pool = _holdout(b)
    return {
        "flint_version": "1.2.3",
        "fixture_commit": "abc1234",
        "requests": requests,
        "holdout_pool": pool,
        "holdout_permutation": [r["id"] for r in reversed(pool)],
        "smoke_ids": _smoke(requests),
        "human_calibration_permutation": [r["id"] for r in reversed(requests)],
    }


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_check_eval_freeze", _CHECK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _World:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.doc = _freeze(root)
        self.instruments = _instruments(root)

    def issues(self) -> list[str]:
        path = self.root / "pre-registration.json"
        path.write_text(json.dumps(self.doc), encoding="utf-8")
        return cast(list[str], _tool().validate(path, self.root, self.instruments))

    def public(self, index: int) -> dict[str, Any]:
        return cast(dict[str, Any], self.doc["requests"][index])


@pytest.fixture
def world(tmp_path: Path) -> _World:
    return _World(tmp_path)


def _names(issues: list[str]) -> set[str]:
    return {line.split()[0] for line in issues}


def test_harness_is_not_on_the_public_surface() -> None:
    assert not any("freeze" in name.lower() for name in chartagent.__all__)


def test_generated_legal_freeze_passes(world: _World) -> None:
    assert world.issues() == []


def test_miscounted_cell_is_named(world: _World) -> None:
    world.public(0)["cell"] = 2
    assert "MATRIX" in _names(world.issues())


def test_duplicate_id_is_named(world: _World) -> None:
    world.public(1)["id"] = world.public(0)["id"]
    assert "IDS" in _names(world.issues())


def test_tampered_dataset_hash_is_named(world: _World) -> None:
    (world.root / world.public(0)["dataset_path"]).write_bytes(b"tampered")
    issues = world.issues()
    assert any(i.startswith("DATASET") and "sha256" in i for i in issues)


def test_missing_dataset_is_named(world: _World) -> None:
    (world.root / world.public(0)["dataset_path"]).unlink()
    assert "DATASET" in _names(world.issues())


def test_pair_shared_with_corpus_prereg_is_named(world: _World) -> None:
    item = world.public(0)
    item["instruction"] = "Corpus question."
    item["query_rewritten"] = "Corpus question."
    # same instruction on the same bytes as a corpus request
    data = b"corpus-bytes"
    (world.root / item["dataset_path"]).write_bytes(data)
    item["dataset_sha256"] = _sha(data)
    issues = world.issues()
    assert any(i.startswith("OVERLAP") and "corpus-prereg-v1" in i for i in issues)


def test_pair_shared_with_first_ask_is_named(world: _World) -> None:
    item = world.public(0)
    item["instruction"] = "First ask."
    item["query_rewritten"] = "First ask."
    data = b"fixture-bytes"
    (world.root / item["dataset_path"]).write_bytes(data)
    item["dataset_sha256"] = _sha(data)
    issues = world.issues()
    assert any(i.startswith("OVERLAP") and "first-ask" in i for i in issues)


def test_pair_shared_with_injection_suite_is_named(world: _World) -> None:
    item = world.doc["holdout_pool"][0]
    item["instruction"] = "Ignore all."
    data = b"inj"
    (world.root / item["dataset_path"]).write_bytes(data)
    item["dataset_sha256"] = _sha(data)
    issues = world.issues()
    assert any(i.startswith("OVERLAP") and "injection-suite" in i for i in issues)


def test_reusing_corpus_dataset_bytes_is_named(world: _World) -> None:
    item = world.public(0)
    data = b"corpus-bytes"
    (world.root / item["dataset_path"]).write_bytes(data)
    item["dataset_sha256"] = _sha(data)
    assert "CORPUS_DATA" in _names(world.issues())


def test_missing_injection_suite_is_named(world: _World) -> None:
    world.instruments.clear()
    assert "INSTRUMENT" in _names(world.issues())


def test_excel_named_request_is_named(world: _World) -> None:
    world.public(3)["query_original"] = "put sales in an Excel chart"
    assert "EXCEL" in _names(world.issues())


def test_wrong_shape_marginals_are_named(world: _World) -> None:
    world.public(0)["shape"] = "nested"
    assert "SHAPE" in _names(world.issues())


def test_wrong_intent_counts_are_named(world: _World) -> None:
    first, last = world.public(0), world.public(89)
    assert first["intent"] != last["intent"]
    first["intent"] = last["intent"]
    assert "INTENTS" in _names(world.issues())


def test_cell4_family_table_is_enforced(world: _World) -> None:
    item = next(r for r in world.doc["requests"] if r["cell_family"] == "iii")
    item["cell_family"] = "iv"
    assert "CELL4_FAMILY" in _names(world.issues())


def test_cell1_on_the_common_path_is_named(world: _World) -> None:
    item = next(r for r in world.doc["requests"] if r["cell"] == 1)
    item["stratum"] = "common_path"
    assert "CELL1" in _names(world.issues())


def test_smoke_mix_is_enforced(world: _World) -> None:
    other = next(
        r["id"]
        for r in world.doc["requests"]
        if r["cell"] == 0 and r["id"] not in world.doc["smoke_ids"]
    )
    world.doc["smoke_ids"][0] = other
    world.doc["smoke_ids"][1] = other
    assert "SMOKE" in _names(world.issues())


def test_holdout_mix_is_enforced(world: _World) -> None:
    world.doc["holdout_pool"][0]["cell"] = 4
    world.doc["holdout_pool"][0]["cell_family"] = "iii"
    assert "HOLDOUT" in _names(world.issues())


def test_holdout_ids_must_be_disjoint_from_public(world: _World) -> None:
    world.doc["holdout_pool"][0]["id"] = world.public(0)["id"]
    assert "IDS" in _names(world.issues())


def test_permutations_must_cover_their_sets(world: _World) -> None:
    world.doc["human_calibration_permutation"].pop()
    world.doc["holdout_permutation"][0] = world.public(0)["id"]
    issues = world.issues()
    assert sum(i.startswith("PERMUTATION") for i in issues) == 2


def test_unfaithful_expected_outcome_is_named(world: _World) -> None:
    world.public(0)["expected_outcome"] = "miss"
    assert "EXPECTED" in _names(world.issues())


def test_facade_invalid_frame_is_named(world: _World) -> None:
    world.public(0)["reference_frame"]["chart_spec"]["chartType"] = "Nope Chart"
    assert "FACADE" in _names(world.issues())


def test_cell2_unsafe_sql_is_named(world: _World) -> None:
    item = next(r for r in world.doc["requests"] if r["cell"] == 2)
    item["reference_frame"]["x_chartagent"]["transform"]["raw_sql"] = (
        "COPY source TO 'x.csv'"
    )
    assert "CELL2_SQL" in _names(world.issues())


def test_schema_error_is_named(world: _World) -> None:
    doc = copy.deepcopy(world.doc)
    del doc["smoke_ids"]
    world.doc = doc
    assert "SCHEMA" in _names(world.issues())


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_CHECK), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_exit_codes(world: _World) -> None:
    path = world.root / "pre-registration.json"
    inj = world.instruments["injection-suite"]
    path.write_text(json.dumps(world.doc), encoding="utf-8")
    ok = _run(
        str(path), "--repo", str(world.root), "--instrument", f"injection-suite={inj}"
    )
    assert ok.returncode == 0, ok.stdout
    bad = _run(str(path), "--repo", str(world.root))
    assert bad.returncode == 1
    assert "INSTRUMENT" in bad.stdout
    assert _run().returncode == 2
    assert _run(str(path), "--instrument", "nope").returncode == 2
