"""Narrowing gate between two extracted Flint vocabularies.

Exit 0 = the new pin only widens, or reports affordance metadata.
Exit 1 = something the façade rejects on is gone (ADR-0009 Decision 13).

    python tools/check_bump.py <old-vocab.json> <new-vocab.json>
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def _prop_id(backend: str, chart: str, key: str) -> str:
    return f"{backend}|{chart}|{key}"


def _chart_id(backend: str, chart: str) -> str:
    return f"{backend}|{chart}"


def _charts(vocab: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    for backend, charts in vocab.get("backends", {}).items():
        for chart in charts:
            out.add(_chart_id(backend, chart))
    return out


def _properties(vocab: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for backend, charts in vocab.get("backends", {}).items():
        for chart, spec in charts.items():
            for prop in spec.get("properties") or []:
                out[_prop_id(backend, chart, prop["key"])] = prop
    return out


def _option_values(prop: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    for option in prop.get("options") or []:
        if isinstance(option, Mapping) and "value" in option:
            values.add(json.dumps(option["value"], sort_keys=True))
        elif isinstance(option, Mapping):
            continue
        else:
            values.add(json.dumps(option, sort_keys=True))
    return values


def _display_option(token: str) -> str:
    parsed = json.loads(token)
    if isinstance(parsed, str):
        return parsed
    return json.dumps(parsed, sort_keys=True, separators=(", ", ": "))


def _chart_channels(vocab: Mapping[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for backend, charts in vocab.get("backends", {}).items():
        for chart, spec in charts.items():
            out[_chart_id(backend, chart)] = list(spec.get("channels") or [])
    return out


def _bound_tuple(prop: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    return (prop.get("min"), prop.get("max"), prop.get("step"))


def _deps(prop: Mapping[str, Any]) -> list[str]:
    return list(prop.get("dependencies") or [])


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(
            "usage: python tools/check_bump.py <old-vocab.json> <new-vocab.json>",
            file=sys.stderr,
        )
        return 2
    old = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    new = json.loads(Path(args[1]).read_text(encoding="utf-8"))

    old_charts = _charts(old)
    new_charts = _charts(new)
    old_props = _properties(old)
    new_props = _properties(new)
    removed_charts = old_charts - new_charts

    breaks: list[str] = []
    for chart in sorted(removed_charts):
        breaks.append(f"CHART REMOVED       {chart}")
    for pid in sorted(set(old_props) - set(new_props)):
        backend, chart, _key = pid.split("|", 2)
        if _chart_id(backend, chart) in removed_charts:
            continue
        breaks.append(f"PROPERTY REMOVED    {pid}")
    for pid in sorted(set(old_props) & set(new_props)):
        old_type = old_props[pid].get("type")
        new_type = new_props[pid].get("type")
        if old_type != new_type:
            breaks.append(f"PROPERTY RETYPED    {pid}: {old_type} -> {new_type}")
        gone = _option_values(old_props[pid]) - _option_values(new_props[pid])
        if gone:
            lost = ", ".join(_display_option(item) for item in sorted(gone))
            breaks.append(f"OPTION REMOVED      {pid}: lost {lost}")

    old_global = set(old.get("channels") or [])
    new_global = set(new.get("channels") or [])
    for channel in sorted(old_global - new_global):
        breaks.append(f"CHANNEL REMOVED     {channel}")
    old_themes = set((old.get("theme_presets") or {}).keys())
    new_themes = set((new.get("theme_presets") or {}).keys())
    for theme in sorted(old_themes - new_themes):
        breaks.append(f"THEME REMOVED       {theme}")
    old_semantics = set(old.get("semantic_types") or [])
    new_semantics = set(new.get("semantic_types") or [])
    for name in sorted(old_semantics - new_semantics):
        breaks.append(f"SEMANTIC TYPE REMOVED {name}")

    missing = list(new.get("missing_exports") or [])
    if missing:
        breaks.append(f"BACKEND MISSING     {', '.join(missing)}")

    reports: list[str] = []
    old_channels = _chart_channels(old)
    new_channels = _chart_channels(new)
    for chart in sorted(set(old_channels) & set(new_channels)):
        if old_channels[chart] != new_channels[chart]:
            before = old_channels[chart]
            after = new_channels[chart]
            reports.append(f"REPORT CHANNELS     {chart}: {before} -> {after}")
    for pid in sorted(set(old_props) & set(new_props)):
        old_bounds = _bound_tuple(old_props[pid])
        new_bounds = _bound_tuple(new_props[pid])
        if old_bounds != new_bounds:
            reports.append(f"REPORT BOUNDS       {pid}: {old_bounds} -> {new_bounds}")
        old_deps = _deps(old_props[pid])
        new_deps = _deps(new_props[pid])
        if old_deps != new_deps:
            reports.append(f"REPORT DEPENDENCIES {pid}: {old_deps} -> {new_deps}")

    print(f"{args[0]} -> {args[1]}")
    n_old, n_new = len(old_props), len(new_props)
    print(
        f"  properties: {n_old} -> {n_new}"
        f"   breaking: {len(breaks)}   reports: {len(reports)}"
    )
    for line in breaks + reports:
        print("  " + line)
    if breaks:
        print(
            "\nFAIL — regenerate deliberately: each line above changes "
            "what a stored frame may bind."
        )
        return 1
    print("\nOK — widening only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
