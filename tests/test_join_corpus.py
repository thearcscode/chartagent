"""tools/join_corpus.py — the join, the provenance manifest, and the real
scorer end-to-end (issue #128, ADR-0014 D13)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from chartagent import ChartAgent, create_chart_agent
from chartagent.plan.client import PRODUCT_DECODING

_REPO = Path(__file__).resolve().parents[1]
_TOOL = _REPO / "tools" / "join_corpus.py"
_SCORE = _REPO / "tools" / "score_corpus.py"
_PREREG = _REPO / "corpus" / "pre-registration.json"
_VOCAB = _REPO / "src" / "chartagent" / "frame" / "vocab.json"
_VENDOR_PIN = _REPO / "tools" / "paint" / "vendor" / "vendor.json"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("join_corpus", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prereg() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_PREREG.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# envelope_sha256 — canonical, order-independent
# ---------------------------------------------------------------------------


def test_envelope_sha256_is_stable_across_key_order() -> None:
    jc = _tool()
    a = {"backend": "vegalite", "flint_version": "0.5.1", "input": {"x": 1, "y": 2}}
    b = {"input": {"y": 2, "x": 1}, "flint_version": "0.5.1", "backend": "vegalite"}
    assert jc.envelope_sha256(a) == jc.envelope_sha256(b)


def test_envelope_sha256_changes_with_content() -> None:
    jc = _tool()
    a = {"backend": "vegalite", "input": {"x": 1}}
    b = {"backend": "vegalite", "input": {"x": 2}}
    assert jc.envelope_sha256(a) != jc.envelope_sha256(b)


# ---------------------------------------------------------------------------
# join_runs — the merge itself
# ---------------------------------------------------------------------------

_ENVELOPE = {
    "flint_version": "0.5.1",
    "backend": "vegalite",
    "input": {"chart_spec": {"chartType": "Bar Chart"}},
}


def _hit_record(request_id: str, run: int, **extra: Any) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "run": run,
        "rail": "deterministic",
        "envelope": _ENVELOPE,
        "bound_row_count": 10,
        "raw_sql_used": False,
        "step1_calls": 1,
        "step2_calls": 1,
        **extra,
    }


def _paint_record(request_id: str, run: int, **extra: Any) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "run": run,
        "backend": "vegalite",
        "accepted": True,
        "painted": True,
        "compiled_row_count": 10,
        "bound_row_count": 10,
        "error": None,
        **extra,
    }


def test_a_hit_is_merged_with_its_paint_record_and_loses_its_envelope() -> None:
    jc = _tool()
    record_journal = {("r1", 1): _hit_record("r1", 1)}
    paint_journal = {("r1", 1): _paint_record("r1", 1)}
    runs, issues = jc.join_runs(record_journal, paint_journal)
    assert issues == []
    assert len(runs) == 1
    row = runs[0]
    assert "envelope" not in row
    assert row["envelope_sha256"] == jc.envelope_sha256(_ENVELOPE)
    assert row["rail"] == "deterministic"
    assert row["emitted_compilable"] is True
    assert row["painted"] is True
    assert row["compiled_row_count"] == 10
    assert row["bound_row_count"] == 10
    assert row["raw_sql_used"] is False
    assert row["backend"] == "vegalite"
    assert row["step1_calls"] == 1
    assert row["step2_calls"] == 1
    assert "error" not in row


def test_join_runs_tolerates_the_per_attempt_journal_field() -> None:
    """Issue #144: record_corpus.py now writes an ``attempts`` list on every
    record; join_runs whitelists fields onto ``merged`` by name, so an
    unknown key is silently dropped, never a break."""
    jc = _tool()
    attempts = [
        {"step": 1, "ask": 1, "outcome": "ok", "emit": "fragment"},
        {"step": 2, "ask": 1, "outcome": "ok"},
    ]
    record_journal = {("r1", 1): _hit_record("r1", 1, attempts=attempts)}
    paint_journal = {("r1", 1): _paint_record("r1", 1)}
    runs, issues = jc.join_runs(record_journal, paint_journal)
    assert issues == []
    assert "attempts" not in runs[0]


def test_a_paint_error_is_carried_through_when_present() -> None:
    jc = _tool()
    record_journal = {("r1", 1): _hit_record("r1", 1)}
    paint_journal = {("r1", 1): _paint_record("r1", 1, painted=False, error="boom")}
    runs, issues = jc.join_runs(record_journal, paint_journal)
    assert issues == []
    assert runs[0]["painted"] is False
    assert runs[0]["error"] == "boom"


def test_assembler_refusal_is_emitted_compilable_false_with_null_row_count() -> None:
    jc = _tool()
    record_journal = {("r1", 1): _hit_record("r1", 1)}
    paint_journal = {
        ("r1", 1): _paint_record(
            "r1", 1, accepted=False, painted=False, compiled_row_count=None
        )
    }
    runs, issues = jc.join_runs(record_journal, paint_journal)
    assert issues == []
    row = runs[0]
    assert row["emitted_compilable"] is False
    assert row["painted"] is False
    assert row["compiled_row_count"] is None


def test_a_deterministic_record_missing_its_paint_record_is_a_named_issue() -> None:
    jc = _tool()
    record_journal = {("r1", 1): _hit_record("r1", 1)}
    runs, issues = jc.join_runs(record_journal, {})
    assert runs == []
    assert len(issues) == 1
    assert "PAINT_MISSING" in issues[0]
    assert "r1" in issues[0]


def test_an_escape_reason_miss_is_passed_through_with_paint_defaults() -> None:
    jc = _tool()
    record_journal = {
        ("r1", 1): {
            "request_id": "r1",
            "run": 1,
            "rail": None,
            "escape_reason": {"bucket": 1},
            "step1_calls": 1,
            "step2_calls": 0,
        }
    }
    runs, issues = jc.join_runs(record_journal, {})
    assert issues == []
    row = runs[0]
    assert row["rail"] is None
    assert row["escape_reason"] == {"bucket": 1}
    assert row["raw_sql_used"] is False
    assert row["emitted_compilable"] is False
    assert row["painted"] is False
    assert row["compiled_row_count"] is None
    assert row["bound_row_count"] is None
    assert "miss_kind" not in row
    assert "residual_error" not in row


def test_a_planner_failure_miss_kind_and_reason_are_passed_through() -> None:
    jc = _tool()
    record_journal = {
        ("r1", 1): {
            "request_id": "r1",
            "run": 1,
            "rail": None,
            "miss_kind": "planner_failure",
            "reason": "invalid_emit",
            "step1_calls": 2,
            "step2_calls": 0,
        }
    }
    runs, _issues = jc.join_runs(record_journal, {})
    row = runs[0]
    assert row["miss_kind"] == "planner_failure"
    assert row["reason"] == "invalid_emit"
    assert "escape_reason" not in row


def test_a_residual_error_carries_no_bucket_and_no_miss_kind() -> None:
    jc = _tool()
    record_journal = {
        ("r1", 1): {
            "request_id": "r1",
            "run": 1,
            "rail": None,
            "residual_error": {"type": "SchemaDriftError", "message": "boom"},
            "step1_calls": 1,
            "step2_calls": 1,
        }
    }
    runs, _issues = jc.join_runs(record_journal, {})
    row = runs[0]
    assert row["residual_error"] == {"type": "SchemaDriftError", "message": "boom"}
    assert "escape_reason" not in row
    assert "miss_kind" not in row


def test_runs_are_sorted_by_request_id_then_run() -> None:
    jc = _tool()
    record_journal = {
        ("r2", 1): _hit_record("r2", 1),
        ("r1", 2): _hit_record("r1", 2),
        ("r1", 1): _hit_record("r1", 1),
    }
    paint_journal = {key: _paint_record(*key) for key in record_journal}
    runs, _issues = jc.join_runs(record_journal, paint_journal)
    assert [(row["request_id"], row["run"]) for row in runs] == [
        ("r1", 1),
        ("r1", 2),
        ("r2", 1),
    ]


# ---------------------------------------------------------------------------
# build_manifest / build_outputs
# ---------------------------------------------------------------------------


def test_build_manifest_carries_every_required_field() -> None:
    jc = _tool()
    manifest = jc.build_manifest(
        model="anthropic:claude-sonnet-4-6",
        purpose="gate",
        prereg={"flint_version": "0.5.1", "fixture_commit": "34ef451"},
        vocab={"flint_version": "0.5.1", "bundle_sha256": "abc123"},
        prereg_sha256="deadbeef",
        renderer_pins={"vega": {"version": "6.4.0"}},
        commit="c0ffee",
        run_date="2026-09-09",
        transport_retries=2,
        transport_exhausted=1,
        runs=[
            {"step1_calls": 1, "step2_calls": 1},
            {"step1_calls": 2, "step2_calls": 0},
        ],
    )
    assert manifest["model"] == "anthropic:claude-sonnet-4-6"
    assert manifest["purpose"] == "gate"
    assert manifest["authoring_pin"] == {
        "flint_version": "0.5.1",
        "fixture_commit": "34ef451",
    }
    assert manifest["scoring_pin"] == {
        "flint_version": "0.5.1",
        "bundle_sha256": "abc123",
    }
    assert manifest["prereg_sha256"] == "deadbeef"
    assert manifest["renderer_pins"] == {"vega": {"version": "6.4.0"}}
    assert manifest["library_commit"] == "c0ffee"
    assert manifest["run_date"] == "2026-09-09"
    assert manifest["transport_retries"] == 2
    assert manifest["transport_exhausted"] == 1
    assert manifest["call_counts"] == {"step1_calls": 3, "step2_calls": 1}


def test_build_outputs_has_exactly_the_three_top_level_keys() -> None:
    jc = _tool()
    outputs = jc.build_outputs([{"request_id": "r1"}], {"model": "test"})
    assert set(outputs) == {"decoding", "runs", "manifest"}
    assert outputs["decoding"] == dict(PRODUCT_DECODING)
    assert outputs["runs"] == [{"request_id": "r1"}]
    assert outputs["manifest"] == {"model": "test"}


def test_read_renderer_pins_drops_the_comment_key() -> None:
    jc = _tool()
    pins = jc.read_renderer_pins(_VENDOR_PIN)
    assert "_comment" not in pins
    assert "vega" in pins
    assert "sha256" in pins["vega"]


def test_library_commit_reads_the_real_head() -> None:
    jc = _tool()
    commit = jc.library_commit(_REPO)
    assert commit is not None
    assert len(commit) == 40


# ---------------------------------------------------------------------------
# CLI: refusal to overwrite, missing journal, a paint gap, a clean write
# ---------------------------------------------------------------------------


def _write_journal(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )


def _minimal_prereg(tmp_path: Path) -> Path:
    path = tmp_path / "pre-registration.json"
    path.write_text(
        json.dumps({"flint_version": "0.5.1", "fixture_commit": "34ef451"}),
        encoding="utf-8",
    )
    return path


def test_cli_refuses_when_journal_is_missing(tmp_path: Path) -> None:
    jc = _tool()
    code = jc.main(
        [
            "join",
            "--model",
            "test",
            "--purpose",
            "plumbing",
            "--journal",
            str(tmp_path / "journal.jsonl"),
            "--out",
            str(tmp_path / "outputs.json"),
            "--prereg",
            str(_minimal_prereg(tmp_path)),
            "--vocab",
            str(_VOCAB),
            "--vendor-pin",
            str(_VENDOR_PIN),
        ]
    )
    assert code == 1
    assert not (tmp_path / "outputs.json").exists()


def test_cli_refuses_on_a_paint_gap_and_writes_nothing(tmp_path: Path) -> None:
    jc = _tool()
    journal = tmp_path / "journal.jsonl"
    _write_journal(journal, [_hit_record("r1", 1)])
    code = jc.main(
        [
            "join",
            "--model",
            "test",
            "--purpose",
            "plumbing",
            "--journal",
            str(journal),
            "--paint-journal",
            str(tmp_path / "paint_journal.jsonl"),
            "--out",
            str(tmp_path / "outputs.json"),
            "--prereg",
            str(_minimal_prereg(tmp_path)),
            "--vocab",
            str(_VOCAB),
            "--vendor-pin",
            str(_VENDOR_PIN),
        ]
    )
    assert code == 1
    assert not (tmp_path / "outputs.json").exists()


def test_cli_writes_outputs_and_then_refuses_without_force(tmp_path: Path) -> None:
    jc = _tool()
    journal = tmp_path / "journal.jsonl"
    paint_journal = tmp_path / "paint_journal.jsonl"
    _write_journal(journal, [_hit_record("r1", 1)])
    _write_journal(paint_journal, [_paint_record("r1", 1)])
    out = tmp_path / "outputs.json"
    args = [
        "join",
        "--model",
        "test",
        "--purpose",
        "plumbing",
        "--journal",
        str(journal),
        "--paint-journal",
        str(paint_journal),
        "--out",
        str(out),
        "--prereg",
        str(_minimal_prereg(tmp_path)),
        "--vocab",
        str(_VOCAB),
        "--vendor-pin",
        str(_VENDOR_PIN),
        "--date",
        "2026-09-09",
    ]
    assert jc.main(args) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert set(doc) == {"decoding", "runs", "manifest"}
    assert doc["manifest"]["purpose"] == "plumbing"
    assert doc["manifest"]["model"] == "test"
    assert doc["manifest"]["run_date"] == "2026-09-09"
    assert len(doc["runs"]) == 1
    assert doc["runs"][0]["envelope_sha256"]

    # Re-running without --force is refused and the file is untouched.
    before = out.read_text(encoding="utf-8")
    assert jc.main(args) == 1
    assert out.read_text(encoding="utf-8") == before

    # --force overwrites.
    assert jc.main([*args, "--force"]) == 0


def test_cli_rejects_an_unknown_purpose(tmp_path: Path) -> None:
    jc = _tool()
    code = jc.main(
        [
            "join",
            "--model",
            "test",
            "--purpose",
            "bogus",
            "--out",
            str(tmp_path / "outputs.json"),
        ]
    )
    assert code == 2
    assert not (tmp_path / "outputs.json").exists()


# ---------------------------------------------------------------------------
# The join, end-to-end: the real 50-request corpus through the real scorer
# ---------------------------------------------------------------------------


def _reply(
    kind: str, args: dict[str, Any] | None = None
) -> Callable[..., ModelResponse]:
    def fn(_messages: object, info: AgentInfo) -> ModelResponse:
        if kind == "step2":
            name = info.output_tools[0].name
            return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args or {})])
        name = next(tool.name for tool in info.output_tools if kind in tool.name)
        return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args or {})])

    return fn


def _install(agent: ChartAgent, *replies: Any) -> None:
    queue = list(replies)

    def fn(messages: object, info: AgentInfo) -> ModelResponse:
        kind, args = queue.pop(0)
        return _reply(kind, args)(messages, info)

    agent._client._model = FunctionModel(fn)  # type: ignore[assignment]


_INEXPRESSIBLE = ("Inexpressible", {"outcome": "inexpressible", "bucket": 1})

# Triggers a residual, unattributed ChartAgentError regardless of which
# real dataset it runs against: Sankey Diagram is not declared for the
# vegalite backend, so select_backend raises BackendCapabilityError before
# ever touching the data — a ChartAgentError outside the three named
# outcomes, still a harness bug the recorder must journal as a residual.
# (A transform naming a column the source doesn't have used to leak
# SchemaDriftError the same way; create_chart now attributes that to
# planner_failure instead — #137.)
_RESIDUAL_FRAGMENT = {
    "outcome": "fragment",
    "chart_type": "Sankey Diagram",
    "encodings": {
        "x": {"field": "yearid"},
        "y": {"field": "n"},
        "size": {"field": "n"},
    },
    "transform": None,
    "semantic_types": {},
    "requested_backend": "vegalite",
}

# r01's own reference frame (ADR-0014's tagged fixture), unmodified — the
# happy path for the same request the residual fixture above deliberately
# breaks, so one test exercises a genuine deterministic-rail ChartResult
# against a real corpus dataset.
_HIT_FRAGMENT = {
    "outcome": "fragment",
    "chart_type": "Line Chart",
    "encodings": {"x": {"field": "yearid"}, "y": {"field": "n"}},
    "transform": {
        "group_by": ["yearid"],
        "aggregate": [{"name": "n", "op": "count"}],
    },
    "semantic_types": {"n": "Quantity"},
    "requested_backend": None,
}


def _replies_for(
    prereg: dict[str, Any], *, residual_id: str | None = None, hit_id: str | None = None
) -> list[Any]:
    replies: list[Any] = []
    for item in prereg["requests"]:
        for _run in range(3):
            if item["id"] == residual_id:
                # BackendCapabilityError fires in select_backend, between
                # step 1 and step 2 — no step2 reply is ever consumed.
                replies.append(("Fragment", _RESIDUAL_FRAGMENT))
            elif item["id"] == hit_id:
                replies.append(("Fragment", _HIT_FRAGMENT))
                replies.append(("step2", {}))
            else:
                replies.append(_INEXPRESSIBLE)
    return replies


def _load_record_corpus() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "record_corpus", _REPO / "tools" / "record_corpus.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record_journal_via_real_recorder(
    tmp_path: Path, *, residual_id: str | None = None, hit_id: str | None = None
) -> tuple[Path, dict[tuple[str, int], dict[str, Any]]]:
    """Drive the real record leg (tools/record_corpus.py) with a scripted
    model against the real tagged pre-registration — no network. Returns
    the journal path and every record it holds, keyed by (request_id, run),
    so a caller can fabricate paint facts for a genuine deterministic hit."""
    rc = _load_record_corpus()
    prereg = _prereg()
    agent = create_chart_agent(model="test")
    _install(agent, *_replies_for(prereg, residual_id=residual_id, hit_id=hit_id))
    journal = tmp_path / "journal.jsonl"
    records = rc.run_record(agent, prereg, _REPO, journal)
    return journal, records


def _score(outputs: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_SCORE),
            str(outputs),
            "--json",
            str(tmp_path / "report.json"),
            "--md",
            str(tmp_path / "report.md"),
            "--date",
            "2026-09-09",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_an_all_clean_run_joins_and_the_real_scorer_exits_0(tmp_path: Path) -> None:
    journal, _records = _record_journal_via_real_recorder(tmp_path)
    out = tmp_path / "outputs.json"
    jc = _tool()
    code = jc.main(
        [
            "join",
            "--model",
            "test",
            "--purpose",
            "plumbing",
            "--journal",
            str(journal),
            "--paint-journal",
            str(tmp_path / "paint_journal.jsonl"),  # empty: no deterministic rows
            "--out",
            str(out),
        ]
    )
    assert code == 0

    result = _score(out, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "report.json").is_file()
    assert (tmp_path / "report.md").is_file()


def test_one_residual_error_joins_and_the_real_scorer_exits_1_unattributed(
    tmp_path: Path,
) -> None:
    journal, _records = _record_journal_via_real_recorder(tmp_path, residual_id="r01")
    out = tmp_path / "outputs.json"
    jc = _tool()
    code = jc.main(
        [
            "join",
            "--model",
            "test",
            "--purpose",
            "plumbing",
            "--journal",
            str(journal),
            "--paint-journal",
            str(tmp_path / "paint_journal.jsonl"),
            "--out",
            str(out),
        ]
    )
    assert code == 0

    result = _score(out, tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "UNATTRIBUTED" in result.stdout
    assert "r01" in result.stdout


def test_a_real_deterministic_hit_joins_with_fabricated_paint_facts(
    tmp_path: Path,
) -> None:
    """The one seam the other two end-to-end tests don't reach: a genuine
    ``ChartResult`` from the real planner against a real corpus dataset,
    paired with fabricated paint facts (issue #122's "3. The join" testing
    decision — no browser here, that is the paint leg's own seam), joined
    and accepted by the real scorer as an actual rail hit."""
    journal, records = _record_journal_via_real_recorder(tmp_path, hit_id="r01")
    for run in (1, 2, 3):
        assert records[("r01", run)]["rail"] == "deterministic"

    paint_journal = tmp_path / "paint_journal.jsonl"
    lines = [
        json.dumps(
            {
                "request_id": "r01",
                "run": run,
                "backend": records[("r01", run)]["envelope"]["backend"],
                "accepted": True,
                "painted": True,
                "compiled_row_count": records[("r01", run)]["bound_row_count"],
                "bound_row_count": records[("r01", run)]["bound_row_count"],
                "error": None,
            }
        )
        for run in (1, 2, 3)
    ]
    paint_journal.write_text("\n".join(lines) + "\n", encoding="utf-8")

    out = tmp_path / "outputs.json"
    jc = _tool()
    code = jc.main(
        [
            "join",
            "--model",
            "test",
            "--purpose",
            "plumbing",
            "--journal",
            str(journal),
            "--paint-journal",
            str(paint_journal),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    r01_runs = sorted(
        (row for row in doc["runs"] if row["request_id"] == "r01"),
        key=lambda row: row["run"],
    )
    assert len(r01_runs) == 3
    for row in r01_runs:
        assert row["rail"] == "deterministic"
        assert row["emitted_compilable"] is True
        assert row["painted"] is True
        assert row["compiled_row_count"] == row["bound_row_count"]
        assert row["envelope_sha256"]
        assert "envelope" not in row

    result = _score(out, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    r01_row = next(row for row in report["requests"] if row["id"] == "r01")
    assert r01_row["rail_hit"] is True
    assert r01_row["delivered"] is True
