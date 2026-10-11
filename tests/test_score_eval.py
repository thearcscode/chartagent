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

import pytest

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


_CUSTOM_IDS = {i for i, _, r in PUBLIC if r == "custom"}


def _record(case_id: str, quality: str) -> dict[str, Any]:
    if case_id in _CUSTOM_IDS:
        return {
            "request_id": case_id,
            "quality": quality,
            "rail": "custom",
            "raster_nonblank": True,
        }
    return {
        "request_id": case_id,
        "quality": quality,
        "rail": "flint",
        "backend": "vega-lite",
        "painted": "pass",
        "compiled_row_count": 10,
        "bound_row_count": 10,
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


# --- executable-output rate (#272) -------------------------------------------


def _with(outputs: dict[str, Any], case_id: str, quality: str, **fields: Any) -> None:
    for record in outputs["records"]:
        if record["request_id"] == case_id and record["quality"] == quality:
            record.update(fields)
            return
    raise AssertionError("no such record")


def _executable(freeze: Freeze, outputs: dict[str, Any]) -> dict[str, Any]:
    out = freeze.repo / "r.json"
    proc = freeze.run(outputs, "--json", str(out))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    executable: dict[str, Any] = report["executable"]
    return executable


def test_all_hits_gives_full_rate_over_the_frozen_n_per_quality(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    executable = _executable(freeze, _records(_public_ids()))
    for quality in QUALITIES:
        row = executable["by_quality"][quality]
        assert (row["k"], row["n"]) == (len(PUBLIC), len(PUBLIC))
        assert row["rate"] == 1.0
        assert 0 < row["wilson_95"]["lower"] < 1.0 <= row["wilson_95"]["upper"] + 1e-9


def test_wilson_is_the_corpus_scorers_implementation(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _records(_public_ids())
    _with(outputs, "e01", "balanced", painted="fail")
    row = _executable(freeze, outputs)["by_quality"]["balanced"]
    spec = importlib.util.spec_from_file_location(
        "score_corpus", _SCORE.with_name("score_corpus.py")
    )
    assert spec is not None and spec.loader is not None
    corpus = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(corpus)
    assert row["wilson_95"] == corpus.wilson_interval(8, 9)


def test_blank_canvas_row_drop_raise_and_throw_are_misses(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _records(_public_ids())
    _with(outputs, "e01", "balanced", painted="fail")
    _with(outputs, "e02", "balanced", compiled_row_count=9)
    _with(outputs, "e03", "balanced", error="PlanError: boom")
    _with(outputs, "e04", "balanced", raster_nonblank=False)
    _with(outputs, "e06", "balanced", error="RasterisationError: x")
    row = _executable(freeze, outputs)["by_quality"]["balanced"]
    assert (row["k"], row["n"]) == (4, 9)
    assert row["misses"] == ["e01", "e02", "e03", "e04", "e06"]
    assert _executable(freeze, _records(_public_ids()))["by_quality"]["fast"]["k"] == 9


def test_other_review_signals_play_no_part(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _records(_public_ids())
    for case_id in _public_ids():
        _with(
            outputs,
            case_id,
            "balanced",
            marks_present="fail",
            data_truthfulness="fail",
            review_passed=False,
        )
    assert _executable(freeze, outputs)["by_quality"]["balanced"]["k"] == 9


def test_custom_hit_is_the_rasterisers_verdict_not_a_painted_check(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _records(_public_ids())
    _with(outputs, "e04", "fast", raster_nonblank=False)
    assert _executable(freeze, outputs)["by_quality"]["fast"]["misses"] == ["e04"]


def test_custom_record_with_a_flint_shape_is_inconsistent(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _records(_public_ids())
    _with(outputs, "e04", "fast", painted="pass")
    assert "e04" in _refused(freeze.run(outputs), "RAIL")
    outputs = _records(_public_ids())
    _with(outputs, "e04", "fast", rail="flint")
    assert "e04" in _refused(freeze.run(outputs), "RAIL")


def test_flint_painted_not_checked_is_a_harness_misconfiguration(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _records(_public_ids())
    _with(outputs, "e01", "best", painted="not_checked")
    line = _refused(freeze.run(outputs), "HARNESS")
    assert "e01" in line and "not_checked" in line


def test_excel_record_is_an_authoring_fault(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _records(_public_ids())
    _with(outputs, "e02", "fast", backend="excel")
    assert "e02" in _refused(freeze.run(outputs), "AUTHORING")


def test_png_bytes_in_outputs_are_refused(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _records(_public_ids())
    _with(outputs, "e04", "fast", png="iVBORw0KGgoAAAANSUhEUg==")
    assert "e04" in _refused(freeze.run(outputs), "PNG")


def test_interval_spanning_the_target_is_never_a_gate_result(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _records(_public_ids())
    _with(outputs, "e01", "balanced", painted="fail")
    executable = _executable(freeze, outputs)
    assert executable["target"] == 0.95
    row = executable["by_quality"]["balanced"]
    assert row["interval_spans_target"] is True
    assert "gate" not in json.dumps(executable).lower()
    assert "passed" not in row and "pass" not in row


def test_markdown_report_states_the_interval(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _records(_public_ids())
    _with(outputs, "e01", "balanced", painted="fail")
    md = tmp_path / "r.md"
    proc = freeze.run(outputs, "--md", str(md))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = md.read_text(encoding="utf-8")
    assert "Executable-output rate" in text
    assert "8/9" in text and "Wilson 95%" in text
    assert "e01" in text


# --- rubric pass rate over executable hits (#273) ----------------------------

_FIVE = (
    "marks_present",
    "label_overlap",
    "axis_labels_present",
    "legend_presence",
    "bar_chart_y_axis_baseline",
)
_APPROPRIATE = "chart_type_appropriateness"
# A Flint Bar with no series channel: marks, overlap, axis labels, baseline.
_BAR_ITEMS = (
    "marks_present",
    "label_overlap",
    "axis_labels_present",
    "bar_chart_y_axis_baseline",
)


def _verdict(case_id: str, quality: str) -> dict[str, Any]:
    if case_id in _CUSTOM_IDS:
        items: tuple[str, ...] = _FIVE
        extra: dict[str, Any] = {"rail": "custom"}
    else:
        items = _BAR_ITEMS
        extra = {
            "rail": "flint",
            "chart_type": "Bar Chart",
            "encodings": {"x": "region", "y": "sales"},
        }
    return {
        "request_id": case_id,
        "quality": quality,
        "judge_model": "gemini-3.8-flash",
        "critic_model": "claude-sonnet-5-5",
        "png_sha256": "ab" * 32,
        "provenance": ["png", "instruction", "chart_type", "intent"],
        "verdicts": {name: "pass" for name in (*items, _APPROPRIATE)},
        **extra,
    }


def _judged() -> dict[str, Any]:
    outputs = _records(_public_ids())
    outputs["judge_verdicts"] = [
        _verdict(i, q) for i in _public_ids() for q in QUALITIES
    ]
    return outputs


def _verdict_of(outputs: dict[str, Any], case_id: str, quality: str) -> dict[str, Any]:
    for v in outputs["judge_verdicts"]:
        if v["request_id"] == case_id and v["quality"] == quality:
            found: dict[str, Any] = v
            return found
    raise AssertionError("no such verdict")


def _drop_verdicts(outputs: dict[str, Any], quality: str, *ids: str) -> None:
    outputs["judge_verdicts"] = [
        v
        for v in outputs["judge_verdicts"]
        if not (v["quality"] == quality and v["request_id"] in ids)
    ]


def _rubric(freeze: Freeze, outputs: dict[str, Any]) -> dict[str, Any]:
    rubric: dict[str, Any] = _report(freeze, outputs)["rubric"]
    return rubric


# --- delivery companion and the figure allow-list (#274) ---------------------


def _report(freeze: Freeze, outputs: dict[str, Any]) -> dict[str, Any]:
    out = freeze.repo / "r.json"
    proc = freeze.run(outputs, "--json", str(out))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    return report


def test_rubric_denominator_is_executable_hits_with_excluded_beside_it(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _judged()
    _with(outputs, "e01", "balanced", painted="fail")
    _with(outputs, "e04", "balanced", raster_nonblank=False)
    _drop_verdicts(outputs, "balanced", "e01", "e04")
    row = _rubric(freeze, outputs)["by_quality"]["balanced"]
    assert row["n"] == 7 and row["excluded"] == 2
    assert row["n"] + row["excluded"] == len(PUBLIC)
    assert row["k"] == 7 and row["rate"] == 1.0
    assert set(row["wilson_95"]) == {"lower", "upper"}


def test_one_failed_sent_item_fails_the_case(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _judged()
    _verdict_of(outputs, "e01", "fast")["verdicts"]["label_overlap"] = "fail"
    row = _rubric(freeze, outputs)["by_quality"]["fast"]
    assert row["k"] == 8 and row["n"] == 9
    assert row["failed"] == ["e01"]


def test_not_checked_on_a_sent_item_fails_and_is_counted_per_item(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _judged()
    _verdict_of(outputs, "e01", "fast")["verdicts"][_APPROPRIATE] = "not_checked"
    _verdict_of(outputs, "e02", "fast")["verdicts"][_APPROPRIATE] = "not_checked"
    _verdict_of(outputs, "e04", "fast")["verdicts"]["legend_presence"] = "not_checked"
    row = _rubric(freeze, outputs)["by_quality"]["fast"]
    assert row["k"] == 6
    counts = row["not_checked_by_item"]
    assert counts[_APPROPRIATE] == 2 and counts["legend_presence"] == 1
    assert counts["marks_present"] == 0


def test_inapplicable_flint_items_are_omitted_and_never_fail_a_case(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _judged()
    # A Bar with no series channel: legend_presence cannot apply on Flint,
    # so even a judge "fail" on it must not fail the case.
    _verdict_of(outputs, "e01", "fast")["verdicts"]["legend_presence"] = "fail"
    row = _rubric(freeze, outputs)["by_quality"]["fast"]
    assert row["k"] == 9
    assert row["not_checked_by_item"].get("legend_presence", 0) == 0


def test_a_sent_flint_item_with_no_verdict_fails_the_case(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _judged()
    del _verdict_of(outputs, "e01", "fast")["verdicts"]["axis_labels_present"]
    row = _rubric(freeze, outputs)["by_quality"]["fast"]
    assert row["failed"] == ["e01"]
    assert row["not_checked_by_item"]["axis_labels_present"] == 1


def test_appropriateness_is_always_sent_and_custom_sends_all_five(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _judged()
    del _verdict_of(outputs, "e01", "fast")["verdicts"][_APPROPRIATE]
    del _verdict_of(outputs, "e04", "fast")["verdicts"]["axis_labels_present"]
    row = _rubric(freeze, outputs)["by_quality"]["fast"]
    assert row["failed"] == ["e01", "e04"]


def test_a_non_cartesian_flint_chart_omits_axis_labels(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _judged()
    verdict = _verdict_of(outputs, "e01", "fast")
    verdict["chart_type"] = "Pie Chart"
    verdict["encodings"] = {"color": "region", "value": "sales"}
    verdict["verdicts"] = {
        "marks_present": "pass",
        "label_overlap": "pass",
        "legend_presence": "pass",
        _APPROPRIATE: "pass",
    }
    assert _rubric(freeze, outputs)["by_quality"]["fast"]["k"] == 9


def test_judge_verdict_for_a_case_with_no_executable_hit_is_refused(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _judged()
    _with(outputs, "e01", "fast", painted="fail")
    line = _refused(freeze.run(outputs), "JUDGE")
    assert "e01" in line and "executable" in line


def test_judge_verdict_without_a_png_is_refused(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _judged()
    del _verdict_of(outputs, "e02", "balanced")["png_sha256"]
    line = _refused(freeze.run(outputs), "JUDGE")
    assert "e02" in line and "PNG" in line


def test_executable_hit_with_no_verdict_is_refused(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _judged()
    for quality in QUALITIES:
        _drop_verdicts(outputs, quality, "e03")
    line = _refused(freeze.run(outputs), "JUDGE")
    assert "e03" in line and "no verdict" in line


def test_judge_in_the_critics_family_is_refused(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _judged()
    _verdict_of(outputs, "e01", "fast")["judge_model"] = "claude-haiku-4-5"
    line = _refused(freeze.run(outputs), "FAMILY")
    assert "e01" in line


def test_a_judge_from_another_family_than_the_critic_is_accepted(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _judged()
    for v in outputs["judge_verdicts"]:
        v["critic_model"] = "gpt-5"
    assert _rubric(freeze, outputs)["by_quality"]["fast"]["k"] == 9


def test_judge_provenance_with_review_report_critic_note_or_module_is_refused(
    tmp_path: Path,
) -> None:
    for banned in ("ReviewReport", "critic_note", "module"):
        (tmp_path / banned).mkdir()
        freeze = _make_freeze(tmp_path / banned)
        outputs = _judged()
        _verdict_of(outputs, "e05", "best")["provenance"].append(banned)
        line = _refused(freeze.run(outputs), "PROVENANCE")
        assert "e05" in line and banned in line


def test_rubric_is_absent_when_no_judge_verdicts_are_supplied(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    out = tmp_path / "r.json"
    assert freeze.run(_records(_public_ids()), "--json", str(out)).returncode == 0
    assert "rubric" not in json.loads(out.read_text(encoding="utf-8"))


def test_markdown_states_the_rubric_denominator_and_excluded(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _judged()
    _with(outputs, "e01", "balanced", painted="fail")
    _drop_verdicts(outputs, "balanced", "e01")
    md = tmp_path / "r.md"
    proc = freeze.run(outputs, "--md", str(md))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = md.read_text(encoding="utf-8")
    assert "Rubric pass rate" in text and "8/8" in text and "excluded" in text


def test_delivery_is_served_only_with_the_excluded_count_beside_it(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _records(_public_ids())
    _with(outputs, "e01", "balanced", error="PlanError: boom")  # not served
    _with(outputs, "e02", "balanced", painted="fail")  # served, not delivered
    _with(outputs, "e03", "balanced", compiled_row_count=9)  # served, row-drop
    report = _report(freeze, outputs)
    row = report["delivery"]["by_quality"]["balanced"]
    # Flint-rail cases: e01, e02, e03, e05, e07, e08. The custom rail has no
    # painted verdict and sits outside the Q1 predicate.
    assert (row["delivered"], row["served"]) == (3, 5)
    assert row["rate"] == 3 / 5
    assert row["excluded"] == 1
    assert row["excluded_ids"] == ["e01"]
    # beside, not instead: the executable rate is still over every request.
    assert report["executable"]["by_quality"]["balanced"]["n"] == len(PUBLIC)
    other = report["delivery"]["by_quality"]["fast"]
    assert (other["delivered"], other["served"], other["excluded"]) == (6, 6, 0)


def test_every_figure_states_its_definition_and_denominator_in_words(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    md = tmp_path / "r.md"
    assert freeze.run(_records(_public_ids()), "--md", str(md)).returncode == 0
    text = md.read_text(encoding="utf-8").lower()
    assert "every request" in text
    assert "served" in text and "excluded" in text
    assert "never multiplied" in text


def test_no_figure_outside_the_allow_list_in_any_output_form(
    tmp_path: Path,
) -> None:
    tool = _tool()
    freeze = _make_freeze(tmp_path)
    outputs = _records(_public_ids())
    _with(outputs, "e01", "balanced", error="PlanError: boom")
    out, md = freeze.repo / "r.json", tmp_path / "r.md"
    proc = freeze.run(outputs, "--json", str(out), "--md", str(md))
    forms = [
        out.read_text(encoding="utf-8"),
        md.read_text(encoding="utf-8"),
        proc.stdout,
    ]
    report = json.loads(forms[0])
    # No judge verdicts were supplied, so the rubric figure is not rendered.
    assert {k for k in report if k not in tool.REPORT_META} == {
        "executable",
        "delivery",
    }
    assert set(tool.FIGURES) == {"executable", "delivery", "rubric", "calibration"}
    for text in forms:
        lowered = text.lower()
        for banned in ("end-to-end", "combined", "overall"):
            assert banned not in lowered, banned


def test_report_model_refuses_an_unlisted_figure() -> None:
    tool = _tool()
    base: dict[str, Any] = {k: None for k in tool.REPORT_META}
    base.update({k: {} for k in tool.FIGURES})
    tool.enforce_allow_list(base)
    for extra in ("end_to_end", "rubric_every_request", "executable_x_delivery"):
        with pytest.raises(ValueError, match=extra):
            tool.enforce_allow_list({**base, extra: {"rate": 0.5}})


def test_a_rubric_rate_can_only_be_the_executable_hits_one() -> None:
    tool = _tool()
    assert "rubric" in tool.FIGURES
    tool.check_figure("rubric", "executable hits only, excluded count beside")
    for denominator in ("every request", "all 150", "served requests"):
        with pytest.raises(ValueError, match="executable hits"):
            tool.check_figure("rubric", denominator)
    with pytest.raises(ValueError, match="end_to_end"):
        tool.check_figure("end_to_end", "executable hits")


# --- cell-1 era reading and the designed-miss budget (#275) -------------------


def _era_report(
    freeze: Freeze, outputs: dict[str, Any], *args: str
) -> tuple[dict[str, Any], str]:
    out = freeze.repo / "r.json"
    md = freeze.repo / "r.md"
    proc = freeze.run(outputs, "--json", str(out), "--md", str(md), *args)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    return report, md.read_text(encoding="utf-8")


def test_shipped_seam_is_detected_and_cell1_is_an_expected_hit(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    report, _ = _era_report(freeze, _records(_public_ids()))
    cell1 = report["cell1"]
    assert cell1["era"] == "shipped"
    assert cell1["era_source"] == "detected"
    assert cell1["expected_executable"] is True
    assert cell1["case_ids"] == ["e04"]
    assert cell1["by_quality"]["balanced"]["unexpected"] == []


def test_shipped_cell1_raise_is_an_unexpected_miss(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _records(_public_ids())
    _with(outputs, "e04", "balanced", error="PlanError: raised")
    report, _ = _era_report(freeze, outputs)
    assert report["cell1"]["by_quality"]["balanced"]["unexpected"] == ["e04"]
    assert report["cell1"]["by_quality"]["fast"]["unexpected"] == []


def test_absent_override_reads_cell1_as_expected_misses_without_changing_n(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    raised = _records(_public_ids())
    for quality in QUALITIES:
        _with(raised, "e04", quality, error="PlanError: no custom rail")
    shipped, _ = _era_report(freeze, raised, "--cell1-era", "shipped")
    absent, _ = _era_report(freeze, raised, "--cell1-era", "absent")
    assert absent["cell1"]["era"] == "absent"
    assert absent["cell1"]["era_source"] == "override"
    assert absent["cell1"]["expected_executable"] is False
    assert absent["cell1"]["by_quality"]["balanced"]["unexpected"] == []
    assert shipped["cell1"]["by_quality"]["balanced"]["unexpected"] == ["e04"]
    # Scoring is the same either way: n and the executable counts do not move.
    assert absent["n"] == shipped["n"] == len(PUBLIC)
    assert absent["executable"] == shipped["executable"]
    assert absent["executable"]["by_quality"]["balanced"]["k"] == len(PUBLIC) - 1


def test_era_reading_never_edits_the_tag(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    before = freeze.prereg_path.read_bytes()
    report, _ = _era_report(freeze, _records(_public_ids()), "--cell1-era", "absent")
    assert freeze.prereg_path.read_bytes() == before
    assert report["cell1"]["expected_rail"] == "custom"
    assert report["prereg_sha256"] == hashlib.sha256(before).hexdigest()


def test_appropriateness_for_cell1_stays_on_the_intent_tag(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    for era in ("shipped", "absent"):
        report, _ = _era_report(freeze, _records(_public_ids()), "--cell1-era", era)
        assert report["cell1"]["appropriateness_basis"] == "intent_tag"


def test_bad_era_value_is_a_usage_error(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    proc = freeze.run(_records(_public_ids()), "--cell1-era", "sometime")
    assert proc.returncode == 2


def test_budget_states_six_authored_one_discretionary_then_two(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    report, md = _era_report(freeze, _records(_public_ids()))
    budget = report["designed_miss_budget"]
    assert budget["before_seam"] == {
        "cell1_raises": 4,
        "row_drops": 2,
        "authored": 6,
        "discretionary": 1,
    }
    assert budget["after_seam"] == {"row_drops": 2, "authored": 2}
    assert "six authored misses" in md
    assert "four cell-1 raises and two row-drops" in md
    assert "one discretionary" in md
    assert "two row-drops" in md


def test_budget_ceilings_are_computed_from_n(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    report, _ = _era_report(freeze, _records(_public_ids()))
    ceilings = report["designed_miss_budget"]["ceilings"]
    n = len(PUBLIC)
    assert ceilings["before_seam"]["authored"] == (n - 6) / n
    assert ceilings["before_seam"]["with_discretionary"] == (n - 7) / n
    assert ceilings["after_seam"]["authored"] == (n - 2) / n
    assert report["designed_miss_budget"]["era"] == "shipped"


def test_markdown_names_the_era_and_how_to_read_it(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    _, shipped = _era_report(freeze, _records(_public_ids()))
    _, absent = _era_report(freeze, _records(_public_ids()), "--cell1-era", "absent")
    assert "seam shipped" in shipped
    assert "seam absent" in absent
    assert "expected miss" in absent


# --- human calibration of the judge (#279) ------------------------------------


def _labelled(*, disagree: dict[str, str] | None = None) -> dict[str, Any]:
    """A judged balanced run plus one human label per executable hit.

    ``disagree`` maps a case id to the item the rater marks ``fail`` where the
    judge said ``pass``.
    """
    outputs = _judged()
    labels = []
    for case_id in _public_ids():
        verdict = copy.deepcopy(_verdict_of(outputs, case_id, "balanced"))
        for key in ("judge_model", "critic_model", "png_sha256", "provenance"):
            verdict.pop(key)
        if disagree and case_id in disagree:
            verdict["verdicts"][disagree[case_id]] = "fail"
        labels.append(verdict)
    outputs["human_labels"] = labels
    return outputs


def _calibration(freeze: Freeze, outputs: dict[str, Any]) -> dict[str, Any]:
    section: dict[str, Any] = _report(freeze, outputs)["calibration"]
    return section


def test_sample_is_first_thirty_hits_in_permutation_order() -> None:
    tool = _tool()
    permutation = [f"c{i:02d}" for i in range(40)]
    hits = {f"c{i:02d}" for i in range(40) if i % 4 != 1}
    sample = tool.calibration_sample(permutation, hits)
    assert len(sample) == 30
    assert sample == [c for c in permutation if c in hits][:30]
    assert tool.calibration_sample(permutation, {"c07", "c03"}) == ["c03", "c07"]


def test_sample_skips_misses_and_follows_the_permutation(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _labelled()
    _with(outputs, "e02", "balanced", painted="fail")
    _drop_verdicts(outputs, "balanced", "e02")
    outputs["human_labels"] = [
        label for label in outputs["human_labels"] if label["request_id"] != "e02"
    ]
    section = _calibration(freeze, outputs)
    assert section["quality"] == "balanced"
    assert section["sample"] == [i for i in _public_ids() if i != "e02"]
    assert section["exact_match"]["n"] == 8


def test_agreement_is_per_item_exact_match_with_a_disagreement_count(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    section = _calibration(
        freeze,
        _labelled(disagree={"e01": "label_overlap", "e04": "legend_presence"}),
    )
    assert section["exact_match"] == {"k": 7, "n": 9, "rate": 7 / 9}
    assert section["disagreement_count"] == 2
    by_id = {row["request_id"]: row for row in section["cases"]}
    assert by_id["e01"]["match"] is False
    assert by_id["e01"]["disagreements"] == ["label_overlap"]
    assert by_id["e02"]["match"] is True
    assert section["by_item"]["label_overlap"] == {"agree": 8, "n": 9}
    assert section["by_item"]["legend_presence"] == {"agree": 2, "n": 3}


def test_labels_never_move_the_rubric_or_executable_figures(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    plain = _report(freeze, _judged())
    labelled = _report(freeze, _labelled(disagree={"e01": "label_overlap"}))
    assert labelled["rubric"] == plain["rubric"]
    assert labelled["executable"] == plain["executable"]
    assert labelled["delivery"] == plain["delivery"]
    assert "calibration" not in plain


def test_a_label_outside_the_sample_is_refused(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _labelled()
    _with(outputs, "e02", "balanced", painted="fail")
    _drop_verdicts(outputs, "balanced", "e02")
    line = _refused(freeze.run(outputs), "CALIBRATION")
    assert "e02" in line


def test_a_missing_label_in_the_sample_is_refused(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _labelled()
    outputs["human_labels"] = outputs["human_labels"][:-1]
    line = _refused(freeze.run(outputs), "CALIBRATION")
    assert "e09" in line


def test_labels_without_judge_verdicts_are_refused(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _labelled()
    del outputs["judge_verdicts"]
    _refused(freeze.run(outputs), "CALIBRATION")


def test_collapse_threshold_is_below_eighty_percent_exact_match(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    one = {"e01": "label_overlap"}
    two = {**one, "e02": "label_overlap"}
    three = {**two, "e03": "label_overlap"}
    assert _calibration(freeze, _labelled(disagree=one))["collapsed"] is False
    assert _calibration(freeze, _labelled(disagree=two))["collapsed"] is True  # 7/9
    assert _calibration(freeze, _labelled(disagree=three))["collapsed"] is True


def test_collapse_appends_a_dated_note_distinct_from_the_named_review(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    notes = tmp_path / "report-notes.md"
    notes.write_text("# Notes\n\n## Named review (Decision 12) - 2026-01-01\n")
    three = {i: "label_overlap" for i in ("e01", "e02", "e03")}
    args = ("--notes", str(notes), "--date", "2026-10-11")
    proc = freeze.run(_labelled(disagree=three), *args)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = notes.read_text(encoding="utf-8")
    assert "## Calibration collapse (ADR-0029 Decision 11) - 2026-10-11" in text
    assert "6/9" in text and "85%" in text and "not rewritten" in text
    assert text.startswith("# Notes\n\n## Named review (Decision 12) - 2026-01-01\n")
    # scoring the same run again on the same day does not duplicate the entry
    freeze.run(_labelled(disagree=three), *args)
    assert notes.read_text(encoding="utf-8").count("Calibration collapse") == 1


def test_no_collapse_writes_no_note(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    notes = tmp_path / "report-notes.md"
    proc = freeze.run(_labelled(), "--notes", str(notes), "--date", "2026-10-11")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not notes.exists()


def test_markdown_publishes_the_calibration_beside_the_rubric(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    md = tmp_path / "r.md"
    proc = freeze.run(_labelled(disagree={"e01": "label_overlap"}), "--md", str(md))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = md.read_text(encoding="utf-8")
    assert "## Human calibration" in text
    assert "8/9" in text and "1 disagreement" in text
    assert "never changes the rubric pass rate" in text


def test_calibration_is_an_allow_listed_figure_over_its_own_sample() -> None:
    tool = _tool()
    assert "calibration" in tool.FIGURES
    tool.check_figure("calibration", "the human-calibration sample")
    with pytest.raises(ValueError, match="calibration sample"):
        tool.check_figure("calibration", "every request")


# --- run modes and the publish write (#276) ----------------------------------


def _eval_files(repo: Path) -> set[str]:
    """Every file under eval/ except the freeze itself and the datasets."""
    root = repo / "eval"
    return {
        p.relative_to(repo).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.relative_to(root).parts[0] != "data"
    } - {"eval/pre-registration.json"}


def test_publish_writes_the_latest_table_and_a_dated_snapshot_only(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    proc = freeze.run(_records(_public_ids()), "--date", "2026-10-11", mode="publish")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _eval_files(tmp_path) == {
        "eval/report.json",
        "eval/report.md",
        "eval/outputs.json",
        "eval/runs/2026-10-11/report.json",
        "eval/runs/2026-10-11/report.md",
        "eval/runs/2026-10-11/outputs.json",
    }
    latest = json.loads((tmp_path / "eval/report.json").read_text(encoding="utf-8"))
    dated = json.loads(
        (tmp_path / "eval/runs/2026-10-11/report.json").read_text(encoding="utf-8")
    )
    assert latest == dated
    assert latest["mode"] == "publish"


def test_publish_refuses_caller_chosen_report_paths(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    proc = freeze.run(
        _records(_public_ids()), "--json", str(tmp_path / "x.json"), mode="publish"
    )
    assert proc.returncode == 2
    assert not (tmp_path / "x.json").exists()
    assert _eval_files(tmp_path) == set()


def test_a_refused_publish_writes_nothing(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _records(_public_ids())
    outputs["records"].pop()
    assert freeze.run(outputs, mode="publish").returncode == 1
    assert not (tmp_path / "eval").exists() or _eval_files(tmp_path) == set()


def test_publish_requires_all_three_qualities(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    proc = freeze.run(_records(_public_ids(), ("balanced",)), mode="publish")
    line = _refused(proc, "IDS")
    assert "fast" in line
    assert "best" in line
    assert _eval_files(tmp_path) == set()


def test_nightly_writes_none_of_the_committed_files(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    proc = freeze.run(_records(_public_ids()), mode="nightly")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _eval_files(tmp_path) == set()
    for committed in (
        "eval/report.json",
        "eval/report.md",
        "eval/outputs.json",
        "eval/runs/2026-10-11/report.md",
        "eval/holdout/report.md",
    ):
        bad = freeze.run(_records(_public_ids()), "--json", str(tmp_path / committed))
        assert bad.returncode == 1, committed
        assert "WRITE" in bad.stdout
    assert _eval_files(tmp_path) == set()


def test_smoke_refuses_committed_paths_too(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    proc = freeze.run(
        _records(SMOKE, ("balanced",)),
        "--json",
        str(tmp_path / "eval/report.json"),
        mode="smoke",
    )
    assert proc.returncode == 1
    assert "WRITE" in proc.stdout


def test_holdout_writes_only_under_the_holdout_report_path(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    proc = freeze.run(_records(HOLDOUT, ("balanced",)), mode="holdout")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    files = _eval_files(tmp_path)
    assert "eval/holdout/report.md" in files
    assert all(f.startswith("eval/holdout/") for f in files)
    bad = freeze.run(
        _records(HOLDOUT, ("balanced",)),
        "--md",
        str(tmp_path / "eval/report.md"),
        mode="holdout",
    )
    assert bad.returncode == 1
    assert "WRITE" in bad.stdout
    assert "eval/report.md" not in _eval_files(tmp_path)


def test_smoke_has_no_judge_and_no_rubric_number(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _records(SMOKE, ("balanced",))
    outputs["judge_verdicts"] = []
    _refused(freeze.run(outputs, mode="smoke"), "JUDGE")
    out = tmp_path / "s.json"
    ok = freeze.run(_records(SMOKE, ("balanced",)), "--json", str(out), mode="smoke")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "rubric" not in json.loads(out.read_text(encoding="utf-8"))


def test_smoke_list_differing_from_the_frozen_thirty_is_refused(
    tmp_path: Path,
) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _records(["e01", "e04", "e09"], ("balanced",))
    line = _refused(freeze.run(outputs, mode="smoke"), "IDS")
    assert "missing e08" in line
    assert "extra e09" in line


def test_reference_lines_come_from_the_balanced_run_only(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _judged()
    out = tmp_path / "r.json"
    proc = freeze.run(outputs, "--json", str(out))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(out.read_text(encoding="utf-8"))
    lines = report["reference_lines"]
    assert lines["basis"] == "balanced"
    assert lines["executable"]["target"] == 0.95
    assert lines["rubric"]["target"] == 0.85
    for q in ("fast", "best"):
        assert "interval_spans_target" not in report["executable"]["by_quality"][q]
        assert "interval_spans_target" not in report["rubric"]["by_quality"][q]
    assert "interval_spans_target" in report["rubric"]["by_quality"]["balanced"]


@pytest.mark.parametrize("mode", ["nightly", "publish"])
def test_two_create_chart_calls_for_one_case_and_quality_is_refused(
    tmp_path: Path, mode: str
) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _records(_public_ids())
    _with(outputs, "e02", "best", create_chart_calls=2)
    line = _refused(freeze.run(outputs, mode=mode), "CALLS")
    assert "e02" in line
    assert "best" in line


def test_repeats_are_refused_in_smoke_too(tmp_path: Path) -> None:
    freeze = _make_freeze(tmp_path)
    outputs = _records(SMOKE, ("balanced",))
    outputs["records"].append(dict(outputs["records"][0]))
    _refused(freeze.run(outputs, mode="smoke"), "REPEATS")
