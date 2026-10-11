"""The eval gate's refusals, against a small synthetic freeze (#280, ADR-0029).

The seam is the CLI and the pure ``score`` core behind it: a pre-registration
plus a run's harness records go in, an accepted report or a named refusal comes
out. The freeze here is built in a throwaway git repo carrying the
``eval-benchmark-v1`` tag, because the real set is not authored yet.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

_SCORE = Path(__file__).resolve().parents[1] / "tools" / "score_eval.py"

QUALITIES = ("fast", "balanced", "best")
# (id, cell, rail): every cell, both rails.
PUBLIC = [
    ("e01", 0, "flint"),
    ("e02", 0, "flint"),
    ("e03", 0, "flint"),
    ("e04", 1, "custom"),
    ("e05", 2, "flint"),
    ("e06", 2, "custom"),
    ("e07", 3, "flint"),
    ("e08", 4, "flint"),
    ("e09", 4, "custom"),
]
HOLDOUT = ["h01", "h02", "h03"]
SMOKE = ["e01", "e04", "e08"]


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("score_eval", _SCORE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dataset_bytes(case_id: str) -> bytes:
    return f"parquet-bytes-{case_id}".encode()


def _request(case_id: str, cell: int, rail: str) -> dict[str, Any]:
    return {
        "id": case_id,
        "cell": cell,
        "expected_rail": rail,
        "instruction": f"instruction for {case_id}",
        "dataset_path": f"eval/data/{case_id}.parquet",
        "dataset_sha256": hashlib.sha256(_dataset_bytes(case_id)).hexdigest(),
    }


def _prereg() -> dict[str, Any]:
    return {
        "flint_version": "0.0.0",
        "fixture_commit": "abc123",
        "smoke_ids": list(SMOKE),
        "requests": [_request(i, c, r) for i, c, r in PUBLIC],
        "holdout_pool": [_request(i, 0, "flint") for i in HOLDOUT],
        "holdout_permutation": list(reversed(HOLDOUT)),
        "human_calibration_permutation": [i for i, _, _ in PUBLIC],
    }


def _record(case_id: str, quality: str) -> dict[str, Any]:
    return {
        "request_id": case_id,
        "quality": quality,
        "backend": "vega-lite",
        "painted": "pass",
    }


def _records(ids: list[str], qualities: tuple[str, ...] = QUALITIES) -> dict[str, Any]:
    return {"records": [_record(i, q) for i in ids for q in qualities]}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


class Freeze:
    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.prereg_path = repo / "eval" / "pre-registration.json"

    def write_prereg(self, prereg: dict[str, Any]) -> None:
        self.prereg_path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(prereg, indent=2) + "\n"
        self.prereg_path.write_bytes(text.encode())

    def run(
        self,
        outputs: dict[str, Any],
        *args: str,
        mode: str = "nightly",
    ) -> subprocess.CompletedProcess[str]:
        path = self.repo / "outputs.json"
        path.write_text(json.dumps(outputs), encoding="utf-8")
        return subprocess.run(
            [
                sys.executable,
                str(_SCORE),
                str(path),
                "--repo",
                str(self.repo),
                "--mode",
                mode,
                *args,
            ],
            check=False,
            capture_output=True,
            text=True,
        )


def _make_freeze(repo: Path, *, tag: bool = True) -> Freeze:
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "config", "tag.gpgsign", "false")
    _git(repo, "config", "core.autocrlf", "false")
    freeze = Freeze(repo)
    prereg = _prereg()
    freeze.write_prereg(prereg)
    for item in prereg["requests"] + prereg["holdout_pool"]:
        data = repo / item["dataset_path"]
        data.parent.mkdir(parents=True, exist_ok=True)
        data.write_bytes(_dataset_bytes(item["id"]))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "freeze")
    if tag:
        _git(repo, "tag", "eval-benchmark-v1")
    return freeze


def _public_ids() -> list[str]:
    return [i for i, _, _ in PUBLIC]


def _refused(proc: subprocess.CompletedProcess[str], prefix: str) -> str:
    assert proc.returncode == 1, proc.stdout + proc.stderr
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith(prefix)), None)
    assert line is not None, proc.stdout
    return line


def test_matching_run_is_accepted_and_report_written(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    out = tmp_path / "report.json"
    proc = freeze.run(_records(_public_ids()), "--json", str(out))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["status"] == "accepted"
    assert report["mode"] == "nightly"
    assert report["n"] == len(PUBLIC)
    assert report["tag"] == "eval-benchmark-v1"


def test_missing_tag_refuses_with_no_fallback_digest(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path, tag=False)
    line = _refused(freeze.run(_records(_public_ids())), "TAG")
    assert "eval-benchmark-v1" in line


def test_prereg_edited_after_tag_refuses(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    moved = _prereg()
    moved["requests"][0]["instruction"] = "moved"
    freeze.write_prereg(moved)
    line = _refused(freeze.run(_records(_public_ids())), "HASH")
    assert "pre-registration" in line


def test_crlf_checkout_of_the_tagged_prereg_is_accepted(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    raw = freeze.prereg_path.read_bytes()
    freeze.prereg_path.write_bytes(raw.replace(b"\n", b"\r\n"))
    proc = freeze.run(_records(_public_ids()))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_dataset_swapped_refuses_naming_the_dataset(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    (tmp_path / "eval/data/e03.parquet").write_bytes(b"swapped")
    line = _refused(freeze.run(_records(_public_ids())), "DATASET")
    assert "e03" in line


def test_dataset_missing_refuses(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    (tmp_path / "eval/data/e05.parquet").unlink()
    line = _refused(freeze.run(_records(_public_ids())), "DATASET")
    assert "e05" in line


def test_missing_case_refuses(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    ids = [i for i in _public_ids() if i != "e07"]
    line = _refused(freeze.run(_records(ids)), "IDS")
    assert "missing" in line and "e07" in line


def test_extra_case_refuses(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    line = _refused(freeze.run(_records([*_public_ids(), "zz9"])), "IDS")
    assert "extra" in line and "zz9" in line


def test_holdout_id_in_public_run_refuses_by_name(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    line = _refused(freeze.run(_records([*_public_ids(), "h02"])), "IDS")
    assert "hold-out" in line and "h02" in line


def test_repeated_record_per_case_and_quality_refuses(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _records(_public_ids())
    outputs["records"].append(_record("e02", "balanced"))
    line = _refused(freeze.run(outputs), "REPEATS")
    assert "e02" in line and "balanced" in line


def test_cross_instrument_overlap_refuses_per_instrument(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    prereg = _prereg()
    request = prereg["requests"][3]
    pressure = tmp_path / "pressure.json"
    pressure.write_text(
        json.dumps(
            {
                "requests": [
                    {
                        "query_rewritten": request["instruction"],
                        "dataset_sha256": request["dataset_sha256"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    injection = tmp_path / "injection.json"
    injection.write_text(
        json.dumps(
            [
                {
                    "instruction": "instruction for e01",
                    "dataset_sha256": prereg["requests"][0]["dataset_sha256"],
                },
                {"instruction": "instruction for e02", "dataset_sha256": "other"},
            ]
        ),
        encoding="utf-8",
    )
    proc = freeze.run(
        _records(_public_ids()),
        "--instrument",
        f"pressure-corpus={pressure}",
        "--instrument",
        f"injection-suite={injection}",
    )
    assert proc.returncode == 1
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("OVERLAP")]
    assert len(lines) == 2
    assert any("pressure-corpus" in ln and "e04" in ln for ln in lines)
    assert any("injection-suite" in ln and "e01" in ln for ln in lines)
    assert not any("e02" in ln for ln in lines)


def test_each_refusal_has_its_own_message(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _records([i for i in _public_ids() if i != "e07"])
    outputs["records"].append(_record("e02", "fast"))
    proc = freeze.run(outputs)
    prefixes = {ln.split()[0] for ln in proc.stdout.splitlines() if ln[:1].isupper()}
    assert {"IDS", "REPEATS"} <= prefixes


def test_smoke_mode_expects_exactly_the_frozen_smoke_ids_at_balanced(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    ok = freeze.run(_records(SMOKE, ("balanced",)), mode="smoke")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    wide = freeze.run(_records(_public_ids(), ("balanced",)), mode="smoke")
    assert "extra" in _refused(wide, "IDS")


def test_holdout_mode_scores_the_permutation_pick_not_the_public_set(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    ok = freeze.run(_records(HOLDOUT, ("balanced",)), mode="holdout")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    public = freeze.run(_records(_public_ids(), ("balanced",)), mode="holdout")
    assert "IDS" in public.stdout and public.returncode == 1


def test_core_score_returns_report_or_raises_named_refusal() -> None:
    module = _tool()
    prereg = _prereg()
    digest = "d" * 64
    kwargs: dict[str, Any] = {
        "mode": "nightly",
        "tag_digest": digest,
        "prereg_sha256": digest,
        "dataset_sha256": {
            r["id"]: r["dataset_sha256"]
            for r in prereg["requests"] + prereg["holdout_pool"]
        },
        "instruments": {},
    }
    report = module.score(prereg, _records(_public_ids()), **kwargs)
    assert report["n"] == len(PUBLIC)
    for override, prefix in (
        ({"tag_digest": None}, "TAG"),
        ({"prereg_sha256": "e" * 64}, "HASH"),
    ):
        bad = copy.deepcopy(kwargs) | override
        try:
            module.score(prereg, _records(_public_ids()), **bad)
        except module.Refusal as refusal:
            assert refusal.issues[0].startswith(prefix)
        else:
            raise AssertionError("expected a refusal")


def test_usage_error_exits_two(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(_SCORE)], check=False, capture_output=True, text=True
    )
    assert proc.returncode == 2
    assert "usage" in proc.stderr
    bad_mode = _make_freeze(tmp_path).run(_records(_public_ids()), mode="bogus")
    assert bad_mode.returncode == 2
