"""tools/paint_corpus.py — the pinned browser harness, its journal, and the
paint predicate (issue #126, ADR-0003 D3-D7, ADR-0014 D10).

The preflight, journal and CLI tests are pure Python and never launch a
browser. The ``harness`` fixture launches one real, pinned Chromium tab and
is shared across the tests that actually paint — if Playwright's Chromium
is not installed locally, those tests are skipped rather than failed. A
failure of the vendored-bytes preflight check itself is never skipped: that
would mean the checked-in vendor files are actually corrupt, which is a real
bug, not an environment gap.
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

_REPO = Path(__file__).resolve().parents[1]
_TOOL = _REPO / "tools" / "paint_corpus.py"

_BAR_INPUT: dict[str, Any] = {
    "data": {
        "values": [
            {"quarter": "Q1", "revenue": 1200},
            {"quarter": "Q2", "revenue": 1450},
            {"quarter": "Q3", "revenue": 980},
            {"quarter": "Q4", "revenue": 1800},
        ]
    },
    "semantic_types": {"quarter": "Quarter", "revenue": "Revenue"},
    "chart_spec": {
        "chartType": "Bar Chart",
        "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
        "baseSize": {"width": 480, "height": 320},
    },
}
_BAR_ENVELOPE: dict[str, Any] = {"backend": "vegalite", "input": _BAR_INPUT}


def _dense_input(n: int, *, width: float, height: float) -> dict[str, Any]:
    """A nominal-axis bar chart wide enough, at a small enough canvas, to
    trip Flint's discrete-channel row drop (ADR-0014 D10's own example)."""
    return {
        "data": {"values": [{"category": f"c{i}", "value": i} for i in range(n)]},
        "semantic_types": {"category": "Category", "value": "Value"},
        "chart_spec": {
            "chartType": "Bar Chart",
            "encodings": {"x": {"field": "category"}, "y": {"field": "value"}},
            "baseSize": {"width": width, "height": height},
        },
    }


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("paint_corpus", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Preflight: the vendored-bytes checks, never a CDN, never an npm resolve
# ---------------------------------------------------------------------------


def test_flint_hash_matches_the_real_vendored_bundle() -> None:
    rc = _tool()
    assert rc.check_flint_hash() == []


def test_flint_hash_mismatch_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    rc = _tool()

    class _FakeBundle:
        path = _REPO / "tests" / "data" / "sales.csv"  # any real, wrong file
        sha256 = "0" * 64

        def read_bytes(self) -> bytes:
            return self.path.read_bytes()

    monkeypatch.setattr(rc, "flint_bundle", lambda: _FakeBundle())
    issues = rc.check_flint_hash()
    assert len(issues) == 1
    assert "FLINT_HASH" in issues[0]
    assert "0" * 64 in issues[0]


def test_vendor_hashes_match_the_real_vendored_files() -> None:
    rc = _tool()
    assert rc.check_vendor_hashes() == []


def test_vendor_hash_mismatch_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rc = _tool()
    monkeypatch.setattr(
        rc,
        "_vendor_pin",
        lambda: {"vega": {"file": "vega.min.js", "sha256": "0" * 64}},
    )
    issues = rc.check_vendor_hashes()
    assert len(issues) == 1
    assert "VENDOR_HASH" in issues[0]
    assert "vega" in issues[0]


def test_vendor_missing_file_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    rc = _tool()
    monkeypatch.setattr(
        rc,
        "_vendor_pin",
        lambda: {"nope": {"file": "does-not-exist.js", "sha256": "0" * 64}},
    )
    issues = rc.check_vendor_hashes()
    assert len(issues) == 1
    assert "VENDOR_MISSING" in issues[0]
    assert "nope" in issues[0]


def test_preflight_error_is_raised_before_any_server_or_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rc = _tool()
    monkeypatch.setattr(rc, "check_flint_hash", lambda: ["FLINT_HASH bad"])
    with pytest.raises(rc.PaintPreflightError) as excinfo:
        rc.PaintHarness()
    assert excinfo.value.issues == ["FLINT_HASH bad"]


def test_a_failed_enter_tears_down_the_server_thread_it_already_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """__enter__ starts the loopback server before it launches the browser.
    Python never calls __exit__ when __enter__ itself raises, so a browser
    launch failure (the common "Chromium not installed" case) must not
    leak the server thread it already started."""
    import playwright.sync_api

    rc = _tool()
    harness = rc.PaintHarness()

    class _BoomPlaywright:
        def start(self) -> Any:
            raise RuntimeError("no chromium installed")

    monkeypatch.setattr(
        playwright.sync_api, "sync_playwright", lambda: _BoomPlaywright()
    )

    with pytest.raises(RuntimeError):
        harness.__enter__()

    assert harness._server is not None  # it did get as far as starting one
    assert harness._thread is not None
    assert not harness._thread.is_alive()  # torn down, not leaked


# ---------------------------------------------------------------------------
# The journal: keyed by (request_id, run), resumable like the record leg's
# ---------------------------------------------------------------------------


class _FakeHarness:
    """A stand-in for :class:`PaintHarness` — no server, no browser."""

    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)
        self.calls: list[dict[str, Any]] = []

    def paint(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        self.calls.append(dict(envelope))
        outcome = self._results.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return cast(dict[str, Any], outcome)


_PAINTED_RESULT = {
    "accepted": True,
    "painted": True,
    "compiled_row_count": 4,
    "error": None,
}
_UNPAINTED_RESULT = {
    "accepted": True,
    "painted": False,
    "compiled_row_count": 4,
    "error": None,
}


def _deterministic_record(
    request_id: str, run: int, *, bound_row_count: int = 4
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "run": run,
        "rail": "deterministic",
        "envelope": _BAR_ENVELOPE,
        "bound_row_count": bound_row_count,
    }


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


def test_run_paint_paints_every_deterministic_record(tmp_path: Path) -> None:
    rc = _tool()
    journal = tmp_path / "journal.jsonl"
    paint_journal = tmp_path / "paint_journal.jsonl"
    _write_jsonl(
        journal, [_deterministic_record("r1", 1), _deterministic_record("r1", 2)]
    )
    harness = _FakeHarness([_PAINTED_RESULT, _PAINTED_RESULT])

    records = rc.run_paint(harness, journal, paint_journal)

    assert len(records) == 2
    assert len(harness.calls) == 2
    assert records[("r1", 1)]["painted"] is True
    assert records[("r1", 1)]["compiled_row_count"] == 4
    assert records[("r1", 1)]["bound_row_count"] == 4
    assert records[("r1", 1)]["backend"] == "vegalite"
    lines = paint_journal.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_run_paint_skips_non_deterministic_records(tmp_path: Path) -> None:
    rc = _tool()
    journal = tmp_path / "journal.jsonl"
    paint_journal = tmp_path / "paint_journal.jsonl"
    _write_jsonl(
        journal,
        [{"request_id": "r1", "run": 1, "rail": None, "miss_kind": "planner_failure"}],
    )
    harness = _FakeHarness([])

    records = rc.run_paint(harness, journal, paint_journal)

    assert records == {}
    assert harness.calls == []
    assert not paint_journal.exists() or paint_journal.read_text() == ""


def test_run_paint_resumes_and_skips_already_painted_keys(tmp_path: Path) -> None:
    rc = _tool()
    journal = tmp_path / "journal.jsonl"
    paint_journal = tmp_path / "paint_journal.jsonl"
    _write_jsonl(
        journal, [_deterministic_record("r1", 1), _deterministic_record("r2", 1)]
    )
    _write_jsonl(
        paint_journal,
        [
            {
                "request_id": "r1",
                "run": 1,
                "backend": "vegalite",
                "accepted": True,
                "painted": True,
                "compiled_row_count": 4,
                "bound_row_count": 4,
                "error": None,
            }
        ],
    )
    harness = _FakeHarness([_PAINTED_RESULT])

    records = rc.run_paint(harness, journal, paint_journal)

    assert len(records) == 2
    assert len(harness.calls) == 1  # r1 run 1 was not repainted


def test_painted_false_is_journalled_like_painted_true_never_as_error(
    tmp_path: Path,
) -> None:
    rc = _tool()
    journal = tmp_path / "journal.jsonl"
    paint_journal = tmp_path / "paint_journal.jsonl"
    _write_jsonl(journal, [_deterministic_record("r1", 1)])
    harness = _FakeHarness([_UNPAINTED_RESULT])

    records = rc.run_paint(harness, journal, paint_journal)

    assert records[("r1", 1)]["painted"] is False
    assert "error" not in records[("r1", 1)] or records[("r1", 1)]["error"] is None
    lines = paint_journal.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["painted"] is False


def test_harness_exception_is_left_unjournalled_and_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = _tool()
    journal = tmp_path / "journal.jsonl"
    paint_journal = tmp_path / "paint_journal.jsonl"
    _write_jsonl(journal, [_deterministic_record("r1", 1)])
    harness = _FakeHarness([RuntimeError("the tab crashed")])

    records = rc.run_paint(harness, journal, paint_journal)

    assert records == {}
    assert not paint_journal.exists() or paint_journal.read_text() == ""
    out = capsys.readouterr().out
    assert "HARNESS_ERROR" in out
    assert "r1" in out
    assert "will retry" in out


def test_resuming_after_a_harness_error_pays_only_for_the_rest(
    tmp_path: Path,
) -> None:
    rc = _tool()
    journal = tmp_path / "journal.jsonl"
    paint_journal = tmp_path / "paint_journal.jsonl"
    _write_jsonl(journal, [_deterministic_record("r1", 1)])

    failing = _FakeHarness([RuntimeError("boom")])
    assert rc.run_paint(failing, journal, paint_journal) == {}

    succeeding = _FakeHarness([_PAINTED_RESULT])
    records = rc.run_paint(succeeding, journal, paint_journal)
    assert len(records) == 1
    assert len(succeeding.calls) == 1


# ---------------------------------------------------------------------------
# The Excel refusal: not a chart that failed to paint, a surprise that stops
# the run (ADR-0003 D7, ADR-0014 D2, ADR-0019/0021). Issue #127.
# ---------------------------------------------------------------------------


def _excel_record(request_id: str, run: int) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "run": run,
        "rail": "deterministic",
        "envelope": {"backend": "excel", "input": _BAR_INPUT},
        "bound_row_count": 4,
    }


def test_an_excel_envelope_raises_and_stops_the_run(tmp_path: Path) -> None:
    rc = _tool()
    journal = tmp_path / "journal.jsonl"
    paint_journal = tmp_path / "paint_journal.jsonl"
    _write_jsonl(journal, [_excel_record("r1", 1)])
    harness = _FakeHarness([])  # never reached — the harness is never asked

    with pytest.raises(rc.ExcelEnvelopeError) as excinfo:
        rc.run_paint(harness, journal, paint_journal)

    assert excinfo.value.request_id == "r1"
    assert excinfo.value.run == 1
    assert harness.calls == []  # never sent to the browser
    assert not paint_journal.exists() or paint_journal.read_text() == ""


def test_an_excel_envelope_never_records_painted_false(tmp_path: Path) -> None:
    rc = _tool()
    journal = tmp_path / "journal.jsonl"
    paint_journal = tmp_path / "paint_journal.jsonl"
    _write_jsonl(journal, [_excel_record("r1", 1)])
    harness = _FakeHarness([])

    with pytest.raises(rc.ExcelEnvelopeError):
        rc.run_paint(harness, journal, paint_journal)

    assert not paint_journal.exists() or paint_journal.read_text() == ""


def test_an_excel_envelope_stops_the_run_but_keeps_records_already_journalled(
    tmp_path: Path,
) -> None:
    rc = _tool()
    journal = tmp_path / "journal.jsonl"
    paint_journal = tmp_path / "paint_journal.jsonl"
    _write_jsonl(journal, [_deterministic_record("r1", 1), _excel_record("r2", 1)])
    harness = _FakeHarness([_PAINTED_RESULT])

    with pytest.raises(rc.ExcelEnvelopeError):
        rc.run_paint(harness, journal, paint_journal)

    lines = paint_journal.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["request_id"] == "r1"


def test_cmd_paint_reports_the_excel_backend_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = _tool()
    journal = tmp_path / "journal.jsonl"
    _write_jsonl(journal, [_excel_record("r1", 1)])
    paint_journal = tmp_path / "paint_journal.jsonl"

    monkeypatch.setattr(
        rc, "PaintHarness", lambda: _StubHarnessContext(_PAINTED_RESULT)
    )
    code = rc.main(
        ["paint", "--journal", str(journal), "--paint-journal", str(paint_journal)]
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "EXCEL_BACKEND" in out
    assert "r1" in out
    assert not paint_journal.exists() or paint_journal.read_text() == ""


# ---------------------------------------------------------------------------
# The CLI — stubbed harness, no browser
# ---------------------------------------------------------------------------


class _StubHarnessContext:
    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result
        self.entered = False

    def __enter__(self) -> _StubHarnessContext:
        self.entered = True
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def paint(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        return self._result


def test_cmd_paint_refuses_when_journal_is_missing(tmp_path: Path) -> None:
    rc = _tool()
    code = rc.main(
        [
            "paint",
            "--journal",
            str(tmp_path / "does-not-exist.jsonl"),
            "--paint-journal",
            str(tmp_path / "paint.jsonl"),
        ]
    )
    assert code == 1


def test_cmd_paint_refuses_on_preflight_failure_before_the_journal_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rc = _tool()
    journal = tmp_path / "journal.jsonl"
    _write_jsonl(journal, [_deterministic_record("r1", 1)])
    paint_journal = tmp_path / "paint_journal.jsonl"

    def _boom() -> Any:
        raise rc.PaintPreflightError(["FLINT_HASH bad"])

    monkeypatch.setattr(rc, "PaintHarness", _boom)
    code = rc.main(
        ["paint", "--journal", str(journal), "--paint-journal", str(paint_journal)]
    )
    assert code == 1
    assert not paint_journal.exists()


def test_cmd_paint_writes_the_paint_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rc = _tool()
    journal = tmp_path / "journal.jsonl"
    _write_jsonl(journal, [_deterministic_record("r1", 1)])
    paint_journal = tmp_path / "paint_journal.jsonl"

    monkeypatch.setattr(
        rc, "PaintHarness", lambda: _StubHarnessContext(_PAINTED_RESULT)
    )
    code = rc.main(
        ["paint", "--journal", str(journal), "--paint-journal", str(paint_journal)]
    )
    assert code == 0
    row = json.loads(paint_journal.read_text(encoding="utf-8").splitlines()[0])
    assert row == {
        "request_id": "r1",
        "run": 1,
        "backend": "vegalite",
        "accepted": True,
        "painted": True,
        "compiled_row_count": 4,
        "bound_row_count": 4,
        "error": None,
    }


def test_cmd_paint_names_unpainted_records_by_id_like_the_record_leg_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = _tool()
    journal = tmp_path / "journal.jsonl"
    _write_jsonl(journal, [_deterministic_record("r1", 1)])
    paint_journal = tmp_path / "paint_journal.jsonl"

    unpainted = {**_UNPAINTED_RESULT, "error": "no renderer vendored for backend: x"}
    monkeypatch.setattr(rc, "PaintHarness", lambda: _StubHarnessContext(unpainted))
    code = rc.main(
        ["paint", "--journal", str(journal), "--paint-journal", str(paint_journal)]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "Unpainted: 1." in out
    assert "r1 run 1" in out
    assert "no renderer vendored for backend: x" in out


def test_cmd_paint_reports_none_unpainted_when_everything_painted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = _tool()
    journal = tmp_path / "journal.jsonl"
    _write_jsonl(journal, [_deterministic_record("r1", 1)])
    paint_journal = tmp_path / "paint_journal.jsonl"

    monkeypatch.setattr(
        rc, "PaintHarness", lambda: _StubHarnessContext(_PAINTED_RESULT)
    )
    code = rc.main(
        ["paint", "--journal", str(journal), "--paint-journal", str(paint_journal)]
    )
    assert code == 0
    assert "Unpainted: none." in capsys.readouterr().out


def test_cmd_paint_one_prints_the_result_for_a_hand_written_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = _tool()
    envelope_path = tmp_path / "envelope.json"
    envelope_path.write_text(json.dumps(_BAR_ENVELOPE), encoding="utf-8")

    monkeypatch.setattr(
        rc, "PaintHarness", lambda: _StubHarnessContext(_PAINTED_RESULT)
    )
    code = rc.main(["paint-one", "--envelope", str(envelope_path)])
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == _PAINTED_RESULT


def test_cmd_paint_one_refuses_on_preflight_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rc = _tool()
    envelope_path = tmp_path / "envelope.json"
    envelope_path.write_text(json.dumps(_BAR_ENVELOPE), encoding="utf-8")

    def _boom() -> Any:
        raise rc.PaintPreflightError(["VENDOR_HASH bad"])

    monkeypatch.setattr(rc, "PaintHarness", _boom)
    code = rc.main(["paint-one", "--envelope", str(envelope_path)])
    assert code == 1


# ---------------------------------------------------------------------------
# The real thing: one pinned Chromium tab, shared across the tests below.
# A preflight failure is a real bug and is never skipped; only a missing
# local Chromium install is.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def harness() -> Iterator[Any]:
    rc = _tool()
    instance = rc.PaintHarness()  # raises PaintPreflightError on bad vendor bytes
    try:
        entered = instance.__enter__()
    except Exception as exc:  # noqa: BLE001 — environment gap, not a code bug
        pytest.skip(f"Chromium is not available for the paint harness: {exc}")
        return
    try:
        yield entered
    finally:
        instance.__exit__(None, None, None)


def test_clean_paint_reports_accepted_painted_and_matching_row_counts(
    harness: Any,
) -> None:
    result = harness.paint(_BAR_ENVELOPE)
    assert result == {
        "accepted": True,
        "painted": True,
        "compiled_row_count": 4,
        "error": None,
    }


def test_a_short_compiled_row_count_is_reported_not_hidden(harness: Any) -> None:
    # 200 categories at a canvas too small to fit them all — Flint's layout
    # optimiser silently drops rows (ADR-0014 D10's own example).
    dense = {
        "backend": "vegalite",
        "input": _dense_input(200, width=200, height=150),
    }
    result = harness.paint(dense)
    assert result["accepted"] is True
    assert result["painted"] is True
    assert result["compiled_row_count"] is not None
    assert result["compiled_row_count"] < 200


def test_canvas_size_is_derived_from_base_size_not_imposed_by_the_harness(
    harness: Any,
) -> None:
    small = harness.paint(
        {"backend": "vegalite", "input": _dense_input(200, width=200, height=150)}
    )
    large = harness.paint(
        {"backend": "vegalite", "input": _dense_input(200, width=4000, height=3000)}
    )
    assert small["compiled_row_count"] < large["compiled_row_count"]
    assert large["compiled_row_count"] == 200


def test_an_unknown_chart_type_is_not_accepted_and_not_painted(harness: Any) -> None:
    bad_input = json.loads(json.dumps(_BAR_INPUT))
    bad_input["chart_spec"]["chartType"] = "Not A Real Chart Type"
    result = harness.paint({"backend": "vegalite", "input": bad_input})
    assert result["accepted"] is False
    assert result["painted"] is False
    assert result["compiled_row_count"] is None
    assert result["error"]


def test_the_backend_the_envelope_names_is_the_one_rendered(harness: Any) -> None:
    # No stand-in (ADR-0003 D3): an ECharts envelope is compiled by Flint's
    # ECharts assembler and painted by the vendored ECharts renderer, never
    # silently substituted with Vega-Lite's.
    result = harness.paint({"backend": "echarts", "input": _BAR_INPUT})
    assert result == {
        "accepted": True,
        "painted": True,
        "compiled_row_count": 4,
        "error": None,
    }


def test_excel_is_reported_as_never_rasterised_not_merely_unvendored(
    harness: Any,
) -> None:
    # ADR-0003 D7: Excel is not a raster target and never will be — a
    # distinct fact from "no renderer vendored for this backend yet", which
    # is what every other backend was before it got one (#126, #127). This
    # is the raw harness's own fallback message; the corpus recorder never
    # reaches it (see the ExcelEnvelopeError tests below), because it stops
    # the run before handing an excel envelope to the harness at all.
    result = harness.paint({"backend": "excel", "input": _BAR_INPUT})
    assert result["accepted"] is True
    assert result["painted"] is False
    assert result["compiled_row_count"] == 4
    assert result["error"] and "ADR-0003" in result["error"]


# ---------------------------------------------------------------------------
# The remaining renderer families — ECharts and Chart.js draw to canvas (a
# non-blank pixel scan), Plotly draws to SVG (the same mark-vs-chrome scan
# as Vega-Lite, scoped to Plotly's own `trace` class). issue #127. ECharts'
# own clean paint is already covered above by
# test_the_backend_the_envelope_names_is_the_one_rendered.
# ---------------------------------------------------------------------------


def test_clean_paint_chartjs(harness: Any) -> None:
    result = harness.paint({"backend": "chartjs", "input": _BAR_INPUT})
    assert result == {
        "accepted": True,
        "painted": True,
        "compiled_row_count": 4,
        "error": None,
    }


def test_clean_paint_plotly(harness: Any) -> None:
    result = harness.paint({"backend": "plotly", "input": _BAR_INPUT})
    assert result == {
        "accepted": True,
        "painted": True,
        "compiled_row_count": 4,
        "error": None,
    }


def test_a_rendered_but_blank_chart_is_reported_not_hidden(harness: Any) -> None:
    # assembler accepts, renders, no marks (acceptance table row 3): zero
    # data rows compiles to a valid Vega-Lite spec with axes but nothing in
    # any `g.role-mark` group.
    empty_input = json.loads(json.dumps(_BAR_INPUT))
    empty_input["data"]["values"] = []
    result = harness.paint({"backend": "vegalite", "input": empty_input})
    assert result["accepted"] is True
    assert result["painted"] is False
    assert result["compiled_row_count"] == 0
    assert result["error"] is None


def test_a_renderer_exception_is_reported_as_accepted_but_unpainted(
    harness: Any,
) -> None:
    # assembler accepts, renderer throws (acceptance table row 2): Flint's
    # ECharts assembler happily compiles a cyclic Sankey — it does not
    # validate DAG-ness — but ECharts' own layout engine raises when it
    # actually lays the graph out.
    cyclic_sankey_input = {
        "data": {
            "values": [
                {"src": "A", "dst": "B", "flow": 10},
                {"src": "B", "dst": "A", "flow": 5},
            ]
        },
        "semantic_types": {"src": "Source", "dst": "Target", "flow": "Value"},
        "chart_spec": {
            "chartType": "Sankey Diagram",
            "encodings": {
                "x": {"field": "src"},
                "y": {"field": "dst"},
                "size": {"field": "flow"},
            },
            "baseSize": {"width": 480, "height": 320},
        },
    }
    result = harness.paint({"backend": "echarts", "input": cyclic_sankey_input})
    assert result["accepted"] is True
    assert result["painted"] is False
    assert result["compiled_row_count"] == 2
    assert result["error"] and "cycle" in result["error"].lower()


def test_an_unknown_backend_name_is_rejected(harness: Any) -> None:
    result = harness.paint({"backend": "not-a-backend", "input": _BAR_INPUT})
    assert result["accepted"] is False
    assert result["painted"] is False
    assert "not-a-backend" in (result["error"] or "")


def test_no_network_fetch_leaves_the_harness_page(harness: Any) -> None:
    """Every script the harness loads is same-origin; nothing else is ever
    requested (ADR-0003 D5's "never a CDN, never an npm resolve")."""
    page = harness._page
    urls: list[str] = page.evaluate(
        "performance.getEntriesByType('resource').map((e) => e.name)"
    )
    origin = page.url.rsplit("/", 1)[0]
    assert urls, "expected the harness to have loaded its own scripts"
    assert all(url.startswith(origin) for url in urls)
