"""Paint leg: compile and paint one envelope in a pinned browser harness.

ADR-0003 Decisions 3, 4, 5, 6 and 7; ADR-0014 D10, D11; ADR-0019; ADR-0021.
Issues #126, #127 (parent #122).

    python tools/paint_corpus.py paint
    python tools/paint_corpus.py paint-one --envelope path/to/envelope.json

The ``paint`` verb reads the record leg's journal
(``build/corpus/journal.jsonl``, ``tools/record_corpus.py``) and, for every
``(request_id, run)`` whose recorded outcome carries a compiled envelope
(``rail: "deterministic"``), paints it in a Chromium tab running the pinned
client harness at ``tools/paint/harness.html`` and appends one record to its
own journal (``build/corpus/paint_journal.jsonl``). Re-running skips any
``(request_id, run)`` already there — a bug in the paint predicate costs
nothing already paid for. Misses (``rail: null``) have no envelope and are
never painted; that absence is delivery rate's own denominator exclusion
(ADR-0014 Decision 10), not a gap here.

Before anything is served, the harness refuses to run unless the vendored
Flint IIFE's sha256 matches the value ``vocab.json`` records, and unless
every vendored Vega / Vega-Lite / Vega-Embed / ECharts / Chart.js / Plotly
file matches ``tools/paint/vendor/vendor.json`` — never a CDN, never an npm
resolve (ADR-0003 Decision 5). Every file the harness page loads is served
over a loopback HTTP server straight from those same vendored bytes, and
the page is additionally blocked from making any request that is not to
that server.

The backend rendered is always the one the envelope names (ADR-0003
Decision 3 — no stand-in, ever), and ``canvasSize`` is derived from the
envelope's own ``chart_spec.baseSize`` by ``tools/flint-predicates.mjs``'s
``pinSize`` — the harness never imposes one of its own (ADR-0014 D10).

``painted`` is a positive assertion, never the absence of an exception
(ADR-0003's stated hazard: a rasteriser can return bytes without having
rendered anything) — but it is asserted two different ways depending on
how the backend actually draws (issue #127), because forcing every backend
onto one rendering mode would mean measuring something other than what the
client runs (ADR-0003 D4). Vega-Lite and Plotly draw to SVG and keep a DOM,
so their predicate is at least one geometry node inside the library's own
mark-group class (Vega's ``role-mark``, Plotly's ``trace``) — chrome like
axes and legends sits outside it. ECharts and Chart.js draw to canvas and
keep no such DOM; their predicate is the coarser one a raster surface
allows, a non-blank scan of the canvas's own pixels. ``painted: false`` is
a legitimate recorded outcome either way, journalled exactly like
``painted: true``, never an error and never retried — including the many
real ECharts boxplot envelopes this reports unpainted; that is the cell-3
case ADR-0014 asks to be measured, not retried away. ``compiled_row_count``
comes from ``tools/flint-predicates.mjs``'s ``rowCount``, the same function
the fixture CI job uses.

A harness-level failure — the browser process dying, a JS exception
escaping ``window.__paint`` itself — is different from a *reported*
``painted: false``: it leaves the attempt unjournalled so a later
invocation retries it for free, and is printed by name rather than
silently swallowed.

A record naming the Excel backend is different again. Excel is not a
raster target and never will be (ADR-0003 Decision 7); under ADR-0019 /
ADR-0021 the ranking never selects it, and no corpus slot names a backend
(ADR-0014 Decision 11). Such a record is a surprise that invalidates the
delivery reading, not a chart that failed to paint — recording
``painted: false`` would charge the planner for a rasterisation gap this
project chose, not one it hit. ``run_paint`` raises
:class:`ExcelEnvelopeError` and stops immediately, before the harness is
ever asked to paint it; records already journalled earlier in the same run
are kept.

Exit 0 = the run finished.
Exit 1 = a named pre-flight check failed (the browser never launched), or a
record named the Excel backend (the run stopped; already-journalled
records are kept).
Exit 2 = usage error.

Adds nothing to ``chartagent.__all__`` — no ``Rasteriser`` protocol, no
public paint helper. That is a P2 decision under ADR-0003, not this tool's.
"""

from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import sys
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from chartagent._flint import flint_bundle

REPO = Path(__file__).resolve().parents[1]
_TOOLS_DIR = Path(__file__).resolve().parent
PAINT_DIR = _TOOLS_DIR / "paint"
HARNESS_HTML = PAINT_DIR / "harness.html"
VENDOR_DIR = PAINT_DIR / "vendor"
VENDOR_PIN = VENDOR_DIR / "vendor.json"
PREDICATES = _TOOLS_DIR / "flint-predicates.mjs"

DEFAULT_JOURNAL = REPO / "build" / "corpus" / "journal.jsonl"
DEFAULT_PAINT_JOURNAL = REPO / "build" / "corpus" / "paint_journal.jsonl"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json",
}


def _fail(issues: list[str]) -> int:
    for line in issues:
        print(line)
    print(f"\nFAIL — {len(issues)} check(s) failed.")
    return 1


def check_flint_hash() -> list[str]:
    """Refuse to run unless the vendored IIFE matches ``vocab.json``'s pin."""
    bundle = flint_bundle()
    actual = hashlib.sha256(bundle.read_bytes()).hexdigest()
    if actual != bundle.sha256:
        return [
            f"FLINT_HASH         {bundle.path} sha256 {actual}, "
            f"want {bundle.sha256} as recorded in vocab.json"
        ]
    return []


def _vendor_pin() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(VENDOR_PIN.read_text(encoding="utf-8")))


def check_vendor_hashes() -> list[str]:
    """Refuse to run unless every vendored renderer file matches its pin."""
    issues: list[str] = []
    for name, record in _vendor_pin().items():
        if name.startswith("_"):
            continue
        path = VENDOR_DIR / record["file"]
        if not path.is_file():
            issues.append(f"VENDOR_MISSING     {name}: {path} is missing")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != record["sha256"]:
            issues.append(
                f"VENDOR_HASH        {name}: {path} sha256 {actual}, "
                f"want {record['sha256']}"
            )
    return issues


def preflight() -> list[str]:
    return check_flint_hash() + check_vendor_hashes()


# ---------------------------------------------------------------------------
# The loopback server — routes are the exact vendored files preflight() has
# already hashed. Nothing else is servable.
# ---------------------------------------------------------------------------


def _routes() -> dict[str, Path]:
    routes = {
        "/harness.html": HARNESS_HTML,
        "/flint.iife.js": flint_bundle().path,
        "/flint-predicates.mjs": PREDICATES,
    }
    for name, record in _vendor_pin().items():
        if name.startswith("_"):
            continue
        routes[f"/vendor/{record['file']}"] = VENDOR_DIR / record["file"]
    return routes


def _make_handler(
    routes: Mapping[str, Path],
) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            file_path = routes.get(self.path)
            if file_path is None or not file_path.is_file():
                self.send_error(404)
                return
            body = file_path.read_bytes()
            content_type = _CONTENT_TYPES.get(
                file_path.suffix, "application/octet-stream"
            )
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass  # keep CLI/test output free of per-request access logs

    return Handler


class PaintPreflightError(Exception):
    """Raised when the vendored-bytes check fails; nothing was launched."""

    def __init__(self, issues: list[str]) -> None:
        super().__init__("; ".join(issues))
        self.issues = issues


class PaintHarness:
    """One Chromium tab loaded with the pinned client harness.

    A context manager::

        with PaintHarness() as harness:
            result = harness.paint({"backend": "vegalite", "input": {...}})

    Raises :class:`PaintPreflightError` before anything is served or
    launched if the vendored-bytes check fails. Starts a loopback HTTP
    server serving only those already-verified bytes, and blocks every
    browser request that is not to that server (ADR-0003 Decision 5's
    "never a CDN, never an npm resolve").
    """

    def __init__(self) -> None:
        issues = preflight()
        if issues:
            raise PaintPreflightError(issues)
        self._server: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None

    def __enter__(self) -> PaintHarness:
        # Python's context-manager protocol never calls __exit__ when
        # __enter__ itself raises (e.g. Chromium not installed) — so
        # anything already started here (the server thread, the Playwright
        # driver) is torn down by hand on the way out, via the same
        # __exit__ a clean run would use.
        try:
            self._start()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def _start(self) -> None:
        from playwright.sync_api import sync_playwright

        handler = _make_handler(_routes())
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        port = self._server.server_address[1]
        origin = f"http://127.0.0.1:{port}"

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch()
        self._page = self._browser.new_page()

        def _route(route: Any) -> None:
            if route.request.url.startswith(origin + "/"):
                route.continue_()
            else:
                route.abort()

        self._page.route("**/*", _route)
        self._page.goto(f"{origin}/harness.html")
        self._page.wait_for_function("window.__ready === true")

    def paint(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        """Compile and paint one envelope. ``envelope`` needs only
        ``backend`` and ``input`` — the rest of the wire envelope, if
        present, is ignored."""
        assert self._page is not None, "paint() called outside `with PaintHarness()`"
        payload = {"backend": envelope["backend"], "input": envelope["input"]}
        result = self._page.evaluate("(envelope) => window.__paint(envelope)", payload)
        return cast(dict[str, Any], result)

    def __exit__(self, *exc_info: object) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)


# ---------------------------------------------------------------------------
# The journal — read the record leg's, write our own, resumable by the same
# (request_id, run) key.
# ---------------------------------------------------------------------------


def _record_key(record: Mapping[str, Any]) -> tuple[str, int]:
    return (str(record["request_id"]), int(record["run"]))


def _read_jsonl(path: Path) -> dict[tuple[str, int], dict[str, Any]]:
    if not path.is_file():
        return {}
    records: dict[tuple[str, int], dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        records[_record_key(record)] = record
    return records


class ExcelEnvelopeError(Exception):
    """Raised when a deterministic-rail record names the Excel backend.

    Excel is not a raster target and never will be (ADR-0003 Decision 7);
    under ADR-0019/0021 the ranking never selects it, and no corpus slot
    names a backend (ADR-0014 Decision 11). A record naming it here is a
    surprise that invalidates the delivery reading, not a chart that
    failed to paint — recording ``painted: false`` would charge the
    planner for a rasterisation gap this project chose, not one it hit.
    The run stops here rather than journalling anything for it.
    """

    def __init__(self, request_id: str, run: int) -> None:
        self.request_id = request_id
        self.run = run
        super().__init__(
            f"{request_id} run {run} names the excel backend — not a raster "
            "target (ADR-0003 D7) and never selected by the ranking "
            "(ADR-0019/0021); this is a surprise that invalidates the "
            "delivery reading, not a paint failure"
        )


def paint_one(harness: PaintHarness, record: Mapping[str, Any]) -> dict[str, Any]:
    """Paint one ``rail: "deterministic"`` record from the record leg's
    journal and map it to a paint-journal row."""
    envelope = record["envelope"]
    result = harness.paint(envelope)
    return {
        "request_id": record["request_id"],
        "run": record["run"],
        "backend": envelope["backend"],
        "accepted": result["accepted"],
        "painted": result["painted"],
        "compiled_row_count": result["compiled_row_count"],
        "bound_row_count": record.get("bound_row_count"),
        "error": result.get("error"),
    }


def run_paint(
    harness: PaintHarness,
    journal_path: Path,
    paint_journal_path: Path,
) -> dict[tuple[str, int], dict[str, Any]]:
    """Paint every deterministic-rail record the paint journal lacks.

    Skips any ``(request_id, run)`` already in the paint journal, and every
    record whose rail is not ``"deterministic"`` (a miss has no envelope to
    paint). A harness-level exception is printed by name and left out of
    both the journal and the returned mapping — it costs nothing already
    paid for and is retried on the next invocation. Returns every record
    the paint journal now holds, old and new.

    A record naming the Excel backend is different from either of those: it
    raises :class:`ExcelEnvelopeError` and stops the run immediately,
    *before* the harness is asked to paint it, rather than being journalled
    as ``painted: false`` (ADR-0003 Decision 7; ADR-0014 Decision 11).
    Records already journalled from earlier in this same call are kept.
    """
    source = _read_jsonl(journal_path)
    records = _read_jsonl(paint_journal_path)
    paint_journal_path.parent.mkdir(parents=True, exist_ok=True)
    with paint_journal_path.open("a", encoding="utf-8") as handle:
        for key, record in source.items():
            if record.get("rail") != "deterministic":
                continue
            if key in records:
                continue
            if record["envelope"]["backend"] == "excel":
                raise ExcelEnvelopeError(record["request_id"], record["run"])
            try:
                outcome = paint_one(harness, record)
            except Exception as exc:  # noqa: BLE001 — a harness fault, not a paint outcome
                print(
                    f"HARNESS_ERROR      {key[0]} run {key[1]}: "
                    f"{type(exc).__name__}: {exc} — left unjournalled, "
                    "will retry on the next invocation"
                )
                continue
            handle.write(json.dumps(outcome) + "\n")
            handle.flush()
            records[key] = outcome
    return records


def _print_unpainted_summary(
    records: dict[tuple[str, int], dict[str, Any]],
) -> None:
    """Name every unpainted record, the way the record leg names its
    residual errors — ``painted: false`` is a legitimate outcome, not a
    failure, but it is still worth a reader's attention by id."""
    unpainted = [record for record in records.values() if not record["painted"]]
    if not unpainted:
        print("Unpainted: none.")
        return
    unpainted.sort(key=lambda record: (record["request_id"], record["run"]))
    print(f"Unpainted: {len(unpainted)}.")
    for record in unpainted:
        reason = record.get("error") or (
            "compile rejected" if not record["accepted"] else "no marks"
        )
        print(
            f"  {record['request_id']} run {record['run']} "
            f"({record['backend']}): {reason}"
        )


def _cmd_paint(ns: argparse.Namespace) -> int:
    journal_path = Path(ns.journal)
    paint_journal_path = Path(ns.paint_journal)
    if not journal_path.is_file():
        return _fail(
            [
                f"JOURNAL            {journal_path} is missing — "
                "run the record leg first (tools/record_corpus.py)"
            ]
        )
    try:
        with PaintHarness() as harness:
            records = run_paint(harness, journal_path, paint_journal_path)
    except PaintPreflightError as exc:
        return _fail(exc.issues)
    except ExcelEnvelopeError as exc:
        return _fail([f"EXCEL_BACKEND      {exc}"])
    painted = sum(1 for record in records.values() if record["painted"])
    _print_unpainted_summary(records)
    print(
        f"OK — {len(records)} attempt(s) journalled at {paint_journal_path}, "
        f"{painted} painted"
    )
    return 0


def _cmd_paint_one(ns: argparse.Namespace) -> int:
    envelope_path = Path(ns.envelope)
    envelope = cast(
        dict[str, Any], json.loads(envelope_path.read_text(encoding="utf-8"))
    )
    try:
        with PaintHarness() as harness:
            result = harness.paint(envelope)
    except PaintPreflightError as exc:
        return _fail(exc.issues)
    print(json.dumps(result, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="paint_corpus.py")
    sub = parser.add_subparsers(dest="verb", required=True)

    paint = sub.add_parser(
        "paint",
        help="Paint every deterministic-rail record the record leg's "
        "journal carries and the paint journal does not.",
    )
    paint.add_argument("--journal", default=str(DEFAULT_JOURNAL))
    paint.add_argument("--paint-journal", default=str(DEFAULT_PAINT_JOURNAL))

    paint_one_parser = sub.add_parser(
        "paint-one",
        help="Paint a single hand-written envelope, for debugging. "
        "No corpus, no journal.",
    )
    paint_one_parser.add_argument(
        "--envelope", required=True, help="Path to a JSON {backend, input} envelope."
    )

    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 2

    if ns.verb == "paint":
        return _cmd_paint(ns)
    if ns.verb == "paint-one":
        return _cmd_paint_one(ns)
    return 2  # pragma: no cover — argparse enforces a known verb


if __name__ == "__main__":
    raise SystemExit(main())
