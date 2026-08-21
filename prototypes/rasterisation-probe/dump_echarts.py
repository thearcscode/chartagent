#!/usr/bin/env python3
"""
PROTOTYPE — THROWAWAY. Compiles all 705 upstream Flint fixtures to the ECharts
backend using the pinned bundle from ../flint-embed, and writes the option
objects to build/echarts_specs.json so the SSR probe has real input.

    python dump_echarts.py            # uses quickjs
"""

from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
EMBED = HERE.parent / "flint-embed"
sys.path.insert(0, str(EMBED))

from harness import Engine, fixture_cases, fixture_input  # type: ignore  # noqa: E402


def main() -> None:
    engine = Engine("quickjs")
    out, unsupported = {}, 0
    for case in fixture_cases():
        try:
            out[case.name] = engine.compile(fixture_input(case), "echarts")
        except Exception:  # noqa: BLE001 — "unsupported by this backend" is expected
            unsupported += 1
    (HERE / "build").mkdir(exist_ok=True)
    (HERE / "build" / "echarts_specs.json").write_text(json.dumps(out))
    print(f"compiled {len(out)} ECharts options; {unsupported} unsupported by the backend")


if __name__ == "__main__":
    main()
