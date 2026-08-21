#!/usr/bin/env python3
"""
PROTOTYPE — THROWAWAY. Evidence for the rasterisation research ticket (#22).

Measures whether vl-convert (Rust + embedded V8, no Node, no browser) can
rasterise the Vega-Lite output that Flint 0.5.1 actually produces.

    python vlconvert_probe.py corpus [vl_version]   # all 705 fixtures -> PNG
    python vlconvert_probe.py cost                  # cold start, warm rate, RSS
    python vlconvert_probe.py fonts                 # what font ends up in the SVG
    python vlconvert_probe.py offline               # behaviour with no network

Input is `../flint-embed/build/specs_node.json`, the Node/V8 compile of all 705
upstream fixtures recorded by ADR-0001's harness.
"""

from __future__ import annotations

import collections
import json
import pathlib
import re
import resource
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
SPECS = HERE.parent / "flint-embed" / "build" / "specs_node.json"
DEFAULT_VL = "6.4"


def load():
    if not SPECS.exists():
        sys.exit(f"missing {SPECS} — run ../flint-embed/setup.sh and harness.py parity first")
    return json.load(open(SPECS))


def strip_meta(spec: dict) -> dict:
    """`_`-prefixed keys are Flint compiler metadata, not Vega-Lite."""
    return {k: v for k, v in spec.items() if not k.startswith("_")}


def rss_mb() -> float:
    kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return kb / (1024 * 1024) if sys.platform == "darwin" else kb / 1024


def corpus(vl_version: str = DEFAULT_VL) -> None:
    import vl_convert as vlc

    specs = load()
    print(f"vl-convert {vlc.__version__}  vega {vlc.get_vega_version()}")
    print(f"vega-lite versions bundled: {vlc.get_vegalite_versions()}")
    print(f"rendering {len(specs)} fixtures at vl_version={vl_version}\n")

    ok, times, sizes = 0, [], []
    fail: collections.Counter = collections.Counter()
    example: dict[str, str] = {}
    t_all = time.time()
    for name, spec in specs.items():
        js = json.dumps(strip_meta(spec))
        t0 = time.time()
        try:
            png = vlc.vegalite_to_png(vl_spec=js, vl_version=vl_version, scale=1)
            ok += 1
            times.append(time.time() - t0)
            sizes.append(len(png))
        except Exception as exc:  # noqa: BLE001 — we want the message, whatever it is
            key = str(exc).strip().splitlines()[0][:120]
            fail[key] += 1
            example.setdefault(key, name)

    wall = time.time() - t_all
    print(f"ok={ok}  fail={sum(fail.values())}  of {len(specs)}   wall={wall:.1f}s")
    if times:
        times.sort()
        sizes.sort()
        print(
            f"per-chart: p50={times[len(times)//2]*1000:.0f}ms "
            f"p90={times[int(len(times)*0.9)]*1000:.0f}ms "
            f"max={times[-1]*1000:.0f}ms   median png={sizes[len(sizes)//2]//1024} KiB"
        )
    for msg, n in fail.most_common(20):
        print(f"  {n:4d}  {msg}   e.g. {example[msg]}")
    print(f"peak RSS {rss_mb():.0f} MB")


def cost() -> None:
    import vl_convert as vlc

    specs = load()
    js = json.dumps(strip_meta(next(iter(specs.values()))))

    before = rss_mb()
    t0 = time.time()
    vlc.vegalite_to_png(vl_spec=js, vl_version=DEFAULT_VL)
    cold = time.time() - t0
    first = rss_mb()

    t0 = time.time()
    for _ in range(20):
        vlc.vegalite_to_png(vl_spec=js, vl_version=DEFAULT_VL)
    warm = (time.time() - t0) / 20

    print(f"first conversion (engine boot + VL load): {cold*1000:.0f} ms")
    print(f"warm mean over 20:                        {warm*1000:.0f} ms")
    print(f"RSS: before={before:.0f} MB  after-first={first:.0f} MB  after-21={rss_mb():.0f} MB")


def fonts() -> None:
    import vl_convert as vlc

    specs = load()
    corpus_json = json.dumps(specs)
    print("font/fontFamily keys anywhere in the 705 compiled specs:",
          corpus_json.count('"font"'), corpus_json.count("fontFamily"))

    svg = vlc.vegalite_to_svg(
        vl_spec=json.dumps(strip_meta(next(iter(specs.values())))), vl_version=DEFAULT_VL
    )
    fams = sorted(set(re.findall(r'font-family="([^"]*)"', svg)))
    print("font-family attributes emitted into the SVG:", fams or "(none)")
    print("svg header:", svg[:160].replace("\n", " "))


def offline() -> None:
    """Flint inlines rows, so nothing should need the network. Prove it."""
    import socket

    def blocked(*_a, **_k):
        raise OSError("network disabled by probe")

    socket.socket = blocked  # type: ignore[assignment]
    socket.create_connection = blocked  # type: ignore[assignment]

    import vl_convert as vlc

    specs = load()
    urlish = {
        k: v["data"]["url"]
        for k, v in specs.items()
        if isinstance(v.get("data"), dict) and "url" in v["data"]
    }
    print("fixtures whose data is a URL rather than inline rows:", urlish or "none")

    ok, fail = 0, []
    for name, spec in specs.items():
        try:
            vlc.vegalite_to_png(vl_spec=json.dumps(strip_meta(spec)), vl_version=DEFAULT_VL)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            fail.append((name, str(exc).strip().splitlines()[0][:100]))
    print(f"with Python sockets disabled: ok={ok} fail={len(fail)}")
    for name, msg in fail[:10]:
        print(f"  {name}: {msg}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "corpus"
    if cmd == "corpus":
        corpus(sys.argv[2] if len(sys.argv) > 2 else DEFAULT_VL)
    elif cmd == "cost":
        cost()
    elif cmd == "fonts":
        fonts()
    elif cmd == "offline":
        offline()
    else:
        sys.exit(__doc__)
