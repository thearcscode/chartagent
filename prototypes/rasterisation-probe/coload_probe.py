#!/usr/bin/env python3
"""
PROTOTYPE — THROWAWAY. Evidence for the rasterisation research ticket (#22).

ADR-0001 records that QuickJS and PythonMonkey segfault if imported into the
same interpreter. vl-convert embeds a *third* JS engine (V8, via deno_runtime)
in the same CPython process. Before anyone puts vl-convert in the request path
next to the compiler, someone has to find out whether that combination is safe.

Each pairing runs in its own subprocess so a SIGSEGV is observed, not suffered.

    python coload_probe.py                 # runs every pairing
    python coload_probe.py <pairing>       # internal: one pairing, in-process
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
EMBED = HERE.parent / "flint-embed"
SPEC = json.dumps(
    {
        "data": {"values": [{"a": "A", "b": 28}, {"a": "B", "b": 55}]},
        "mark": "bar",
        "encoding": {"x": {"field": "a", "type": "nominal"},
                     "y": {"field": "b", "type": "quantitative"}},
    }
)

PAIRINGS = [
    "v8-only",
    "quickjs-then-v8", "v8-then-quickjs",
    "pythonmonkey-then-v8", "v8-then-pythonmonkey",
    # Control pairings that ADR-0001 claims crash. Added by #29; the original
    # probe never ran these, so a "survived" result against V8 was uncalibrated.
    "quickjs-then-pythonmonkey", "pythonmonkey-then-quickjs",
]


def use_v8() -> None:
    import vl_convert as vlc

    png = vlc.vegalite_to_png(vl_spec=SPEC, vl_version="6.4")
    print(f"    v8/vl-convert produced {len(png)} bytes")


def use_quickjs() -> None:
    import quickjs

    ctx = quickjs.Context()
    ctx.eval("globalThis.f = function () { return 6 * 7; };")
    print(f"    quickjs says {ctx.get('f')()}")


def use_pythonmonkey() -> None:
    import pythonmonkey as pm

    print(f"    pythonmonkey says {pm.eval('6 * 7')}")


def run_one(pairing: str) -> None:
    steps = {
        "v8-only": [use_v8],
        "quickjs-then-v8": [use_quickjs, use_v8],
        "v8-then-quickjs": [use_v8, use_quickjs],
        "pythonmonkey-then-v8": [use_pythonmonkey, use_v8],
        "v8-then-pythonmonkey": [use_v8, use_pythonmonkey],
        "quickjs-then-pythonmonkey": [use_quickjs, use_pythonmonkey],
        "pythonmonkey-then-quickjs": [use_pythonmonkey, use_quickjs],
    }[pairing]
    for step in steps:
        step()
    print("    survived")


def main() -> None:
    if len(sys.argv) > 1:
        run_one(sys.argv[1])
        return
    for pairing in PAIRINGS:
        print(f"{pairing}:")
        r = subprocess.run([sys.executable, __file__, pairing],
                           capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        verdict = "ok" if r.returncode == 0 else f"exit {r.returncode}"
        if r.returncode < 0:
            verdict += "  <-- killed by signal (a crash, not an exception)"
        print(f"  => {verdict}")
        if r.returncode != 0 and r.stderr:
            print("     " + r.stderr.strip().splitlines()[-1][:140])


if __name__ == "__main__":
    main()
