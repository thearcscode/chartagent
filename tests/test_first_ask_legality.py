"""tools/first_ask_legality.py — the first-ask-only rate, repair success kept
beside it, and the runner's per-attempt journal (issue #146, ADR-0023
Decision 8)."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from chartagent import ChartAgent, create_chart_agent

_REPO = Path(__file__).resolve().parents[1]
_TOOL = _REPO / "tools" / "first_ask_legality.py"
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
# A step-1 fragment `assemble()` rejects outright (a raw_sql that fails its
# lock 1 — a runtime SQL parse, not a shape the typed menu decodes) — unlike
# record_corpus.py's/test_plan_agent.py's bind-wrap examples, this fails at
# step 1, never reaching step 2. An unrecognised slot fails earlier, at
# decode (ADR-0023): the typed menu moves that miss from `assemble` to
# `decode`, which is exactly the shift the after-measurement's breakdown is
# for.
_BAD_TRANSFORM_FRAGMENT: dict[str, Any] = {
    **_FRAGMENT,
    "transform": {"raw_sql": "SELECT 1; SELECT 2"},
}


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("first_ask_legality", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before exec so dataclasses (FirstAskRates) can resolve its
    # own module by name — with `from __future__ import annotations`,
    # dataclass field processing looks itself up in sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def _install(agent: ChartAgent, *replies: Any) -> dict[str, int]:
    queue = list(replies)
    calls = {"model": 0}

    def fn(messages: object, info: AgentInfo) -> ModelResponse:
        calls["model"] += 1
        reply = queue.pop(0)
        if isinstance(reply, tuple):
            kind, args = reply
            return _reply(kind, args)(messages, info)
        return _reply(reply)(messages, info)

    agent._client._model = FunctionModel(fn)  # type: ignore[assignment]
    return calls


def _agent() -> ChartAgent:
    return create_chart_agent(model="test")


def _run(*attempts_shape: tuple[str, str | None]) -> dict[str, Any]:
    """A minimal journal-shaped run: ``attempts_shape`` is
    ``(outcome, emit)`` pairs, step-1 attempts in order (enough for the
    rate functions, which read only ``step``/``outcome``/``emit``)."""
    attempts = [
        {
            "step": 1,
            "ask": i + 1,
            "outcome": outcome,
            **({"emit": emit} if emit else {}),
        }
        for i, (outcome, emit) in enumerate(attempts_shape)
    ]
    return {"attempts": attempts}


# ---------------------------------------------------------------------------
# compute_first_ask_rates — pure, no model
# ---------------------------------------------------------------------------


def test_fragment_first_ask_counts_as_ok_in_both_views() -> None:
    rc = _tool()
    rates = rc.compute_first_ask_rates([_run(("ok", "fragment"))])
    assert (rates.included_ok, rates.included_total) == (1, 1)
    assert (rates.excluded_ok, rates.excluded_total) == (1, 1)


def test_verdict_first_ask_counts_included_but_drops_from_excluded() -> None:
    rc = _tool()
    rates = rc.compute_first_ask_rates(
        [_run(("ok", "inexpressible")), _run(("ok", "unanswerable"))]
    )
    assert (rates.included_ok, rates.included_total) == (2, 2)
    # Both runs are verdicts: dropped from numerator *and* denominator.
    assert (rates.excluded_ok, rates.excluded_total) == (0, 0)
    assert rates.excluded_rate is None


def test_a_repaired_run_is_not_first_ask_ok() -> None:
    """The ticket's own done-when test: a run whose first step-1 attempt
    missed and whose *next* step-1 attempt reached ok is not counted as
    first-ask legal, in either view."""
    rc = _tool()
    repaired = _run(("assemble", None), ("ok", "fragment"))
    rates = rc.compute_first_ask_rates([repaired])
    assert rates.included_ok == 0
    assert rates.excluded_ok == 0
    assert rates.included_total == 1
    assert rates.excluded_total == 1  # not a verdict, stays in the denominator


def test_repair_success_is_tracked_beside_the_rate_not_folded_in() -> None:
    rc = _tool()
    repaired = _run(("assemble", None), ("ok", "fragment"))
    never_repaired = _run(("decode", None), ("decode", None))
    rates = rc.compute_first_ask_rates([repaired, never_repaired])
    assert rates.repair_eligible == 2
    assert rates.repair_succeeded == 1
    assert rates.repair_rate == 0.5
    # Neither touches the first-ask numerator.
    assert rates.included_ok == 0
    assert rates.excluded_ok == 0


def test_repair_eligible_excludes_runs_that_were_first_ask_ok() -> None:
    rc = _tool()
    rates = rc.compute_first_ask_rates([_run(("ok", "fragment"))])
    assert rates.repair_eligible == 0
    assert rates.repair_rate is None


def test_breakdown_counts_the_first_attempt_outcome_only() -> None:
    rc = _tool()
    repaired = _run(("assemble", None), ("ok", "fragment"))
    rates = rc.compute_first_ask_rates([repaired])
    assert rates.breakdown == {"assemble": 1}
    assert "ok" not in rates.breakdown


def test_breakdown_covers_all_four_outcomes_across_runs() -> None:
    rc = _tool()
    runs = [
        _run(("decode", None)),
        _run(("assemble", None), ("ok", "fragment")),
        _run(("refuted", None)),
        _run(("ok", "fragment")),
    ]
    rates = rc.compute_first_ask_rates(runs)
    assert rates.breakdown == {"decode": 1, "assemble": 1, "refuted": 1, "ok": 1}


def test_rates_are_none_on_an_empty_denominator() -> None:
    rc = _tool()
    rates = rc.compute_first_ask_rates([])
    assert rates.included_rate is None
    assert rates.excluded_rate is None
    assert rates.repair_rate is None


# ---------------------------------------------------------------------------
# attempt() — real Attempt journal off a scripted model
# ---------------------------------------------------------------------------


def test_attempt_records_ok_fragment_as_the_only_step1_attempt() -> None:
    rc = _tool()
    agent = _agent()
    _install(agent, ("Fragment", _FRAGMENT), ("step2", {}))
    record = rc.attempt(agent, _SALES, "revenue by quarter")
    assert record["rail"] == "deterministic"
    step1 = [a for a in record["attempts"] if a["step"] == 1]
    assert step1 == [{"step": 1, "ask": 1, "outcome": "ok", "emit": "fragment"}]


def test_attempt_records_the_model_that_actually_produced_it() -> None:
    """The manifest's model string must come from what actually ran, never
    an independently-typed `report --model` flag (a `run`/`report` mismatch
    would otherwise silently mislabel the data)."""
    rc = _tool()
    agent = create_chart_agent(model="test")
    _install(agent, ("Fragment", _FRAGMENT), ("step2", {}))
    record = rc.attempt(agent, _SALES, "revenue by quarter")
    assert record["model"] == "test"


def test_attempt_records_a_repaired_step1_assemble_rejection() -> None:
    rc = _tool()
    agent = _agent()
    _install(
        agent,
        ("Fragment", _BAD_TRANSFORM_FRAGMENT),
        ("Fragment", _FRAGMENT),
        ("step2", {}),
    )
    record = rc.attempt(agent, _SALES, "revenue by quarter")
    assert record["rail"] == "deterministic"
    step1 = [a for a in record["attempts"] if a["step"] == 1]
    assert len(step1) == 2
    assert step1[0]["outcome"] == "assemble"
    assert "rejected_emit" in step1[0]
    assert "checker" in step1[0]
    assert step1[1] == {"step": 1, "ask": 2, "outcome": "ok", "emit": "fragment"}
    # Fed into the rate function: not first-ask ok, but a repair success.
    rates = rc.compute_first_ask_rates([record])
    assert rates.included_ok == 0
    assert rates.repair_eligible == 1
    assert rates.repair_succeeded == 1


def test_attempt_records_a_well_formed_inexpressible_verdict() -> None:
    rc = _tool()
    agent = _agent()
    _install(agent, ("Inexpressible", {"outcome": "inexpressible", "bucket": 1}))
    record = rc.attempt(agent, _SALES, "a 3D holographic globe")
    assert record["rail"] is None
    assert record["escape_reason"] == {"bucket": 1}
    assert record["attempts"] == [
        {"step": 1, "ask": 1, "outcome": "ok", "emit": "inexpressible"}
    ]


# ---------------------------------------------------------------------------
# run_measurement — resumable journal
# ---------------------------------------------------------------------------


def test_run_measurement_skips_already_journalled_pairs(tmp_path: Path) -> None:
    rc = _tool()
    agent = _agent()
    journal = tmp_path / "journal.jsonl"
    journal.write_text(
        json.dumps(
            {
                "id": "fa01",
                "run": 1,
                "rail": "deterministic",
                "attempts": [
                    {"step": 1, "ask": 1, "outcome": "ok", "emit": "fragment"}
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    calls = _install(agent, ("Fragment", _FRAGMENT), ("step2", {}))
    instructions = [{"id": "fa01", "fixture": "sales.csv", "instruction": "revenue"}]
    records = rc.run_measurement(
        agent,
        instructions,
        Path(__file__).with_name("data"),
        journal,
        runs_per_instruction=1,
    )
    assert calls["model"] == 0  # the one (id, run) pair was already journalled
    assert len(records) == 1


def test_run_measurement_appends_new_runs_and_persists_them(tmp_path: Path) -> None:
    rc = _tool()
    agent = _agent()
    journal = tmp_path / "journal.jsonl"
    _install(agent, ("Fragment", _FRAGMENT), ("step2", {}))
    instructions = [{"id": "fa01", "fixture": "sales.csv", "instruction": "revenue"}]
    records = rc.run_measurement(
        agent,
        instructions,
        Path(__file__).with_name("data"),
        journal,
        runs_per_instruction=1,
    )
    assert set(records) == {("fa01", 1)}
    on_disk = journal.read_text(encoding="utf-8").splitlines()
    assert len(on_disk) == 1
    assert json.loads(on_disk[0])["id"] == "fa01"


# ---------------------------------------------------------------------------
# Manifest and report
# ---------------------------------------------------------------------------


def test_journal_model_returns_the_single_model_across_runs() -> None:
    rc = _tool()
    model = "anthropic:claude-sonnet-4-6"
    runs = [{"model": model}, {"model": model}]
    assert rc.journal_model(runs) == model


def test_journal_model_raises_when_runs_disagree() -> None:
    rc = _tool()
    runs = [{"model": "anthropic:claude-sonnet-4-6"}, {"model": "anthropic:other"}]
    try:
        rc.journal_model(runs)
    except rc.MixedModelJournalError as exc:
        assert exc.models == {"anthropic:claude-sonnet-4-6", "anthropic:other"}
    else:
        raise AssertionError("expected MixedModelJournalError")


def test_cli_run_requires_an_explicit_model() -> None:
    """Matches `tools/record_corpus.py` / `tools/join_corpus.py`: a billed,
    manifest-bearing model string is never silently defaulted."""
    rc = _tool()
    assert rc.main(["run"]) == 2


def test_fixture_commit_and_library_commit_are_full_shas() -> None:
    rc = _tool()
    assert re.fullmatch(r"[0-9a-f]{40}", rc.fixture_commit(_REPO) or "")
    assert re.fullmatch(r"[0-9a-f]{40}", rc.library_commit(_REPO) or "")


def test_read_flint_pin_reads_the_shipped_vocab() -> None:
    rc = _tool()
    pin = rc.read_flint_pin(_REPO / "src" / "chartagent" / "frame" / "vocab.json")
    assert pin["flint_version"]
    assert pin["bundle_sha256"]


def test_render_report_states_both_rates_breakdown_repair_and_manifest() -> None:
    rc = _tool()
    rates = rc.compute_first_ask_rates(
        [_run(("ok", "fragment")), _run(("assemble", None), ("ok", "fragment"))]
    )
    manifest = {
        "fixture_commit": "abc123",
        "library_commit": "def456",
        "model": "anthropic:claude-sonnet-4-6",
        "flint_pin": {"flint_version": "0.5.1", "bundle_sha256": "deadbeef"},
        "run_date": "2026-09-13",
    }
    report = rc.render_report(rates, manifest)
    assert "abc123" in report
    assert "def456" in report
    assert "anthropic:claude-sonnet-4-6" in report
    assert "0.5.1" in report
    assert "deadbeef" in report
    assert "First-ask legality" in report
    assert "Repair success" in report
    assert "outcome breakdown" in report.lower()
    assert "no gate" in report.lower()


# ---------------------------------------------------------------------------
# The corpus-freeze guardrail (ADR-0023 Decision 8)
# ---------------------------------------------------------------------------


def test_the_tool_never_reads_the_frozen_corpus() -> None:
    """Nothing under `corpus/` is read, adapted, or re-scored by this tool —
    a from-scratch instruction set (#145) measures its own series."""
    source = _TOOL.read_text(encoding="utf-8")
    for banned in (
        "corpus/pre-registration",
        "corpus/data",
        "corpus/outputs.json",
        "pre-registration.json",
    ):
        assert banned not in source
