# /// script
# requires-python = ">=3.11"
# dependencies = ["pydantic>=2.9"]
# ///
"""
PROTOTYPE — THROWAWAY. Interactive walkthrough of the ChartSpec v1 draft (issue #3).

    uv run prototypes/chartspec-v1/explore.py

Each case prints the full resulting state: the canonical JSON for specs that build,
the typed error for specs that don't, and the round-trip verdict either way.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable

from pydantic import ValidationError

from chartspec_draft import (
    SPEC_VERSION,
    ChartSpec,
    adapter_supports,
    validate_against_profile,
)

DIM, BOLD, RED, GREEN, YELLOW, RESET = "\033[2m", "\033[1m", "\033[31m", "\033[32m", "\033[33m", "\033[0m"


def base_data() -> dict[str, Any]:
    return {"source": "s3://bucket/sales.parquet", "transform": {"__stub__": "issue #4"}}


# A stand-in for profile.json (issue #5) — only what phase-2 validation reads.
FAKE_PROFILE = {
    "columns": {
        "month": {"cardinality": 24},
        "revenue_sum": {"cardinality": 24},
        "region": {"cardinality": 4},
        "sku": {"cardinality": 830},
    }
}


# ---------------------------------------------------------------------------- specs ---
def spec_simple_bar() -> dict[str, Any]:
    return {
        "data": base_data(),
        "mark": {"type": "bar", "stack": "stacked"},
        "encodings": {
            "x": {"field": "month", "type": "temporal"},
            "y": {"field": "revenue_sum", "type": "quantitative", "scale": {"zero": True}},
            "color": {"field": "region", "type": "nominal"},
            "tooltip": [{"field": "revenue_sum", "type": "quantitative"}],
        },
        "style": {"title": "Monthly revenue by region"},
    }


def spec_donut() -> dict[str, Any]:
    return {
        "data": base_data(),
        "mark": {"type": "pie", "inner_radius_ratio": 0.55},
        "encodings": {
            "color": {"field": "region", "type": "nominal"},
            "y": {"field": "revenue_sum", "type": "quantitative"},
        },
    }


def spec_layered() -> dict[str, Any]:
    return {
        "data": base_data(),
        "mark": {"type": "line", "interpolate": "monotone"},
        "encodings": {
            "x": {"field": "month", "type": "temporal"},
            "y": {"field": "revenue_sum", "type": "quantitative"},
        },
        "layers": [{"mark": {"type": "scatter"}}],
        "annotations": [
            {"type": "reference_line", "axis": "y", "value": "mean", "field": "revenue_sum", "label": "avg"}
        ],
    }


def spec_histogram_with_y() -> dict[str, Any]:
    s = {
        "data": base_data(),
        "mark": {"type": "histogram", "bins": 30},
        "encodings": {
            "x": {"field": "revenue_sum", "type": "quantitative"},
            "y": {"field": "count", "type": "quantitative"},
        },
    }
    return s


def spec_pie_missing_value() -> dict[str, Any]:
    return {
        "data": base_data(),
        "mark": {"type": "pie"},
        "encodings": {"color": {"field": "region", "type": "nominal"}},
    }


def spec_scatter_ordinal_x() -> dict[str, Any]:
    return {
        "data": base_data(),
        "mark": {"type": "scatter"},
        "encodings": {
            "x": {"field": "region", "type": "nominal"},
            "y": {"field": "revenue_sum", "type": "quantitative"},
        },
    }


def spec_bad_layer_combo() -> dict[str, Any]:
    return {
        "data": base_data(),
        "mark": {"type": "pie"},
        "encodings": {
            "color": {"field": "region", "type": "nominal"},
            "y": {"field": "revenue_sum", "type": "quantitative"},
        },
        "layers": [{"mark": {"type": "heatmap"}}],
    }


def spec_layer_overlay_breaks_contract() -> dict[str, Any]:
    """Base is fine; the overlay's own mark can't take the merged channel set."""
    return {
        "data": base_data(),
        "mark": {"type": "scatter"},
        "encodings": {
            "x": {"field": "revenue_sum", "type": "quantitative"},
            "y": {"field": "revenue_sum", "type": "quantitative"},
            "size": {"field": "revenue_sum", "type": "quantitative"},
        },
        "layers": [{"mark": {"type": "line"}}],  # line has no `size` channel
    }


def spec_stat_ref_line_no_field() -> dict[str, Any]:
    return {
        "data": base_data(),
        "mark": {"type": "line"},
        "encodings": {
            "x": {"field": "month", "type": "temporal"},
            "y": {"field": "revenue_sum", "type": "quantitative"},
        },
        "annotations": [{"type": "reference_line", "axis": "y", "value": "median"}],
    }


def spec_escape_with_layers() -> dict[str, Any]:
    s = spec_layered()
    s["escape"] = {"mode": "custom_code", "reason": "sankey requested", "runtime_profile": "web"}
    return s


def spec_typo_channel() -> dict[str, Any]:
    return {
        "data": base_data(),
        "mark": {"type": "bar"},
        "encodings": {
            "x": {"field": "month", "type": "temporal"},
            "y": {"field": "revenue_sum", "type": "quantitative"},
            "colour": {"field": "region", "type": "nominal"},  # British spelling typo
        },
    }


def spec_high_cardinality_color() -> dict[str, Any]:
    return {
        "data": base_data(),
        "mark": {"type": "bar"},
        "encodings": {
            "x": {"field": "month", "type": "temporal"},
            "y": {"field": "revenue_sum", "type": "quantitative"},
            "color": {"field": "sku", "type": "nominal"},  # cardinality 830
        },
    }


def spec_unknown_field() -> dict[str, Any]:
    return {
        "data": base_data(),
        "mark": {"type": "bar"},
        "encodings": {
            "x": {"field": "montth", "type": "temporal"},  # typo'd column
            "y": {"field": "revenue_sum", "type": "quantitative"},
        },
    }


# ------------------------------------------------------------------------- machinery ---
def show(title: str, raw: dict[str, Any], *, expect: str, profile_check: bool = False) -> None:
    print(f"\n{BOLD}── {title}{RESET}  {DIM}(expect: {expect}){RESET}")
    try:
        spec = ChartSpec.model_validate(raw)
    except ValidationError as e:
        print(f"{RED}REJECTED at construction{RESET}")
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "<root>"
            msg = err["msg"].removeprefix("Value error, ")
            print(f"  {RED}✗{RESET} {loc}: {msg}")
        return

    canonical = spec.to_json_obj()
    print(f"{GREEN}ACCEPTED{RESET} — canonical JSON:")
    print("\n".join("  " + ln for ln in json.dumps(canonical, indent=2).splitlines()))

    # P0.3 lossless round-trip
    again = ChartSpec.from_json_obj(canonical).to_json_obj()
    ok = again == canonical
    tag = f"{GREEN}lossless{RESET}" if ok else f"{RED}LOSSY{RESET}"
    print(f"  round-trip JSON→Pydantic→JSON: {tag}")
    if not ok:
        print(f"    {RED}before{RESET}: {json.dumps(canonical)}")
        print(f"    {RED}after {RESET}: {json.dumps(again)}")

    if profile_check:
        errs = validate_against_profile(spec, FAKE_PROFILE)
        if errs:
            print(f"  {YELLOW}phase-2 (against profile.json) rejected:{RESET}")
            for e in errs:
                print(f"    {YELLOW}✗{RESET} {e}")
        else:
            print(f"  phase-2 (against profile.json): {GREEN}passes{RESET}")


def case_versions() -> None:
    print(f"\n{BOLD}── D7: spec_version ↔ adapter max_spec_version{RESET}")
    for spec_v, adapter_v in [("1.0", "1.0"), ("1.0", "1.3"), ("1.4", "1.2"), ("2.0", "1.9")]:
        ok, why = adapter_supports(spec_v, adapter_v)
        mark = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
        print(f"  {mark} spec {spec_v} vs adapter max {adapter_v}: {why}")


CASES: list[tuple[str, Callable[[], None]]] = [
    ("simple stacked bar (the 80% case)", lambda: show("simple stacked bar", spec_simple_bar(), expect="accept", profile_check=True)),
    ("donut = pie + inner_radius_ratio (D1)", lambda: show("donut via pie mark", spec_donut(), expect="accept")),
    ("line + point overlay + mean ref line (D5, D6)", lambda: show("layered line+scatter", spec_layered(), expect="accept")),
    ("histogram given an explicit y (D4)", lambda: show("histogram with y", spec_histogram_with_y(), expect="reject: y is computed")),
    ("pie missing its value channel (D4)", lambda: show("pie without y", spec_pie_missing_value(), expect="reject: required channel")),
    ("scatter with a nominal x (D4 type rule)", lambda: show("scatter nominal x", spec_scatter_ordinal_x(), expect="reject: type mismatch")),
    ("pie + heatmap layer (D5 allowlist)", lambda: show("bad layer combo", spec_bad_layer_combo(), expect="reject: combo not allowed")),
    ("overlay inherits a channel it can't take (D5)", lambda: show("overlay contract break", spec_layer_overlay_breaks_contract(), expect="reject: layer channel")),
    ("stat ref line with no field (D6)", lambda: show("mean line, no field", spec_stat_ref_line_no_field(), expect="reject: needs field")),
    ("escape + layers (rail conflict)", lambda: show("escape with layers", spec_escape_with_layers(), expect="reject: escape conflict")),
    ("misspelled channel name (extra=forbid)", lambda: show("'colour' typo", spec_typo_channel(), expect="reject: unknown key")),
    ("830-way color — phase 2 only", lambda: show("high-cardinality color", spec_high_cardinality_color(), expect="accept, then phase-2 reject", profile_check=True)),
    ("field absent from profile — phase 2 only", lambda: show("unknown field", spec_unknown_field(), expect="accept, then phase-2 reject", profile_check=True)),
    ("spec_version compatibility (D7)", case_versions),
]


def main() -> None:
    print(f"{BOLD}ChartSpec v{SPEC_VERSION} draft — prototype walkthrough (issue #3){RESET}")
    print(f"{DIM}THROWAWAY CODE. Decisions D1–D9 live in chartspec_draft.py / README.md{RESET}")

    if len(sys.argv) > 1 and sys.argv[1] in {"-a", "--all"}:
        for _, fn in CASES:
            fn()
        return

    while True:
        print(f"\n{BOLD}Cases{RESET}")
        for i, (name, _) in enumerate(CASES, 1):
            print(f"  {i:>2}. {name}")
        print("   a. run all      q. quit")
        try:
            choice = input("\n> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if choice in {"q", "quit", "exit"}:
            return
        if choice in {"a", "all"}:
            for _, fn in CASES:
                fn()
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(CASES):
            CASES[int(choice) - 1][1]()
        else:
            print(f"{RED}?{RESET}")


if __name__ == "__main__":
    main()
