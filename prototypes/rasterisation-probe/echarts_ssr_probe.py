#!/usr/bin/env python3
"""
PROTOTYPE — THROWAWAY. Evidence for the rasterisation research ticket (#22).

Question: ECharts 5.3+ ships a *zero-dependency* server-side SVG renderer
(`init(null, null, {renderer: 'svg', ssr: true})` -> `renderToSVGString()`) that
the handbook says needs neither JSDOM nor node-canvas. If that is true of the
*runtime* and not merely of Node, it should also run inside the embedded engine
ADR-0001 already puts in the CPython process — giving an ECharts raster path
with no Node and no browser.

    python echarts_ssr_probe.py quickjs
    python echarts_ssr_probe.py pythonmonkey

Never run both in one interpreter: ADR-0001 records that co-loading segfaults.
Renders the ECharts option objects Flint 0.5.1 actually emits, read from
`build/echarts_specs.json` (produced by `dump_echarts.py`).
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ECHARTS = HERE / "build" / "npm" / "package" / "dist" / "echarts.js"
SPECS = HERE / "build" / "echarts_specs.json"

# QuickJS lacks structuredClone (ADR-0001). The UMD wrapper in dist/echarts.js
# looks for CommonJS/AMD first; in a bare realm neither exists, so it assigns to
# the global object — which we have to supply as `this`.
PRELUDE = """
globalThis.structuredClone = globalThis.structuredClone || function (o) {
  return o === undefined ? undefined : JSON.parse(JSON.stringify(o));
};
globalThis.global = globalThis;
globalThis.self = globalThis;
// zrender schedules work through setTimeout even under ssr:true. Neither
// embedded engine has a timer queue; the SSR path is synchronous, so a stub
// that never fires is enough to get renderToSVGString() to return.
// Forced, not `||`: PythonMonkey *does* ship setTimeout, but it defers to a
// running Python asyncio loop and raises without one. A render that must not
// wait for a callback is better served by a timer that never fires.
globalThis.setTimeout = function () { return 0; };
globalThis.clearTimeout = function () {};
globalThis.setInterval = function () { return 0; };
globalThis.clearInterval = function () {};
globalThis.requestAnimationFrame = function () { return 0; };
globalThis.cancelAnimationFrame = function () {};
globalThis.console = globalThis.console || { log: function () {}, warn: function () {}, error: function () {} };
"""

GLUE = """
globalThis.ssrRender = function (optionJson, w, h) {
  var chart = echarts.init(null, null, {
    renderer: 'svg', ssr: true, width: w, height: h
  });
  chart.setOption(JSON.parse(optionJson));
  var svg = chart.renderToSVGString();
  chart.dispose();
  return svg;
};
globalThis.echartsVersion = function () { return echarts.version; };
"""


def load_engine(name: str):
    src = ECHARTS.read_text()
    if name == "quickjs":
        import quickjs

        ctx = quickjs.Context()
        ctx.eval(PRELUDE)
        ctx.eval(src)
        ctx.eval(GLUE)
        return ctx.get("ssrRender"), ctx.get("echartsVersion")
    if name == "pythonmonkey":
        import pythonmonkey as pm

        pm.eval(PRELUDE)
        pm.eval(src)
        pm.eval(GLUE)
        return pm.eval("globalThis.ssrRender"), pm.eval("globalThis.echartsVersion")
    raise ValueError(name)


def main(engine_name: str) -> None:
    if not ECHARTS.exists():
        sys.exit(f"missing {ECHARTS} — npm pack echarts@5.6.0 into build/npm first")
    if not SPECS.exists():
        sys.exit(f"missing {SPECS} — run dump_echarts.py first")

    t0 = time.time()
    render, version = load_engine(engine_name)
    boot = time.time() - t0
    print(f"{engine_name}: echarts {version()} loaded in {boot*1000:.0f} ms")

    specs = json.load(open(SPECS))
    ok, times, sizes = 0, [], []
    fail: collections.Counter = collections.Counter()
    example: dict[str, str] = {}
    blank = []
    for name, option in specs.items():
        t = time.time()
        try:
            svg = render(json.dumps(option), 640.0, 400.0)
            ok += 1
            times.append(time.time() - t)
            sizes.append(len(svg))
            if "<path" not in svg and "<rect" not in svg:
                blank.append(name)
        except Exception as exc:  # noqa: BLE001
            key = str(exc).strip().splitlines()[0][:120]
            fail[key] += 1
            example.setdefault(key, name)

    print(f"ok={ok} fail={sum(fail.values())} of {len(specs)}")
    if times:
        times.sort()
        print(
            f"per-chart SVG: p50={times[len(times)//2]*1000:.1f}ms "
            f"p90={times[int(len(times)*0.9)]*1000:.1f}ms max={times[-1]*1000:.1f}ms"
        )
        print(f"median svg bytes: {sorted(sizes)[len(sizes)//2]}")
    if blank:
        print(f"rendered but visually empty: {len(blank)}  e.g. {blank[:5]}")
    for msg, n in fail.most_common(10):
        print(f"  {n:4d}  {msg}   e.g. {example[msg]}")

    # keep one artifact so the SVG can be eyeballed / rasterised downstream
    first = next(iter(specs))
    (HERE / "build" / f"sample_{engine_name}.svg").write_text(
        render(json.dumps(specs[first]), 640.0, 400.0)
    )
    print(f"wrote build/sample_{engine_name}.svg ({first})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "quickjs")
