#!/usr/bin/env python3
"""
PROTOTYPE — THROWAWAY. Evidence for the V8-embed research ticket (#29).

Each engine runs in its own subprocess so a hang or SIGSEGV is observed, not
suffered. MiniRacer launches a background event loop; we always close it.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time

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
    ]},
    "semantic_types": {"quarter": "Quarter", "revenue": "Revenue"},
    "chart_spec": {
        "chartType": "Bar Chart", "title": "Revenue",
        "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
        "baseSize": {"width": 480, "height": 320},
    },
}
DATE_JS = r"""
({
  parse: Date.parse("Jan 2020"),
  iso: Date.parse("2020-01"),
  asString: String(new Date("Jan 2020")),
  tag: Object.prototype.toString.call(new Date("Jan 2020")),
})
"""

ENGINES = ("miniracer", "stpyv8", "quickjs_rs")


def src() -> str:
    if not BUNDLE.exists():
        sys.exit(f"missing {BUNDLE} — run ../flint-embed/setup.sh")
    return BUNDLE.read_text()


def run_miniracer() -> None:
    from py_mini_racer import MiniRacer

    t0 = time.perf_counter()
    ctx = MiniRacer()
    boot = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    ctx.eval(POLYFILL)
    ctx.eval(src())
    ctx.eval(GLUE)
    load = (time.perf_counter() - t0) * 1000
    dates = ctx.eval("JSON.stringify(" + DATE_JS + ")")
    t0 = time.perf_counter()
    out = json.loads(ctx.call("compile", json.dumps(SAMPLE), "vegalite"))
    compile_ms = (time.perf_counter() - t0) * 1000
    print(f"  MiniRacer() {boot:.0f} ms; bundle eval {load:.0f} ms; "
          f"first compile {compile_ms:.2f} ms; keys {list(out)[:6]}")
    print(f"  dates: {dates}")
    print(f"  x.type: {out['encoding']['x']['type']}")
    ctx2 = MiniRacer()
    ctx2.eval(POLYFILL)
    ctx2.eval(src())
    ctx2.eval(GLUE)
    print("  second isolate: ok")
    ctx.close()
    ctx2.close()


def run_stpyv8() -> None:
    import STPyV8

    t0 = time.perf_counter()
    with STPyV8.JSIsolate():
        with STPyV8.JSContext() as ctx:
            boot = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter()
            ctx.eval(POLYFILL)
            ctx.eval(src())
            ctx.eval(GLUE)
            load = (time.perf_counter() - t0) * 1000
            raw_dates = ctx.eval(DATE_JS)
            dates = dict(raw_dates) if hasattr(raw_dates, "keys") else raw_dates
            compile = ctx.eval("compile")
            t0 = time.perf_counter()
            raw = compile(json.dumps(SAMPLE), "vegalite")
            compile_ms = (time.perf_counter() - t0) * 1000
            out = json.loads(str(raw))
            print(f"  JSIsolate+JSContext {boot:.0f} ms; bundle eval {load:.0f} ms; "
                  f"first compile {compile_ms:.2f} ms; keys {list(out)[:6]}")
            print(f"  dates: {dates}")
            print(f"  x.type: {out['encoding']['x']['type']}")


def run_quickjs_rs() -> None:
    from quickjs_rs import Runtime

    t0 = time.perf_counter()
    with Runtime(memory_limit=256 * 1024 * 1024) as rt:
        ctx = rt.new_context(timeout=60.0)
        boot = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        ctx.eval(POLYFILL + ";0")
        ctx.eval(src() + ";0")
        ctx.eval(GLUE + ";0")
        load = (time.perf_counter() - t0) * 1000
        dates = ctx.eval("JSON.stringify(" + DATE_JS + ")")
        payload = json.dumps(json.dumps(SAMPLE))
        t0 = time.perf_counter()
        raw = ctx.eval(f"compile({payload}, 'vegalite')")
        compile_ms = (time.perf_counter() - t0) * 1000
        out = json.loads(raw) if isinstance(raw, str) else raw
        print(f"  Runtime+Context {boot:.0f} ms; bundle eval {load:.0f} ms; "
              f"first compile {compile_ms:.2f} ms")
        print(f"  dates: {dates}")
        if isinstance(out, dict):
            print(f"  keys {list(out)[:6]}")
            enc = out.get("encoding") or {}
            print(f"  x.type: {(enc.get('x') or {}).get('type')}")


HANDLERS = {
    "miniracer": run_miniracer,
    "stpyv8": run_stpyv8,
    "quickjs_rs": run_quickjs_rs,
}


def main() -> None:
    if len(sys.argv) > 1:
        HANDLERS[sys.argv[1]]()
        return
    for name in ENGINES:
        print(f"{name}:")
        r = subprocess.run([sys.executable, __file__, name],
                           capture_output=True, text=True, timeout=120)
        sys.stdout.write(r.stdout)
        if r.returncode == 0:
            print("  => ok")
        else:
            print(f"  => FAIL exit {r.returncode}"
                  f"{' (signal)' if r.returncode < 0 else ''}")
            err = (r.stderr or "").strip().splitlines()
            for line in err[-8:]:
                print(f"     {line[:160]}")


if __name__ == "__main__":
    main()
