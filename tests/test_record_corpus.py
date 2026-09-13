"""tools/record_corpus.py — the journal, its resumability, and the five
outcome rows (issue #124, ADR-0014 D12/D13)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from chartagent import ChartAgent, create_chart_agent
from chartagent.errors import PlannerFailureError

_REPO = Path(__file__).resolve().parents[1]
_TOOL = _REPO / "tools" / "record_corpus.py"
_PREREG = _REPO / "corpus" / "pre-registration.json"
_SALES = Path(__file__).with_name("data") / "sales.csv"

_FRAGMENT: dict[str, Any] = {
    "outcome": "fragment",
    "chart_type": "Bar Chart",
    "encodings": {"x": {"field": "quarter"}, "y": {"field": "total"}},
    "transform": {
        "group_by": ["quarter"],
        "aggregate": [{"name": "total", "op": "sum", "field": "revenue"}],
    },
    "semantic_types": {"total": "Quantity"},
    "requested_backend": None,
}
_RAW_SQL_FRAGMENT: dict[str, Any] = {
    "outcome": "fragment",
    "chart_type": "Bar Chart",
    "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
    "transform": {"raw_sql": "SELECT quarter, revenue FROM source"},
    "semantic_types": {"revenue": "Quantity"},
    "requested_backend": None,
}
# A residual, unattributed ChartAgentError (#137): Sankey Diagram is not
# declared for the vegalite backend, so select_backend raises
# BackendCapabilityError — a ChartAgentError outside the three named
# outcomes, still a harness bug the recorder must journal as a residual.
# (A transform naming a column the source doesn't have used to leak
# SchemaDriftError the same way; create_chart now attributes that to
# planner_failure instead — see test_planner_failure_records_miss_kind_
# and_reason_and_no_bucket.)
_BACKEND_CAPABILITY_FRAGMENT: dict[str, Any] = {
    "outcome": "fragment",
    "chart_type": "Sankey Diagram",
    "encodings": {
        "x": {"field": "quarter"},
        "y": {"field": "revenue"},
        "size": {"field": "revenue"},
    },
    "transform": None,
    "semantic_types": {},
    "requested_backend": "vegalite",
}


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("record_corpus", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reply(
    kind: str, args: dict[str, Any] | None = None
) -> Callable[..., ModelResponse]:
    def fn(_messages: object, info: AgentInfo) -> ModelResponse:
        if kind == "empty":
            return ModelResponse(parts=[])
        if kind == "step2":
            name = info.output_tools[0].name
            return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args or {})])
        name = next(tool.name for tool in info.output_tools if kind in tool.name)
        return ModelResponse(parts=[ToolCallPart(tool_name=name, args=args or {})])

    return fn


def _install(agent: ChartAgent, *replies: Any) -> dict[str, int]:
    queue = list(replies)
    calls = {"model": 0}

    def fn(messages: object, info: AgentInfo) -> ModelResponse:
        calls["model"] += 1
        reply = queue.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        if isinstance(reply, tuple):
            kind, args = reply
            return _reply(kind, args)(messages, info)
        return _reply(reply)(messages, info)

    agent._client._model = FunctionModel(fn)  # type: ignore[assignment]
    return calls


def _agent() -> ChartAgent:
    return create_chart_agent(model="test")


def _prereg() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_PREREG.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# attempt() — the five outcome rows
# ---------------------------------------------------------------------------


def test_success_is_recorded_as_deterministic_with_the_envelope() -> None:
    rc = _tool()
    agent = _agent()
    _install(agent, ("Fragment", _FRAGMENT), ("step2", {}))
    record = rc.attempt(agent, _SALES, "revenue by quarter")
    assert record["rail"] == "deterministic"
    assert record["bound_row_count"] == 2
    assert record["raw_sql_used"] is False
    assert record["envelope"]["backend"] == "vegalite"
    assert set(record["envelope"]) == {"flint_version", "backend", "input"}
    assert record["step1_calls"] == 1
    assert record["step2_calls"] == 1
    assert "miss_kind" not in record
    assert "escape_reason" not in record
    assert "residual_error" not in record


def test_raw_sql_used_is_read_off_the_stored_transform() -> None:
    rc = _tool()
    agent = _agent()
    _install(agent, ("Fragment", _RAW_SQL_FRAGMENT), ("step2", {}))
    record = rc.attempt(agent, _SALES, "revenue by quarter, raw sql")
    assert record["rail"] == "deterministic"
    assert record["raw_sql_used"] is True


def test_inexpressible_records_escape_reason_and_no_miss_kind() -> None:
    rc = _tool()
    agent = _agent()
    _install(agent, ("Inexpressible", {"outcome": "inexpressible", "bucket": 1}))
    record = rc.attempt(agent, _SALES, "a 3D holographic globe")
    assert record == {
        "rail": None,
        "escape_reason": {"bucket": 1},
        "step1_calls": 1,
        "step2_calls": 0,
    }


def test_planner_failure_records_miss_kind_and_reason_and_no_bucket() -> None:
    rc = _tool()
    agent = _agent()
    payload = {"outcome": "unanswerable", "kind": "missing_column", "keys": ["quarter"]}
    _install(agent, ("Unanswerable", payload), ("Unanswerable", payload))
    record = rc.attempt(agent, _SALES, "revenue by quarter")
    assert record["rail"] is None
    assert record["miss_kind"] == "planner_failure"
    assert record["reason"] == "invalid_emit"
    assert record["step1_calls"] == 2
    assert record["step2_calls"] == 0
    assert "escape_reason" not in record
    assert "bucket" not in record


def test_unanswerable_instruction_records_miss_kind_and_no_bucket() -> None:
    rc = _tool()
    agent = _agent()
    payload = {
        "outcome": "unanswerable",
        "kind": "missing_column",
        "keys": ["sentiment"],
    }
    _install(agent, ("Unanswerable", payload))
    record = rc.attempt(agent, _SALES, "chart sentiment")
    assert record == {
        "rail": None,
        "miss_kind": "unanswerable_instruction",
        "step1_calls": 1,
        "step2_calls": 0,
    }


def test_missing_source_column_is_planner_failure_not_a_residual() -> None:
    """#137: create_chart no longer leaks SchemaDriftError for this shape."""
    rc = _tool()
    agent = _agent()
    fragment = {
        **_FRAGMENT,
        "transform": {
            "filter": {
                "kind": "is_not_null",
                "args": [{"kind": "col", "name": "missing"}],
            }
        },
        "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
        "semantic_types": {"revenue": "Quantity"},
    }
    _install(
        agent,
        ("Fragment", fragment),
        ("step2", {}),
        ("Fragment", fragment),
        ("step2", {}),
    )
    record = rc.attempt(agent, _SALES, "drop missing")
    assert record["rail"] is None
    assert record["miss_kind"] == "planner_failure"
    assert record["reason"] == "invalid_emit"
    assert record["step1_calls"] == 2
    assert record["step2_calls"] == 2
    assert "residual_error" not in record
    assert "escape_reason" not in record
    assert "bucket" not in record


def test_residual_chart_agent_error_has_no_bucket_and_no_miss_kind() -> None:
    """The load-bearing row: a ChartAgentError outside the three named
    outcomes never becomes planner_failure — it stays an unattributed
    residual (ADR-0019 D8).
    """
    rc = _tool()
    agent = _agent()
    _install(agent, ("Fragment", _BACKEND_CAPABILITY_FRAGMENT))
    record = rc.attempt(agent, _SALES, "sankey in vegalite")
    assert record["rail"] is None
    assert record["residual_error"]["type"] == "BackendCapabilityError"
    assert isinstance(record["residual_error"]["message"], str)
    assert record["step1_calls"] == 1
    assert record["step2_calls"] == 0
    assert "miss_kind" not in record
    assert "escape_reason" not in record
    assert "bucket" not in record


# ---------------------------------------------------------------------------
# Pre-flight refusal, before any model call
# ---------------------------------------------------------------------------


def test_prereg_hash_mismatch_is_named(tmp_path: Path) -> None:
    rc = _tool()
    bad = tmp_path / "pre-registration.json"
    bad.write_text('{"requests": []}', encoding="utf-8")
    issues = rc.check_prereg_hash(_REPO, bad)
    assert len(issues) == 1
    assert "PREREG_HASH" in issues[0]
    assert rc.TAG in issues[0]


def test_prereg_hash_matches_the_real_tagged_file() -> None:
    rc = _tool()
    assert rc.check_prereg_hash(_REPO, _PREREG) == []


def test_dataset_mismatch_is_named_by_request_id(tmp_path: Path) -> None:
    rc = _tool()
    requests = _prereg()["requests"]
    tampered = [dict(item) for item in requests[:2]]
    tampered[1]["dataset_sha256"] = "0" * 64
    issues = rc.check_datasets(_REPO, tampered)
    assert len(issues) == 1
    assert tampered[1]["id"] in issues[0]
    assert "DATASET" in issues[0]


def test_dataset_missing_file_is_named(tmp_path: Path) -> None:
    rc = _tool()
    fake = [
        {
            "id": "zzz",
            "dataset_path": "corpus/data/does-not-exist.parquet",
            "dataset_sha256": "0" * 64,
        }
    ]
    issues = rc.check_datasets(_REPO, fake)
    assert len(issues) == 1
    assert "zzz" in issues[0]
    assert "is missing" in issues[0]


def test_every_real_dataset_matches_its_recorded_sha256() -> None:
    rc = _tool()
    assert rc.check_datasets(_REPO, _prereg()["requests"]) == []


def test_cli_refuses_on_hash_mismatch_before_any_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rc = _tool()
    bad = tmp_path / "pre-registration.json"
    bad.write_text('{"requests": []}', encoding="utf-8")
    journal = tmp_path / "journal.jsonl"

    def _boom(**_kwargs: Any) -> Any:
        raise AssertionError("no agent should be built when pre-flight fails")

    monkeypatch.setattr(rc, "create_chart_agent", _boom)
    code = rc.main(
        [
            "record",
            "--model",
            "test",
            "--prereg",
            str(bad),
            "--journal",
            str(journal),
        ]
    )
    assert code == 1
    assert not journal.exists()


def test_cli_refuses_on_dataset_mismatch_before_any_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clean prereg hash does not skip the dataset check before the agent."""
    rc = _tool()
    journal = tmp_path / "journal.jsonl"
    prereg_path = tmp_path / "pre-registration.json"
    prereg_path.write_text(json.dumps({"requests": []}), encoding="utf-8")

    def _boom(**_kwargs: Any) -> Any:
        raise AssertionError("no agent should be built when pre-flight fails")

    monkeypatch.setattr(rc, "create_chart_agent", _boom)
    monkeypatch.setattr(rc, "check_prereg_hash", lambda _repo, _path: [])
    monkeypatch.setattr(
        rc, "check_datasets", lambda _repo, _requests: ["DATASET            r01: bad"]
    )
    code = rc.main(
        [
            "record",
            "--model",
            "test",
            "--prereg",
            str(prereg_path),
            "--journal",
            str(journal),
        ]
    )
    assert code == 1
    assert not journal.exists()


# ---------------------------------------------------------------------------
# The journal: keyed by (request_id, run), resumable, cell 1 included
# ---------------------------------------------------------------------------


def test_end_to_end_journals_150_attempts_and_resumes_for_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prereg = _prereg()
    request_ids = [item["id"] for item in prereg["requests"]]
    assert len(request_ids) == 50
    cell1_ids = {item["id"] for item in prereg["requests"] if item["cell"] == 1}
    assert cell1_ids  # the corpus does carry cell-1 requests

    rc = _tool()
    agent = _agent()
    calls = _install(
        agent,
        *[("Inexpressible", {"outcome": "inexpressible", "bucket": 1})] * 150,
    )
    journal = tmp_path / "journal.jsonl"

    records = rc.run_record(agent, prereg, _REPO, journal)
    assert len(records) == 150
    assert calls["model"] == 150
    for request_id in request_ids:
        for run in (1, 2, 3):
            key = (request_id, run)
            assert key in records
            assert records[key]["escape_reason"] == {"bucket": 1}
            assert records[key]["rail"] is None
    # cell 1 is attempted three times like every other request
    for request_id in cell1_ids:
        assert sum(1 for run in (1, 2, 3) if (request_id, run) in records) == 3

    lines = journal.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 150
    for line in lines:
        json.loads(line)  # one JSON object per line

    # Re-running makes zero model calls for already-journalled attempts.
    resumed_calls = _install(agent)
    records_again = rc.run_record(agent, prereg, _REPO, journal)
    assert resumed_calls["model"] == 0
    assert len(records_again) == 150
    assert journal.read_text(encoding="utf-8").count("\n") == 150


def test_resuming_after_a_partial_run_only_pays_for_the_rest(tmp_path: Path) -> None:
    rc = _tool()
    prereg = {
        "requests": [
            {"id": "a", "dataset_path": "tests/data/sales.csv", "query_rewritten": "q"},
            {"id": "b", "dataset_path": "tests/data/sales.csv", "query_rewritten": "q"},
        ]
    }
    journal = tmp_path / "journal.jsonl"
    seeded = {"rail": None, "escape_reason": {"bucket": 1}}
    journal.write_text(
        "\n".join(
            json.dumps({"request_id": "a", "run": run, **seeded}) for run in (1, 2, 3)
        )
        + "\n",
        encoding="utf-8",
    )
    agent = _agent()
    calls = _install(
        agent, *[("Inexpressible", {"outcome": "inexpressible", "bucket": 2})] * 3
    )
    records = rc.run_record(agent, prereg, _REPO, journal)
    assert calls["model"] == 3
    assert len(records) == 6
    assert records[("a", 1)]["escape_reason"] == {"bucket": 1}  # untouched
    assert records[("b", 1)]["escape_reason"] == {"bucket": 2}  # newly journalled


def test_residual_errors_do_not_abort_the_run_and_are_summarised(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = _tool()
    prereg = {
        "requests": [
            {
                "id": "bad",
                "dataset_path": "tests/data/sales.csv",
                "query_rewritten": "drop missing",
            },
            {
                "id": "ok",
                "dataset_path": "tests/data/sales.csv",
                "query_rewritten": "a globe",
            },
        ]
    }
    agent = _agent()
    _install(
        agent,
        ("Fragment", _BACKEND_CAPABILITY_FRAGMENT),
        ("Fragment", _BACKEND_CAPABILITY_FRAGMENT),
        ("Fragment", _BACKEND_CAPABILITY_FRAGMENT),
        ("Inexpressible", {"outcome": "inexpressible", "bucket": 1}),
        ("Inexpressible", {"outcome": "inexpressible", "bucket": 1}),
        ("Inexpressible", {"outcome": "inexpressible", "bucket": 1}),
    )
    journal = tmp_path / "journal.jsonl"
    records = rc.run_record(agent, prereg, _REPO, journal)
    assert len(records) == 6  # every attempt ran despite the residual errors
    rc._print_residual_summary(records)
    out = capsys.readouterr().out
    assert "bad" in out
    assert "BackendCapabilityError" in out
    assert "3" in out


def test_main_record_is_zero_exit_with_residual_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = _tool()
    agent = _agent()
    _install(agent, *([("Fragment", _BACKEND_CAPABILITY_FRAGMENT)] * 3))
    monkeypatch.setattr(rc, "create_chart_agent", lambda **_kwargs: agent)

    prereg_path = tmp_path / "pre-registration.json"
    prereg_path.write_text(
        json.dumps(
            {
                "requests": [
                    {
                        "id": "r1",
                        "dataset_path": "tests/data/sales.csv",
                        "dataset_sha256": hashlib.sha256(
                            (_REPO / "tests/data/sales.csv").read_bytes()
                        ).hexdigest(),
                        "query_rewritten": "drop missing",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rc, "check_prereg_hash", lambda _repo, _path: [])
    journal = tmp_path / "journal.jsonl"
    code = rc.main(
        [
            "record",
            "--model",
            "test",
            "--prereg",
            str(prereg_path),
            "--journal",
            str(journal),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "Residual errors: 3." in out
    assert journal.exists()


# ---------------------------------------------------------------------------
# Transport retries and per-step call counts (issue #125)
# ---------------------------------------------------------------------------


def test_transport_fault_is_retried_and_the_call_still_counts_once() -> None:
    """A retried-then-successful call costs one counted planner call, not two."""
    rc = _tool()
    agent = _agent()
    _install(
        agent,
        RuntimeError("simulated rate limit"),
        RuntimeError("simulated rate limit"),
        ("Fragment", _FRAGMENT),
        ("step2", {}),
    )
    proxy = rc.RecordingClient(agent._client, retries=3, sleep=lambda _s: None)
    agent._client = proxy
    record = rc.attempt(agent, _SALES, "revenue by quarter")
    assert record is not None
    assert record["rail"] == "deterministic"
    assert record["step1_calls"] == 1
    assert record["step2_calls"] == 1
    assert proxy.transport_retries == 2
    assert proxy.transport_exhausted == 0


def test_transport_fault_exhausting_retries_leaves_the_attempt_unjournalled() -> None:
    rc = _tool()
    agent = _agent()
    _install(
        agent,
        RuntimeError("simulated rate limit"),
        RuntimeError("simulated rate limit"),
        RuntimeError("simulated rate limit"),
    )
    proxy = rc.RecordingClient(agent._client, retries=2, sleep=lambda _s: None)
    agent._client = proxy
    record = rc.attempt(agent, _SALES, "revenue by quarter")
    assert record is None
    assert proxy.transport_retries == 2
    assert proxy.transport_exhausted == 1


def test_a_planner_shape_failure_is_never_retried_as_transport() -> None:
    """ValidationError/ToolRetryError/UnexpectedModelBehavior stay the planner's own
    retry budget — the transport proxy must not intercept them."""
    rc = _tool()
    agent = _agent()
    calls = _install(agent, "empty", "empty")
    proxy = rc.RecordingClient(agent._client, retries=5, sleep=lambda _s: None)
    agent._client = proxy
    with pytest.raises(PlannerFailureError) as caught:
        agent.create_chart(_SALES, "revenue by quarter")
    assert caught.value.reason == "empty_response"
    assert calls["model"] == 2  # step 1's own retry budget, no transport retry spent
    assert proxy.transport_retries == 0
    assert proxy.transport_exhausted == 0


def test_recording_client_changes_no_planner_behaviour() -> None:
    """Installing the counting/retry proxy changes no budget, retry, or outcome."""
    rc = _tool()
    agent = _agent()
    payload = {"outcome": "unanswerable", "kind": "missing_column", "keys": ["quarter"]}
    calls = _install(agent, ("Unanswerable", payload), ("Unanswerable", payload))
    agent._client = rc.RecordingClient(agent._client)
    with pytest.raises(PlannerFailureError) as caught:
        agent.create_chart(_SALES, "revenue by quarter")
    assert caught.value.reason == "invalid_emit"
    assert calls["model"] == 2


def test_step1_calls_diagnostic_counts_the_retry() -> None:
    rc = _tool()
    agent = _agent()
    bad = {**_FRAGMENT, "transform": {"pivot": []}}
    _install(agent, ("Fragment", bad), ("Fragment", _FRAGMENT), ("step2", {}))
    record = rc.attempt(agent, _SALES, "revenue by quarter")
    assert record["rail"] == "deterministic"
    assert record["step1_calls"] == 2
    assert record["step2_calls"] == 1


def test_run_record_leaves_an_exhausted_attempt_out_of_the_journal(
    tmp_path: Path,
) -> None:
    rc = _tool()
    prereg = {
        "requests": [
            {"id": "a", "dataset_path": "tests/data/sales.csv", "query_rewritten": "q"},
        ]
    }
    journal = tmp_path / "journal.jsonl"
    agent = _agent()
    _install(
        agent,
        RuntimeError("boom"),
        RuntimeError("boom"),
        RuntimeError("boom"),
        ("Inexpressible", {"outcome": "inexpressible", "bucket": 1}),
        ("Inexpressible", {"outcome": "inexpressible", "bucket": 1}),
    )
    agent._client = rc.RecordingClient(agent._client, retries=2, sleep=lambda _s: None)
    records = rc.run_record(agent, prereg, _REPO, journal)
    assert ("a", 1) not in records
    assert ("a", 2) in records
    assert ("a", 3) in records
    assert len(records) == 2
    assert journal.read_text(encoding="utf-8").count("\n") == 2


def test_run_record_resumes_cleanly_after_an_exhausted_attempt(
    tmp_path: Path,
) -> None:
    """A crash-and-resume never re-buys an already-journalled attempt, and the
    left-out attempt is simply retried on the next invocation."""
    rc = _tool()
    prereg = {
        "requests": [
            {"id": "a", "dataset_path": "tests/data/sales.csv", "query_rewritten": "q"},
        ]
    }
    journal = tmp_path / "journal.jsonl"

    first = _agent()
    _install(
        first,
        RuntimeError("boom"),
        RuntimeError("boom"),
        RuntimeError("boom"),
        ("Inexpressible", {"outcome": "inexpressible", "bucket": 1}),
        ("Inexpressible", {"outcome": "inexpressible", "bucket": 1}),
    )
    first._client = rc.RecordingClient(first._client, retries=2, sleep=lambda _s: None)
    records = rc.run_record(first, prereg, _REPO, journal)
    assert len(records) == 2
    assert ("a", 1) not in records

    second = _agent()
    calls = _install(
        second, ("Inexpressible", {"outcome": "inexpressible", "bucket": 1})
    )
    second._client = rc.RecordingClient(
        second._client, retries=2, sleep=lambda _s: None
    )
    records_again = rc.run_record(second, prereg, _REPO, journal)
    assert calls["model"] == 1  # only the missing (a, 1) is re-attempted
    assert len(records_again) == 3
    assert ("a", 1) in records_again
