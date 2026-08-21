#!/usr/bin/env python3
"""
PROTOTYPE — THROWAWAY. Evidence for the rasterisation research ticket (#22).

The ECharts SSR probe shows the option object becomes an SVG string inside the
embedded engine. This asks the next question: does that SVG survive a
*non-browser* rasteriser? vl-convert exposes resvg directly as `svg_to_png`, so
the two halves compose into an ECharts raster path with no Node and no browser.

Run under a venv that has BOTH `vl_convert` and `quickjs` installed.

    python echarts_svg_to_png.py
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import vl_convert as vlc  # noqa: E402

from echarts_ssr_probe import load_engine  # noqa: E402

SPECS = json.load(open(HERE / "build" / "echarts_specs.json"))


def render(option: dict, animation: bool) -> str:
    opt = dict(option)
    if not animation:
        opt["animation"] = False
    return _render(json.dumps(opt), 640.0, 400.0)


_render, _ = load_engine("quickjs")

names = list(SPECS)[:40]

for anim in (True, False):
    ok = blank = err = 0
    sizes = []
    for name in names:
        try:
            svg = render(SPECS[name], animation=anim)
            png = vlc.svg_to_png(svg)
            sizes.append(len(png))
            ok += 1
        except Exception as exc:  # noqa: BLE001
            err += 1
            if err == 1:
                print(f"  first error (animation={anim}): {str(exc).splitlines()[0][:160]}")
    label = "with entrance animation" if anim else "animation:false"
    if sizes:
        sizes.sort()
        print(f"{label}: png ok={ok} err={err}  "
              f"median={sizes[len(sizes)//2]//1024} KiB  min={sizes[0]//1024} KiB")
    else:
        print(f"{label}: png ok={ok} err={err}")

# Is the SVG byte-stable? The class names look session-scoped.
a = render(SPECS[names[0]], animation=False)
b = render(SPECS[names[0]], animation=False)
print("\nsame engine, two renders identical:", a == b)
print("class-name sample:", sorted(set(re.findall(r'class="(zr[^"]*)"', a)))[:3])
print("css animation present with animation:false:",
      "@keyframes" in a or "animation:" in a)

pathlib.Path(HERE / "build" / "echarts_sample.png").write_bytes(
    vlc.svg_to_png(render(SPECS[names[0]], animation=False))
)
print("wrote build/echarts_sample.png")
