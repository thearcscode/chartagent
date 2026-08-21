#!/usr/bin/env python3
"""
Evidence harness for ADR-0001 (embed the pinned Flint compiler in-process).

MEASUREMENT ONLY — not the integration. See README.md.

    python harness.py smoke | parity | bench | dates

Engine-comparing checks re-exec this file once per engine so a SIGSEGV in one
binding is observed rather than suffered. MiniRacer launches a background
event loop — Engine.close() must run or the process hangs at exit.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import resource
import subprocess
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
BUNDLE = HERE / "build" / "flint.iife.js"
FIXTURES = HERE / "build" / "fixtures"
NPM_DIST = HERE / "build" / "npm" / "package" / "dist" / "index.js"

# QuickJS has no structuredClone; Flint's assemblers call it. This is the only
# missing global across all five backends.
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
globalThis.themeIds = function () {
  return JSON.stringify(Flint.listThemePresets().map(function (t) { return t.id; }));
};
globalThis.recommend = function (rowsJson, typesJson) {
  return JSON.stringify(Flint.recommendChartTypes(JSON.parse(rowsJson), JSON.parse(typesJson)));
};
"""

# miniracer is the V8 candidate under test for issue #29. stpyv8 is measured
# when FLINT_ENGINES includes it; its wheel matrix is incomplete (no Linux
# aarch64), so it is not in the default set.
ENGINES = tuple(
    os.environ["FLINT_ENGINES"].split(",")
    if os.environ.get("FLINT_ENGINES")
    else ("quickjs", "pythonmonkey", "miniracer")
)


def require_build() -> None:
    if not BUNDLE.exists():
        sys.exit("build/flint.iife.js missing — run ./setup.sh first")


def rss_mb() -> float:
    kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return kb / (1024 * 1024) if sys.platform == "darwin" else kb / 1024


class Engine:
    """One JS realm. NEVER share an instance across threads — see bench('crash')."""

    def __init__(self, name: str) -> None:
        self.name = name
        src = BUNDLE.read_text()
        if name == "quickjs":
            import quickjs

            self._ctx = quickjs.Context()
            for chunk in (POLYFILL, src, GLUE):
                self._ctx.eval(chunk)
            self._compile = self._ctx.get("compile")
            self._get = self._ctx.get
        elif name == "pythonmonkey":
            import pythonmonkey as pm

            for chunk in (POLYFILL, src, GLUE):
                pm.eval(chunk)
            self._compile = pm.eval("globalThis.compile")
            self._get = lambda n: pm.eval("globalThis." + n)
        elif name == "miniracer":
            from py_mini_racer import MiniRacer

            self._ctx = MiniRacer()
            for chunk in (POLYFILL, src, GLUE):
                self._ctx.eval(chunk)
            self._compile = lambda spec_json, backend: self._ctx.call(
                "compile", spec_json, backend
            )
            self._get = lambda n: self._ctx.eval(n)
        elif name == "stpyv8":
            import STPyV8

            self._isolate = STPyV8.JSIsolate()
            self._isolate.enter()
            self._ctx = STPyV8.JSContext()
            self._ctx.enter()
            for chunk in (POLYFILL, src, GLUE):
                self._ctx.eval(chunk)
            fn = self._ctx.eval("compile")
            self._compile = lambda spec_json, backend, fn=fn: fn(spec_json, backend)
            self._get = lambda n: self._ctx.eval(n)
        else:
            raise ValueError(name)

    def compile(self, spec: dict, backend: str) -> dict:
        raw = self._compile(json.dumps(spec), backend)
        if not isinstance(raw, str):
            raw = str(raw)
        return json.loads(raw)

    def call(self, name: str, *args: str) -> str:
        raw = self._get(name)(*args)
        return raw if isinstance(raw, str) else str(raw)

    def close(self) -> None:
        ctx = getattr(self, "_ctx", None)
        if ctx is not None and hasattr(ctx, "close"):
            ctx.close()
        if getattr(self, "name", None) == "stpyv8":
            self._ctx.leave()
            self._isolate.leave()


# ---------------------------------------------------------------------------
# spec comparison
# ---------------------------------------------------------------------------
# `_`-prefixed keys are compiler metadata (_width, _warnings, _transform, _pivot),
# not output. Canonicalise key order in ONE language: JS sorts by UTF-16 code unit
# and Python by code point, which reports phantom diffs on CJK labels.

def strip_meta(obj):
    if isinstance(obj, dict):
        return {k: strip_meta(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [strip_meta(v) for v in obj]
    return obj


def canon(obj) -> str:
    return json.dumps(strip_meta(obj), sort_keys=True, separators=(",", ":"))


def digest(obj) -> str:
    return hashlib.sha256(canon(obj).encode()).hexdigest()


def diff_paths(a, b, path="") -> list[str]:
    """Field-level differences, for reading rather than counting."""
    if type(a) is not type(b):
        return [f"{path}: {type(a).__name__} vs {type(b).__name__}"]
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{path}.{k}: only in B")
            elif k not in b:
                out.append(f"{path}.{k}: only in A")
            else:
                out += diff_paths(a[k], b[k], f"{path}.{k}")
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [f"{path}: length {len(a)} vs {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in diff_paths(x, y, f"{path}[{i}]")]
    return [] if a == b else [f"{path}: {json.dumps(a)[:44]} vs {json.dumps(b)[:44]}"]


def fixture_cases() -> list[pathlib.Path]:
    if not FIXTURES.exists():
        sys.exit("build/fixtures missing — run ./setup.sh first")
    return sorted(d for d in FIXTURES.iterdir() if d.is_dir())


def fixture_input(case: pathlib.Path) -> dict:
    # The assembler argument is nested under `.input`; the root also carries
    # title / description / chartType.
    return json.loads((case / "input.json").read_text())["input"]


SAMPLE = {
    "data": {"values": [
        {"quarter": "Q1", "revenue": 1200}, {"quarter": "Q2", "revenue": 1450},
        {"quarter": "Q3", "revenue": 980},  {"quarter": "Q4", "revenue": 1800},
    ]},
    "semantic_types": {"quarter": "Quarter", "revenue": "Revenue"},
    "chart_spec": {
        "chartType": "Bar Chart",
        "title": "Revenue by quarter",
        "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
        "baseSize": {"width": 480, "height": 320},
    },
}


# ---------------------------------------------------------------------------
# smoke
# ---------------------------------------------------------------------------

def cmd_smoke() -> None:
    require_build()
    engine = os.environ.get("FLINT_ENGINE", "quickjs")
    t0 = time.perf_counter()
    eng = Engine(engine)
    print(f"{engine}: engine + 1.6 MB bundle loaded in {(time.perf_counter() - t0) * 1000:.0f} ms\n")

    for backend in ("vegalite", "echarts", "chartjs", "plotly", "excel"):
        t0 = time.perf_counter()
        out = eng.compile(SAMPLE, backend)
        ms = (time.perf_counter() - t0) * 1000
        print(f"  {backend:9s} {ms:6.2f} ms  {len(json.dumps(out)):7d} bytes  "
              f"keys: {','.join(list(out)[:5])}")

    themes = json.loads(eng.call("themeIds"))
    print(f"\n  themes ({len(themes)}): {', '.join(themes)}")
    rec = eng.call("recommend", json.dumps(SAMPLE["data"]["values"]),
                   json.dumps(SAMPLE["semantic_types"]))
    print(f"  recommendChartTypes -> {rec}")

    # theme_spec is realised for Vega-Lite and Plotly only; ECharts and Chart.js
    # ignore it silently. Worth re-checking on every Flint bump.
    print("\n  theme_spec reaches:")
    for backend in ("vegalite", "echarts", "chartjs", "plotly"):
        plain = eng.compile(SAMPLE, backend)
        themed = eng.compile({**SAMPLE, "theme_spec": "economist"}, backend)
        applied = canon(plain) != canon(themed)
        print(f"    {backend:9s} {'yes' if applied else 'NO — silently ignored'}")
    eng.close()


# ---------------------------------------------------------------------------
# parity
# ---------------------------------------------------------------------------

def node_specs() -> dict[str, object]:
    """
    Reference specs from Node/V8 — Microsoft's own test oracle.

    Node returns whole specs, not digests, so that BOTH sides are canonicalised by
    the same Python code. Hashing in JS and comparing to a Python hash silently
    fails: JS sorts object keys by UTF-16 code unit, Python by code point, so CJK
    labels report phantom diffs.
    """
    script = r"""
    import { readFileSync, readdirSync, writeFileSync } from 'fs';
    const Flint = await import(process.argv[2]);
    const root = process.argv[3];
    const out = {};
    for (const d of readdirSync(root).sort()) {
      let input;
      try { input = JSON.parse(readFileSync(`${root}/${d}/input.json`, 'utf8')).input; }
      catch { continue; }
      try { out[d] = Flint.assembleVegaLite(input); }
      catch (e) { out[d] = { __error__: String(e.message).slice(0, 80) }; }
    }
    writeFileSync(process.argv[4], JSON.stringify(out));
    """
    dest = HERE / "build" / "specs_node.json"
    r = subprocess.run(["node", "--input-type=module", "-e", script,
                        "x", str(NPM_DIST), str(FIXTURES), str(dest)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("node reference run failed:\n" + r.stderr[:400])
    return json.loads(dest.read_text())


def engine_specs(engine: str) -> dict[str, object]:
    eng = Engine(engine)
    out = {}
    try:
        for case in fixture_cases():
            try:
                out[case.name] = eng.compile(fixture_input(case), "vegalite")
            except Exception as exc:  # noqa: BLE001 - recording failures is the point
                out[case.name] = {"__error__": f"{type(exc).__name__}: {exc}"[:80]}
    finally:
        eng.close()
    return out


def cmd_parity() -> None:
    require_build()
    cases = fixture_cases()
    print(f"{len(cases)} fixtures\n")

    # Both engines produce specs in their own subprocess; compare here.
    per_engine = {}
    for engine in ENGINES:
        r = subprocess.run([sys.executable, __file__, "_dump", engine],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  {engine}: FAILED ({r.returncode}) {r.stderr.strip()[:120]}")
            continue
        per_engine[engine] = json.loads(pathlib.Path(r.stdout.strip()).read_text())

    node = node_specs()
    node_digest = {k: digest(v) for k, v in node.items()}

    for engine, specs in per_engine.items():
        errors = [k for k, v in specs.items() if isinstance(v, dict) and "__error__" in v]
        disagree = [k for k, v in specs.items()
                    if k in node_digest and not (isinstance(v, dict) and "__error__" in v)
                    and digest(v) != node_digest[k]]
        agree = len(node_digest) - len(disagree)
        print(f"  {engine:13s} executed {len(specs) - len(errors)}/{len(specs)}, "
              f"errors {len(errors)}, agrees with Node on {agree}/{len(node_digest)}")
        if errors:
            print(f"    first errors: {errors[:3]}")
        if disagree:
            kinds = sorted({k.split("__")[0] for k in disagree})
            print(f"    disagrees on {len(disagree)}, all in: {', '.join(kinds)}")

    if len(per_engine) >= 2:
        names = [e for e in ENGINES if e in per_engine]
        for i, a_name in enumerate(names):
            for b_name in names[i + 1:]:
                a, b = per_engine[a_name], per_engine[b_name]
                both = [k for k in a if k in b]
                same = sum(1 for k in both if digest(a[k]) == digest(b[k]))
                print(f"\n  {a_name} vs {b_name}: {same}/{len(both)} identical")
                for k in [k for k in both if digest(a[k]) != digest(b[k])][:5]:
                    print(f"    {k}")
                    for d in diff_paths(strip_meta(a[k]), strip_meta(b[k]))[:4]:
                        print(f"      {d}")


def cmd__dump(engine: str) -> None:
    """Internal: compile every fixture in an isolated process, write to a temp file."""
    out = HERE / "build" / f"specs_{engine}.json"
    specs = engine_specs(engine)
    out.write_text(json.dumps(specs))
    print(out)


# ---------------------------------------------------------------------------
# bench
# ---------------------------------------------------------------------------

def cmd_bench() -> None:
    require_build()
    for engine in ENGINES:
        r = subprocess.run([sys.executable, __file__, "_bench1", engine],
                           capture_output=True, text=True)
        print(r.stdout.rstrip() or f"{engine}: FAILED {r.stderr.strip()[:150]}")
        print()

    print("=== shared-context safety (QuickJS) ===")
    r = subprocess.run([sys.executable, __file__, "_crash"], capture_output=True, text=True)
    print(r.stdout.rstrip())
    if r.returncode != 0:
        print(f"  process died with exit {r.returncode}"
              f"{' (SIGSEGV)' if r.returncode in (-11, 139) else ''} — as expected.")
        print("  A shared context is a hard crash, not an exception. Enforce one per thread.")
    else:
        print("  !! survived — re-verify the pool design assumption for this binding version")

    print("\n=== shared-isolate safety (MiniRacer) ===")
    r = subprocess.run([sys.executable, __file__, "_crash_miniracer"],
                       capture_output=True, text=True)
    print(r.stdout.rstrip())
    if r.returncode != 0:
        print(f"  process died with exit {r.returncode}"
              f"{' (SIGSEGV)' if r.returncode in (-11, 139) else ''}")
    else:
        print("  survived sharing one MiniRacer isolate across 4 threads")


def cmd__bench1(engine: str) -> None:
    m0 = rss_mb()
    t0 = time.perf_counter()
    eng = Engine(engine)
    boot = (time.perf_counter() - t0) * 1000
    print(f"=== {engine} ===")
    print(f"  cold boot {boot:.0f} ms | resident +{rss_mb() - m0:.1f} MB")

    for backend in ("vegalite", "echarts"):
        eng.compile(SAMPLE, backend)
        samples = []
        for _ in range(300):
            t0 = time.perf_counter()
            eng.compile(SAMPLE, backend)
            samples.append((time.perf_counter() - t0) * 1000)
        samples.sort()
        print(f"  {backend:9s} p50 {samples[150]:.2f} ms  "
              f"p95 {samples[285]:.2f} ms  p99 {samples[297]:.2f} ms")

    n = 1200
    t0 = time.perf_counter()
    for _ in range(n):
        eng.compile(SAMPLE, "echarts")
    serial = n / (time.perf_counter() - t0)
    print(f"  serial throughput {serial:.0f} compiles/s")

    if engine == "quickjs":
        m1 = rss_mb()
        pool = [Engine(engine) for _ in range(4)]
        print(f"  4 extra contexts +{rss_mb() - m1:.1f} MB "
              f"= {(rss_mb() - m1) / 4:.1f} MB each")
        per = 300
        t0 = time.perf_counter()
        threads = [threading.Thread(target=lambda e=e: [e.compile(SAMPLE, "echarts")
                                                        for _ in range(per)])
                   for e in pool]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        threaded = 4 * per / (time.perf_counter() - t0)
        print(f"  4 threads, one context each: {threaded:.0f} compiles/s "
              f"({threaded / serial:.1f}x serial — the binding releases the GIL)")
        for e in pool:
            e.close()
        eng.close()
    elif engine == "miniracer":
        m1 = rss_mb()
        pool = [Engine(engine) for _ in range(4)]
        print(f"  4 extra isolates +{rss_mb() - m1:.1f} MB "
              f"= {(rss_mb() - m1) / 4:.1f} MB each")
        per = 300
        t0 = time.perf_counter()
        threads = [threading.Thread(target=lambda e=e: [e.compile(SAMPLE, "echarts")
                                                        for _ in range(per)])
                   for e in pool]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        threaded = 4 * per / (time.perf_counter() - t0)
        print(f"  4 threads, one isolate each: {threaded:.0f} compiles/s "
              f"({threaded / serial:.1f}x serial)")
        for e in pool:
            e.close()
        eng.close()
    else:
        print("  one global realm per process; isolate tenants by process, not context")
        eng.close()


def cmd__crash() -> None:
    """Deliberately share one QuickJS context across threads. Expected to SIGSEGV."""
    eng = Engine("quickjs")
    eng.compile(SAMPLE, "echarts")
    print("  sharing ONE context across 4 threads (expected to crash)...", flush=True)
    threads = [threading.Thread(target=lambda: [eng.compile(SAMPLE, "echarts")
                                                for _ in range(200)])
               for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print("  survived")


def cmd__crash_miniracer() -> None:
    """Share one MiniRacer isolate across threads. Docs claim it is thread-safe."""
    eng = Engine("miniracer")
    eng.compile(SAMPLE, "echarts")
    print("  sharing ONE MiniRacer isolate across 4 threads...", flush=True)
    threads = [threading.Thread(target=lambda: [eng.compile(SAMPLE, "echarts")
                                                for _ in range(200)])
               for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print("  survived")
    eng.close()


# ---------------------------------------------------------------------------
# dates
# ---------------------------------------------------------------------------
# Parsing of non-standard date strings is implementation-defined in ECMAScript.
# The engines disagree, and not subtly: "Jan 2020" is temporal under V8 and
# ordinal under SpiderMonkey, which changes the axis type and the whole layout.

MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}

PATTERNS = (
    (re.compile(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})$"),
     lambda m: f"{m[3]}-{MONTHS[m[1]]:02d}-{int(m[2]):02d}"),          # Jan 15, 2020
    (re.compile(r"([A-Z][a-z]{2}) (\d{4})$"),
     lambda m: f"{m[2]}-{MONTHS[m[1]]:02d}"),                          # Jan 2020
    (re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})$"),
     lambda m: f"{m[3]}-{int(m[1]):02d}-{int(m[2]):02d}"),             # 01/15/2020 (US)
)


def to_iso(value):
    """Normalise recognised non-ISO date strings. Leaves everything else alone."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    for pattern, render in PATTERNS:
        m = pattern.fullmatch(text)
        if m:
            return render(m)
    return value


def cmd_dates() -> None:
    require_build()
    node = node_specs()
    r = subprocess.run([sys.executable, __file__, "_dump", "pythonmonkey"],
                       capture_output=True, text=True)
    specs = json.loads(pathlib.Path(r.stdout.strip()).read_text())
    diverging = [k for k in specs if k in node and digest(specs[k]) != digest(node[k])]
    print(f"pythonmonkey disagrees with Node on {len(diverging)} of {len(node)} cases\n")

    eng = Engine("pythonmonkey")
    fixed = still = untouched = 0
    shown = 0
    for name in diverging:
        spec = fixture_input(FIXTURES / name)
        before = json.dumps(spec["data"]["values"])
        spec["data"]["values"] = [{k: to_iso(v) for k, v in row.items()}
                                  for row in spec["data"]["values"]]
        if json.dumps(spec["data"]["values"]) == before:
            untouched += 1
            continue
        ours = eng.compile(spec, "vegalite")
        theirs = _node_one(spec)
        if theirs is not None and canon(ours) == canon(theirs):
            fixed += 1
        else:
            still += 1
            if shown < 2 and theirs is not None:
                shown += 1
                print(f"  still differing: {name}")
                for d in diff_paths(strip_meta(theirs), strip_meta(ours))[:5]:
                    print(f"    {d}")

    print("after ISO-8601 normalisation of the affected columns:")
    print(f"  now identical to Node : {fixed}")
    print(f"  still differing       : {still}")
    print(f"  no known date pattern : {untouched}  (needs a semantic_types hint, not parsing)")
    print("\nRule for the transform layer: emit ISO-8601, never a locale date string.")


def _node_one(spec: dict):
    script = ("const F = await import(process.argv[2]);"
              "let s=''; for await (const c of process.stdin) s += c;"
              "console.log(JSON.stringify(F.assembleVegaLite(JSON.parse(s))));")
    r = subprocess.run(["node", "--input-type=module", "-e", script, "x", str(NPM_DIST)],
                       input=json.dumps(spec), capture_output=True, text=True)
    return json.loads(r.stdout) if r.stdout.strip() else None


COMMANDS = {
    "smoke": cmd_smoke, "parity": cmd_parity, "bench": cmd_bench, "dates": cmd_dates,
    "_dump": cmd__dump, "_bench1": cmd__bench1, "_crash": cmd__crash,
    "_crash_miniracer": cmd__crash_miniracer,
}

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in COMMANDS:
        sys.exit(__doc__)
    COMMANDS[name](*sys.argv[2:])
