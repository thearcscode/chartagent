#!/usr/bin/env python3
"""
PROTOTYPE — THROWAWAY. Evidence for the V8-embed research ticket (#29).

ADR-0001 asserts two different crash claims. Only the first is evidenced:

  1. Sharing a QuickJS context across threads is a SIGSEGV. (harness.py bench)
  2. "The two engines segfault if imported into the same interpreter." (a note)

#22's coload_probe.py never included a quickjs↔pythonmonkey control pairing,
and its workload was a 6×7 eval — too light to trust a "survived" result.

This probe:

  - Runs every pairing in its own subprocess so a signal is observed.
  - Includes the missing quickjs↔pythonmonkey control, both orders.
  - Adds mini-racer and STPyV8 as V8 bindings, plus vl-convert's embedded V8.
  - Sweeps four intensities: import-only, trivial eval, Flint compile ×200,
    and four threads each compiling.

    python coload_probe.py                         # full matrix
    python coload_probe.py <pairing> <intensity>   # one cell, in-process
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import threading

HERE = pathlib.Path(__file__).resolve().parent
EMBED = HERE.parent / "flint-embed"
BUNDLE = EMBED / "build" / "flint.iife.js"

POLYFILL = (
    "globalThis.structuredClone=function(o){"
    "return o===undefined?undefined:JSON.parse(JSON.stringify(o));};"
)
GLUE = """
globalThis.compile = function (inputJson, backend) {
  var assemble = {
    vegalite: Flint.assembleVegaLite, echarts: Flint.assembleECharts,
    chartjs:  Flint.assembleChartjs,  plotly:  Flint.assemblePlotly,
    excel:    Flint.assembleExcel,
  }[backend];
  return JSON.stringify(assemble(JSON.parse(inputJson)));
};
"""
SAMPLE = {
    "data": {"values": [
        {"quarter": "Q1", "revenue": 1200}, {"quarter": "Q2", "revenue": 1450},
        {"quarter": "Q3", "revenue": 980}, {"quarter": "Q4", "revenue": 1800},
    ]},
    "semantic_types": {"quarter": "Quarter", "revenue": "Revenue"},
    "chart_spec": {
        "chartType": "Bar Chart", "title": "Revenue by quarter",
        "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
        "baseSize": {"width": 480, "height": 320},
    },
}
VL_SPEC = json.dumps({
    "data": {"values": [{"a": "A", "b": 28}, {"a": "B", "b": 55}]},
    "mark": "bar",
    "encoding": {"x": {"field": "a", "type": "nominal"},
                 "y": {"field": "b", "type": "quantitative"}},
})

# Engines that can co-exist in one process, in theory. Pairings are ordered.
ENGINES = ("quickjs", "pythonmonkey", "miniracer", "stpyv8", "vlconvert")
INTENSITIES = ("import", "eval", "compile", "threads")

# Full cartesian of distinct ordered pairs would be 20 × 4 = 80 cells.
# That's ~10+ minutes if compile is 200× Flint. Restrict to:
#   - the ADR-0001 control (both orders)
#   - each V8 binding crossed with each of the two ADR engines (both orders)
#   - vl-convert crossed with each of the two ADR engines and with miniracer
#   - same-engine sanity (miniracer twice) is not a pairing
PAIRINGS = [
    "quickjs-then-pythonmonkey",
    "pythonmonkey-then-quickjs",
    "quickjs-then-miniracer",
    "miniracer-then-quickjs",
    "pythonmonkey-then-miniracer",
    "miniracer-then-pythonmonkey",
    "quickjs-then-stpyv8",
    "stpyv8-then-quickjs",
    "pythonmonkey-then-stpyv8",
    "stpyv8-then-pythonmonkey",
    "quickjs-then-vlconvert",
    "vlconvert-then-quickjs",
    "pythonmonkey-then-vlconvert",
    "vlconvert-then-pythonmonkey",
    "miniracer-then-vlconvert",
    "vlconvert-then-miniracer",
    "miniracer-then-stpyv8",
    "stpyv8-then-miniracer",
]


class Handle:
    def __init__(self, name: str, intensity: str) -> None:
        self.name = name
        self.intensity = intensity
        self._obj = None

    def start(self) -> None:
        if self.name == "quickjs":
            import quickjs
            self._obj = quickjs
            if self.intensity == "import":
                return
            self._ctx = quickjs.Context()
            if self.intensity == "eval":
                self._ctx.eval("globalThis.f = function () { return 6 * 7; };")
                assert self._ctx.get("f")() == 42
                return
            src = BUNDLE.read_text()
            for chunk in (POLYFILL, src, GLUE):
                self._ctx.eval(chunk)
            self._compile = self._ctx.get("compile")
        elif self.name == "pythonmonkey":
            import pythonmonkey as pm
            self._obj = pm
            if self.intensity == "import":
                return
            if self.intensity == "eval":
                assert pm.eval("6 * 7") == 42
                return
            src = BUNDLE.read_text()
            for chunk in (POLYFILL, src, GLUE):
                pm.eval(chunk)
            self._compile = pm.eval("globalThis.compile")
        elif self.name == "miniracer":
            from py_mini_racer import MiniRacer
            if self.intensity == "import":
                import py_mini_racer  # noqa: F401
                return
            self._ctx = MiniRacer()
            if self.intensity == "eval":
                assert self._ctx.eval("6 * 7") == 42
                return
            src = BUNDLE.read_text()
            for chunk in (POLYFILL, src, GLUE):
                self._ctx.eval(chunk)
            self._compile = lambda spec, backend: self._ctx.call("compile", spec, backend)
        elif self.name == "stpyv8":
            import STPyV8
            self._isolate = STPyV8.JSIsolate()
            self._isolate.enter()
            self._lock_ctx = STPyV8.JSContext()
            self._lock_ctx.enter()
            if self.intensity == "import":
                return
            if self.intensity == "eval":
                assert int(self._lock_ctx.eval("6 * 7")) == 42
                return
            src = BUNDLE.read_text()
            for chunk in (POLYFILL, src, GLUE):
                self._lock_ctx.eval(chunk)
            fn = self._lock_ctx.eval("compile")
            self._compile = lambda spec, backend, fn=fn: fn(spec, backend)
        elif self.name == "vlconvert":
            import vl_convert as vlc
            self._obj = vlc
            if self.intensity in ("import", "eval"):
                return
            self._compile = lambda spec, backend: vlc.vegalite_to_png(
                vl_spec=VL_SPEC, vl_version="6.4")
        else:
            raise ValueError(self.name)

    def work(self, n: int = 200) -> None:
        if self.intensity in ("import", "eval"):
            return
        if self.name == "vlconvert":
            for _ in range(min(n, 20)):
                self._compile(None, None)
            return
        spec = json.dumps(SAMPLE)
        for _ in range(n):
            self._compile(spec, "vegalite")

    def close(self) -> None:
        ctx = getattr(self, "_ctx", None)
        if ctx is not None and hasattr(ctx, "close"):
            ctx.close()
        lock_ctx = getattr(self, "_lock_ctx", None)
        if lock_ctx is not None:
            lock_ctx.leave()
        isolate = getattr(self, "_isolate", None)
        if isolate is not None:
            isolate.leave()


def run_one(pairing: str, intensity: str) -> None:
    a, b = pairing.split("-then-")
    first, second = Handle(a, intensity), Handle(b, intensity)
    first.start()
    print(f"    {a} started")
    second.start()
    print(f"    {b} started")
    if intensity == "compile":
        first.work(200)
        second.work(200)
        print("    compile load done")
    elif intensity == "threads":
        # One thread per engine, each with its own handle. Sharing a QuickJS
        # context across threads is a known SIGSEGV (harness.py bench) and
        # must not be mixed into this cell — that would confound co-load
        # with the already-evidenced hazard.
        def go(h: Handle) -> None:
            h.work(80)
        threads = [
            threading.Thread(target=go, args=(first,)),
            threading.Thread(target=go, args=(second,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        print("    concurrent compile (one thread per engine) done")
    first.close()
    second.close()
    print("    survived")


def main() -> None:
    if len(sys.argv) >= 3:
        run_one(sys.argv[1], sys.argv[2])
        return
    if len(sys.argv) == 2:
        sys.exit("usage: coload_probe.py [<pairing> <intensity>]")

    timeout = {"import": 30, "eval": 60, "compile": 180, "threads": 180}
    print(f"{len(PAIRINGS)} pairings × {len(INTENSITIES)} intensities\n")
    crashes = []
    for pairing in PAIRINGS:
        for intensity in INTENSITIES:
            cell = f"{pairing} / {intensity}"
            r = subprocess.run(
                [sys.executable, __file__, pairing, intensity],
                capture_output=True, text=True,
                timeout=timeout[intensity],
            )
            if r.returncode == 0:
                verdict = "ok"
            elif r.returncode < 0:
                verdict = f"KILLED signal {-r.returncode}"
                crashes.append(cell)
            else:
                verdict = f"exit {r.returncode}"
                crashes.append(cell)
            print(f"{cell:55s} {verdict}")
            if r.returncode != 0:
                err = (r.stderr or r.stdout or "").strip().splitlines()
                for line in err[-3:]:
                    print(f"    {line[:140]}")
    print()
    if crashes:
        print(f"{len(crashes)} cells failed:")
        for c in crashes:
            print(f"  {c}")
    else:
        print("all cells survived")


if __name__ == "__main__":
    main()
