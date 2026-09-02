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

_REPO = Path(__file__).resolve().parents[1]
_SCORE = _REPO / "tools" / "score_corpus.py"
_PREREG = _REPO / "corpus" / "pre-registration.json"
_VOCAB = _REPO / "src" / "chartagent" / "frame" / "vocab.json"

_CELL1 = ("r31", "r32", "r33", "r34")
_TRIP_EXTRA_MISSES = (
    "r01",
    "r02",
    "r03",
    "r04",
    "r05",
    "r06",
    "r07",
    "r08",
    "r09",
    "r10",
)
_CLEAR_EXTRA_MISSES = ("r01", "r02", "r03", "r04", "r05", "r06", "r07", "r08", "r09")
_BUCKET2_SENTENCE = (
    "Bucket 2 reads zero by construction and the menu lever is fed by "
    "the raw_sql_used rate, not by the histogram."
)


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("score_corpus", _SCORE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prereg() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_PREREG.read_text(encoding="utf-8")))


def _request_ids() -> list[str]:
    return [item["id"] for item in _prereg()["requests"]]


def _cell2_ids() -> set[str]:
    return {item["id"] for item in _prereg()["requests"] if item["cell"] == 2}


def _run_record(
    request_id: str,
    run: int,
    *,
    rail: str,
    raw_sql_used: bool,
    emitted_compilable: bool,
    painted: bool,
    compiled_row_count: int | None,
    bound_row_count: int | None,
    escape_reason: object | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "request_id": request_id,
        "run": run,
        "rail": rail,
        "raw_sql_used": raw_sql_used,
        "emitted_compilable": emitted_compilable,
        "painted": painted,
        "compiled_row_count": compiled_row_count,
        "bound_row_count": bound_row_count,
    }
    if extra:
        record.update(extra)
    if escape_reason is not None:
        record["escape_reason"] = escape_reason
    return record


def _hit_run(request_id: str, run: int, *, raw_sql: bool) -> dict[str, Any]:
    return _run_record(
        request_id,
        run,
        rail="deterministic",
        raw_sql_used=raw_sql,
        emitted_compilable=True,
        painted=True,
        compiled_row_count=10,
        bound_row_count=10,
    )


def _miss_run(
    request_id: str,
    run: int,
    *,
    rail: str = "nothing_fits",
    escape_reason: object | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reason: object | None = escape_reason
    if reason is None and extra is None:
        reason = {"bucket": 1}
    return _run_record(
        request_id,
        run,
        rail=rail,
        raw_sql_used=False,
        emitted_compilable=False,
        painted=False,
        compiled_row_count=None,
        bound_row_count=None,
        escape_reason=reason,
        extra=extra,
    )


def _outputs(
    *,
    miss_ids: set[str],
    two_one_rail: str | None = None,
    two_one_raw_sql: str | None = None,
    two_one_delivery: str | None = None,
    surprise_hit: str | None = None,
    miss_reasons: dict[str, object] | None = None,
    miss_extras: dict[str, dict[str, Any]] | None = None,
    undelivered: set[str] | None = None,
) -> dict[str, Any]:
    cell2 = _cell2_ids()
    runs: list[dict[str, Any]] = []
    undelivered = undelivered or set()
    miss_reasons = miss_reasons or {}
    miss_extras = miss_extras or {}
    for request_id in _request_ids():
        raw_sql = request_id in cell2
        is_miss = request_id in miss_ids and request_id != surprise_hit
        for run in (1, 2, 3):
            if is_miss:
                extra = dict(miss_extras.get(request_id, {}))
                reason = miss_reasons.get(request_id)
                if extra and "escape_reason" not in extra and reason is None:
                    extra.setdefault("recipe", {"escape_reason": {"bucket": 1}})
                runs.append(
                    _miss_run(
                        request_id,
                        run,
                        escape_reason=reason,
                        extra=extra or None,
                    )
                )
                continue
            record = _hit_run(request_id, run, raw_sql=raw_sql)
            if two_one_rail == request_id and run == 3 and request_id not in miss_ids:
                record = _miss_run(
                    request_id,
                    run,
                    rail="planner_failure",
                    escape_reason={"bucket": 3},
                )
            if two_one_raw_sql == request_id and run == 2:
                record = {**record, "raw_sql_used": not record["raw_sql_used"]}
            if two_one_delivery == request_id and run == 3:
                record = {
                    **record,
                    "painted": False,
                    "compiled_row_count": 4,
                    "bound_row_count": 10,
                }
            if request_id in undelivered:
                record = {
                    **record,
                    "painted": True,
                    "compiled_row_count": 4,
                    "bound_row_count": 10,
                }
            runs.append(record)
    return {"decoding": {"temperature": 0}, "runs": runs}


def _write_outputs(doc: dict[str, Any], tmp_path: Path) -> Path:
    path = tmp_path / "outputs.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _run(
    outputs: Path,
    tmp_path: Path,
    *,
    prereg: Path | None = None,
    vocab: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    out_json = tmp_path / "score.json"
    out_md = tmp_path / "score.md"
    cmd = [
        sys.executable,
        str(_SCORE),
        str(outputs),
        "--json",
        str(out_json),
        "--md",
        str(out_md),
        "--date",
        "2026-08-30",
    ]
    if prereg is not None:
        cmd.extend(["--prereg", str(prereg)])
    if vocab is not None:
        cmd.extend(["--vocab", str(vocab)])
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def _report(tmp_path: Path) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((tmp_path / "score.json").read_text(encoding="utf-8")),
    )


def _markdown(tmp_path: Path) -> str:
    return (tmp_path / "score.md").read_text(encoding="utf-8")


def test_harness_is_not_on_the_public_surface() -> None:
    assert "score_corpus" not in chartagent.__all__
    with pytest.raises(ModuleNotFoundError):
        __import__("chartagent.score_corpus")


def test_crlf_checkout_still_matches_the_tag(tmp_path: Path) -> None:
    lf = _PREREG.read_bytes().replace(b"\r\n", b"\n")
    crlf = lf.replace(b"\n", b"\r\n")
    assert crlf != lf
    path = tmp_path / "pre-registration.json"
    path.write_bytes(crlf)
    outputs = _write_outputs(
        _outputs(miss_ids=set(_CELL1) | set(_TRIP_EXTRA_MISSES)),
        tmp_path,
    )
    result = _run(outputs, tmp_path, prereg=path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_mismatched_hash_exits_nonzero(tmp_path: Path) -> None:
    blob = bytearray(_PREREG.read_bytes())
    blob[0] ^= 0x01
    mutated = tmp_path / "pre-registration.json"
    mutated.write_bytes(blob)
    outputs = _write_outputs(
        _outputs(miss_ids=set(_CELL1) | set(_TRIP_EXTRA_MISSES)),
        tmp_path,
    )
    result = _run(outputs, tmp_path, prereg=mutated)
    assert result.returncode != 0
    assert "HASH" in result.stdout or "HASH" in result.stderr


def test_wilson_36_of_50_trips(tmp_path: Path) -> None:
    outputs = _write_outputs(
        _outputs(miss_ids=set(_CELL1) | set(_TRIP_EXTRA_MISSES)),
        tmp_path,
    )
    result = _run(outputs, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = _report(tmp_path)
    share = report["rail_share"]
    assert share["k"] == 36
    assert share["n"] == 50
    assert share["gate_tripped"] is True
    assert share["wilson_95"]["lower"] < 0.60
    assert round(share["wilson_95"]["lower"], 4) == 0.5833
    assert "end_to_end" not in report
    assert "combined" not in report
    assert "goal_3" not in report


def test_wilson_37_of_50_does_not_trip(tmp_path: Path) -> None:
    outputs = _write_outputs(
        _outputs(miss_ids=set(_CELL1) | set(_CLEAR_EXTRA_MISSES)),
        tmp_path,
    )
    result = _run(outputs, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    share = _report(tmp_path)["rail_share"]
    assert share["k"] == 37
    assert share["n"] == 50
    assert share["gate_tripped"] is False
    assert share["wilson_95"]["lower"] >= 0.60
    assert round(share["wilson_95"]["lower"], 4) == 0.6045


def test_majority_is_independent_and_two_one_is_published(tmp_path: Path) -> None:
    outputs = _write_outputs(
        _outputs(
            miss_ids=set(_CELL1) | set(_TRIP_EXTRA_MISSES),
            two_one_rail="r11",
            two_one_raw_sql="r23",
            two_one_delivery="r27",
        ),
        tmp_path,
    )
    result = _run(outputs, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = _report(tmp_path)
    by_id = {row["id"]: row for row in report["requests"]}
    assert by_id["r11"]["rail_hit"] is True
    assert by_id["r11"]["rail_votes"] == [True, True, False]
    assert by_id["r23"]["raw_sql_used"] is True
    assert by_id["r23"]["raw_sql_votes"] == [True, False, True]
    assert by_id["r27"]["delivered"] is True
    assert by_id["r27"]["delivery_votes"] == [True, True, False]
    assert by_id["r11"]["delivery_votes"] == [True, True, False]
    counts = report["two_one_counts"]
    assert counts["rail"] == 1
    assert counts["raw_sql_used"] == 1
    # r11's 2–1 rail miss on run 3 is also a 2–1 delivery vote.
    assert counts["delivery"] == 2


def test_rail_miss_is_outside_delivery_denominator(tmp_path: Path) -> None:
    miss_ids = set(_CELL1) | set(_TRIP_EXTRA_MISSES)
    outputs = _write_outputs(
        _outputs(miss_ids=miss_ids, undelivered={"r27"}),
        tmp_path,
    )
    result = _run(outputs, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = _report(tmp_path)
    delivery = report["delivery_rate"]
    assert delivery["n"] == 36
    assert delivery["k"] == 35
    assert delivery["excluded"] == 14
    denom_ids = {
        row["id"] for row in report["requests"] if row["in_delivery_denominator"]
    }
    assert denom_ids.isdisjoint(miss_ids)
    raw = report["raw_sql_used"]
    assert raw["pooled"]["n"] == 36
    assert raw["pooled"]["k"] == 10
    assert raw["common_path"]["n"] == 20
    assert raw["common_path"]["k"] == 4
    assert raw["adversarial"]["n"] == 16
    assert raw["adversarial"]["k"] == 6


def test_report_renders_per_cell_counts_and_stratum_intervals(
    tmp_path: Path,
) -> None:
    outputs = _write_outputs(
        _outputs(miss_ids=set(_CELL1) | set(_TRIP_EXTRA_MISSES)),
        tmp_path,
    )
    result = _run(outputs, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = _report(tmp_path)
    cells = report["cells"]
    assert cells["0"] == {"k": 12, "n": 22}
    assert cells["1"] == {"k": 0, "n": 4}
    assert cells["2"] == {"k": 10, "n": 10}
    assert cells["3"] == {"k": 6, "n": 6}
    assert cells["4"] == {"k": 8, "n": 8}
    for cell in cells.values():
        assert "rate" not in cell
        assert "wilson_95" not in cell
        assert "%" not in json.dumps(cell)
    strata = report["strata"]
    assert strata["common_path"]["k"] == 20
    assert strata["common_path"]["n"] == 30
    assert "wilson_95" in strata["common_path"]
    assert strata["adversarial"]["k"] == 16
    assert strata["adversarial"]["n"] == 20
    assert "wilson_95" in strata["adversarial"]
    md = _markdown(tmp_path)
    assert "0 of 4" in md
    assert "12 of 22" in md
    assert _BUCKET2_SENTENCE in md
    assert "authoring pin" in md.lower() or "Authoring pin" in md
    assert "0.5.1" in md
    assert "34ef451" in md
    assert report["authoring_pin"]["flint_version"] == "0.5.1"
    assert report["authoring_pin"]["fixture_commit"] == "34ef451"
    assert report["scoring_pin"]["flint_version"] == "0.5.1"
    assert report["backend_forced"]["neither_vegalite_nor_plotly"] == 9
    assert report["backend_forced"]["exactly_one_backend"] == 8
    assert "Poisson-binomial" in md or "poisson-binomial" in md.lower()


def test_cell2_sql_refused_at_scoring_is_a_bucket_2_miss(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from chartagent.errors import RawSqlRejectedError

    module = _tool()
    original = module.validate_raw_sql

    def refuse_r23(connection: object, sql: str) -> None:
        if "UNPIVOT (faculty_count FOR rank IN" in sql:
            raise RawSqlRejectedError(
                "raw_sql refused",
                reason="multi_statement",
            )
        original(connection, sql)

    monkeypatch.setattr(module, "validate_raw_sql", refuse_r23)
    outputs = _write_outputs(
        _outputs(miss_ids=set(_CELL1) | set(_TRIP_EXTRA_MISSES)),
        tmp_path,
    )
    out_json = tmp_path / "score.json"
    out_md = tmp_path / "score.md"
    code = module.main(
        [
            str(outputs),
            "--json",
            str(out_json),
            "--md",
            str(out_md),
            "--date",
            "2026-08-30",
        ]
    )
    assert code == 0
    report = json.loads(out_json.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in report["requests"]}
    assert by_id["r23"]["rail_hit"] is False
    assert by_id["r23"]["reported_bucket"] == 2
    assert report["escape_reason_histogram"]["2"] == 1
    md = out_md.read_text(encoding="utf-8")
    assert _BUCKET2_SENTENCE in md
    assert "genuine bucket-2 miss" in md.lower() or (
        "genuine bucket 2 miss" in md.lower()
    )


def test_expected_versus_reported_includes_a_surprise_cell1_hit(
    tmp_path: Path,
) -> None:
    outputs = _write_outputs(
        _outputs(
            miss_ids=set(_CELL1) | set(_TRIP_EXTRA_MISSES),
            surprise_hit="r31",
            miss_reasons={"r32": {"bucket": 3, "note": "mislabeled"}},
        ),
        tmp_path,
    )
    result = _run(outputs, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = _report(tmp_path)
    by_id = {row["id"]: row for row in report["requests"]}
    assert by_id["r31"]["expected_outcome"] == "miss"
    assert by_id["r31"]["reported_outcome"] == "hit"
    assert by_id["r31"]["surprise_hit"] is True
    confusion = report["bucket_confusion"]
    assert confusion["1"]["3"] == 1
    md = _markdown(tmp_path)
    assert "surprise" in md.lower()
    assert "bucket confusion" in md.lower()
    assert "r31: expected miss, reported hit" in md
    assert "r01: expected hit, reported miss" in md


def test_pin_bump_moves_cell1_when_union_gains_venn(tmp_path: Path) -> None:
    vocab = json.loads(_VOCAB.read_text(encoding="utf-8"))
    vocab["backends"]["vegalite"]["Venn"] = {
        "channels": ["x"],
        "properties": [],
    }
    vocab_path = tmp_path / "vocab.json"
    vocab_path.write_text(json.dumps(vocab), encoding="utf-8")
    before = hashlib.sha256(_PREREG.read_bytes()).hexdigest()
    outputs = _write_outputs(
        _outputs(miss_ids=set(_CELL1) | set(_TRIP_EXTRA_MISSES)),
        tmp_path,
    )
    result = _run(outputs, tmp_path, vocab=vocab_path)
    assert result.returncode == 0, result.stdout + result.stderr
    after = hashlib.sha256(_PREREG.read_bytes()).hexdigest()
    assert after == before
    report = _report(tmp_path)
    moved = {row["id"]: row for row in report["cell_moves"]}
    assert moved["r31"]["authoring_cell"] == 1
    assert moved["r31"]["scoring_cell"] != 1
    assert "Venn" in moved["r31"]["intersected"]
    assert moved["r32"]["authoring_cell"] == 1
    assert "r33" not in moved
    assert "r34" not in moved
    md = _markdown(tmp_path)
    assert "r31" in md
    assert "moved" in md.lower()


def test_narrowing_bump_reports_frames_the_facade_rejects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from chartagent.errors import ChartAgentError

    module = _tool()
    original = module.InputFrame.model_validate

    def reject_bullet(data: object) -> object:
        frame = data if isinstance(data, dict) else {}
        spec = frame.get("chart_spec")
        chart = spec.get("chartType") if isinstance(spec, dict) else None
        if chart == "Bullet Chart":
            raise ChartAgentError("scoring pin no longer admits Bullet Chart")
        return original(data)

    monkeypatch.setattr(module.InputFrame, "model_validate", reject_bullet)
    outputs = _write_outputs(
        _outputs(miss_ids=set(_CELL1) | set(_TRIP_EXTRA_MISSES)),
        tmp_path,
    )
    out_json = tmp_path / "score.json"
    out_md = tmp_path / "score.md"
    code = module.main(
        [
            str(outputs),
            "--json",
            str(out_json),
            "--md",
            str(out_md),
            "--date",
            "2026-08-30",
        ]
    )
    assert code == 0
    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert "r22" in report["facade_invalid_ids"]
    by_id = {row["id"]: row for row in report["requests"]}
    assert by_id["r22"]["facade_invalid"] is True
    assert by_id["r22"]["expected_outcome"] == "miss"
    md = out_md.read_text(encoding="utf-8")
    assert "r22" in md
    assert "façade" in md.lower() or "facade" in md.lower()


def test_escape_reason_is_read_from_any_home(tmp_path: Path) -> None:
    outputs = _write_outputs(
        _outputs(
            miss_ids=set(_CELL1) | set(_TRIP_EXTRA_MISSES),
            miss_reasons={
                "r31": None,
                "r32": None,
                "r33": {"bucket": 1},
                "r34": None,
            },
            miss_extras={
                "r31": {"recipe": {"escape_reason": {"bucket": 1}}},
                "r32": {"x_chartagent": {"escape": {"bucket": 1}}},
                "r34": {"reason": 1},
            },
        ),
        tmp_path,
    )
    result = _run(outputs, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    hist = _report(tmp_path)["escape_reason_histogram"]
    assert hist["1"] == 14
    assert hist["2"] == 0
    assert hist["3"] == 0
    assert hist["4"] == 0


def test_inflated_temperature_is_refused(tmp_path: Path) -> None:
    doc = _outputs(miss_ids=set(_CELL1) | set(_TRIP_EXTRA_MISSES))
    doc["decoding"] = {"temperature": 0.7}
    outputs = _write_outputs(doc, tmp_path)
    result = _run(outputs, tmp_path)
    assert result.returncode != 0
    assert "DECODING" in result.stdout or "DECODING" in result.stderr


def test_planner_failure_miss_has_no_bucket_and_is_counted_separately(
    tmp_path: Path,
) -> None:
    outputs = _write_outputs(
        _outputs(
            miss_ids=set(_CELL1) | set(_TRIP_EXTRA_MISSES),
            miss_reasons={"r01": {}},
            miss_extras={"r01": {"miss_kind": "planner_failure"}},
        ),
        tmp_path,
    )
    result = _run(outputs, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = _report(tmp_path)
    by_id = {row["id"]: row for row in report["requests"]}
    assert by_id["r01"]["reported_bucket"] is None
    assert by_id["r01"]["reported_miss_kind"] == "planner_failure"
    assert by_id["r01"]["rail_hit"] is False
    assert report["planner_failure_ids"] == ["r01"]
    assert report["planner_failure_misses"] == 1
    assert report["unattributed_misses"] == 0
    assert report["unattributed_ids"] == []
    hist = report["escape_reason_histogram"]
    assert hist["1"] == 13
    assert sum(hist.values()) == 13
    recon = report["reconciliation"]
    assert recon["hits"] == 36
    assert recon["buckets"] == 13
    assert recon["planner_failure"] == 1
    assert recon["unattributed"] == 0
    assert recon["n"] == 50
    total = (
        recon["hits"]
        + recon["buckets"]
        + recon["planner_failure"]
        + recon["unattributed"]
    )
    assert total == recon["n"]
    assert recon["total"] == total
    md = _markdown(tmp_path)
    assert "planner-failure" in md.lower()
    assert "unattributed" in md.lower()


def test_unanswerable_instruction_miss_has_no_bucket_and_is_counted_separately(
    tmp_path: Path,
) -> None:
    outputs = _write_outputs(
        _outputs(
            miss_ids=set(_CELL1) | set(_TRIP_EXTRA_MISSES),
            miss_reasons={"r01": {}},
            miss_extras={"r01": {"miss_kind": "unanswerable_instruction"}},
        ),
        tmp_path,
    )
    result = _run(outputs, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = _report(tmp_path)
    by_id = {row["id"]: row for row in report["requests"]}
    assert by_id["r01"]["reported_bucket"] is None
    assert by_id["r01"]["reported_miss_kind"] == "unanswerable_instruction"
    assert by_id["r01"]["rail_hit"] is False
    assert report["unanswerable_instruction_ids"] == ["r01"]
    assert report["unanswerable_instruction_misses"] == 1
    assert report["planner_failure_misses"] == 0
    assert report["unattributed_misses"] == 0
    assert report["unattributed_ids"] == []
    hist = report["escape_reason_histogram"]
    assert hist["1"] == 13
    assert sum(hist.values()) == 13
    recon = report["reconciliation"]
    assert recon["hits"] == 36
    assert recon["buckets"] == 13
    assert recon["planner_failure"] == 0
    assert recon["unanswerable_instruction"] == 1
    assert recon["unattributed"] == 0
    assert recon["n"] == 50
    total = (
        recon["hits"]
        + recon["buckets"]
        + recon["planner_failure"]
        + recon["unanswerable_instruction"]
        + recon["unattributed"]
    )
    assert total == recon["n"]
    assert recon["total"] == total
    md = _markdown(tmp_path)
    assert "unanswerable" in md.lower()
    assert "unattributed" in md.lower()


def test_unattributed_row_is_flagged_in_the_score(tmp_path: Path) -> None:
    module = _tool()
    prereg = _prereg()
    vocab = json.loads(_VOCAB.read_text(encoding="utf-8"))
    outputs = _outputs(
        miss_ids=set(_CELL1) | set(_TRIP_EXTRA_MISSES),
        miss_reasons={"r01": {}},
    )
    report = module.score(
        prereg,
        outputs,
        vocab,
        scored_at="2026-08-30",
        prereg_sha256="ignored",
    )
    by_id = {row["id"]: row for row in report["requests"]}
    assert by_id["r01"]["reported_bucket"] is None
    assert by_id["r01"]["reported_miss_kind"] is None
    assert report["unattributed_ids"] == ["r01"]
    assert report["unattributed_misses"] == 1
    assert report["planner_failure_misses"] == 0
    recon = report["reconciliation"]
    total = (
        recon["hits"]
        + recon["buckets"]
        + recon["planner_failure"]
        + recon["unattributed"]
    )
    assert total == recon["n"]
    assert recon["total"] == total


def test_unattributed_miss_is_a_named_check_failure_at_the_cli(tmp_path: Path) -> None:
    outputs = _write_outputs(
        _outputs(
            miss_ids=set(_CELL1) | set(_TRIP_EXTRA_MISSES),
            miss_reasons={"r01": {}},
        ),
        tmp_path,
    )
    result = _run(outputs, tmp_path)
    assert result.returncode == 1
    assert "UNATTRIBUTED" in result.stdout or "UNATTRIBUTED" in result.stderr
    assert "r01" in result.stdout or "r01" in result.stderr
    assert not (tmp_path / "score.json").exists()
    assert not (tmp_path / "score.md").exists()


def test_call_cost_reports_the_floor_and_worst_case(tmp_path: Path) -> None:
    outputs = _write_outputs(
        _outputs(miss_ids=set(_CELL1) | set(_TRIP_EXTRA_MISSES)),
        tmp_path,
    )
    result = _run(outputs, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = _report(tmp_path)
    cost = report["call_cost"]
    assert cost["runs"] == 150
    assert cost["floor"] == 300
    assert cost["worst_case"] == 750
    floor = cost["mean_calls_per_chart_floor"]
    assert floor["hit"] == 2.0
    assert floor["miss"] == 1.0
    assert round(floor["weighted"], 4) == round((36 * 2.0 + 14 * 1.0) / 50, 4)
    md = _markdown(tmp_path)
    assert "300" in md
    assert "750" in md
    assert "call" in md.lower()


def test_usage_without_outputs_exits_two() -> None:
    result = subprocess.run(
        [sys.executable, str(_SCORE)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "usage" in result.stderr.lower()
