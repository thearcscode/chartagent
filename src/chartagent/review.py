"""``ReviewReport`` and ``CheckResult`` — the review gate's result types
(ADR-0005 Decision 9, ADR-0024), the Tier-1 checks (``injection_pattern``
needs no rasteriser; ``painted`` and ``colorblind_safe_palette`` need one),
and Tier 2 (ADR-0026, ADR-0027): the applicability table over the 48 chart
types and ``flint_review``, which runs Tier 1 then, when a rasteriser and a
critic are both supplied, a Flint critique.

With a rasteriser, a Flint review rasterises once and ``painted`` resolves
from that picture (#254); the same PNG feeds the critic. Without one it stays
``not_checked`` ("unavailable"). ``colorblind_safe_palette`` is scored from
the same picture (#255), unless ``painted`` failed. ``data_truthfulness`` is
omitted on Flint (its output is ``input.data``; ADR-0024). An internal
error in a check raises; it never becomes a ``CheckResult`` (ADR-0024
Decision 2).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Literal

from chartagent._palette import score_palette
from chartagent._pixels import Raster, decode_png
from chartagent.critique import (
    Critique,
    CritiqueContext,
    Tier2CheckName,
    critique,
    to_check_outcome,
)
from chartagent.envelope import Envelope
from chartagent.frame.input import Backend, InputFrame
from chartagent.plan.client import ModelClient
from chartagent.profile.models import Profile, StringColumn
from chartagent.rasterise import Rasteriser

CheckName = Literal[
    "injection_pattern",
    "painted",
    "colorblind_safe_palette",
    "data_truthfulness",
    "marks_present",
    "axis_labels_present",
    "legend_presence",
    "label_overlap",
    "bar_chart_y_axis_baseline",
]
Outcome = Literal["pass", "fail", "not_checked"]


@dataclass(frozen=True)
class CheckResult:
    """One check's outcome. One shape across every tier; richer per-tier
    content rides in ``detail``, never a new field."""

    name: CheckName
    outcome: Outcome
    detail: str | None = None


@dataclass(frozen=True)
class ReviewReport:
    """The report for the artifact ``create_chart`` returned.

    ``passed`` is scoped to the tiers run and is false for a run tier that
    resolved nothing. ``budget_exhausted`` is true iff a repairable fail met a
    spent repair budget; Tier 1 has none, so it is false here."""

    tiers_run: tuple[int, ...]
    tiers_skipped: Mapping[int, Literal["unavailable", "unsupported", "blocked"]]
    passed: bool
    budget_exhausted: bool
    checks: tuple[CheckResult, ...]


_INSTRUCTION_LIKE = re.compile(
    r"""
    \b(?:ignore|disregard|forget|override)\b[^.\n]{0,40}\b(?:previous|prior|above|earlier|all|any|your)\b[^.\n]{0,40}\b(?:instructions?|prompts?|rules?|directions?)\b
    | \bsystem\s+prompt\b
    | \b(?:new|updated)\s+instructions?\b
    | \byou\s+are\s+now\b
    | \bact\s+as\b
    | \bpretend\s+(?:to\s+be|you\s+are)\b
    | </?\s*(?:system|assistant|data_profile\w*|instructions?)\b
    | \[\s*(?:system|inst)\s*\]
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _tier1_checks(profile: Profile, backend: Backend | None) -> list[CheckResult]:
    """Which checks appear follows ADR-0024 Decision 4: Excel gets only
    ``injection_pattern``; Flint adds ``painted`` and
    ``colorblind_safe_palette``; the custom rail adds ``colorblind_safe_palette``
    and ``data_truthfulness``. The image-derived ones start as
    ``not_checked`` placeholders; ``flint_review`` resolves the Flint ones
    from the rasterised picture when a rasteriser is supplied (module
    docstring)."""
    checks = [_injection_pattern(profile)]
    if backend is None:
        checks.append(
            CheckResult("colorblind_safe_palette", "not_checked", "unavailable")
        )
        checks.append(CheckResult("data_truthfulness", "not_checked", "unavailable"))
    elif backend != "excel":
        checks.append(CheckResult("painted", "not_checked", "unavailable"))
        checks.append(
            CheckResult("colorblind_safe_palette", "not_checked", "unavailable")
        )
    return checks


# `painted` is a coarse whole-canvas non-blank check (ADR-0024): the canvas
# fails when it is one flat colour or when fewer than this fraction of its
# pixels differ from the most common colour. One named number so `pass` means
# the same on every deployment.
_PAINTED_INK_FLOOR = 0.001


def _painted(raster: Raster) -> CheckResult:
    counts: dict[tuple[int, int, int], int] = {}
    for pixel in raster.pixels:
        counts[pixel] = counts.get(pixel, 0) + 1
    ink = len(raster.pixels) - max(counts.values(), default=0)
    if ink / max(len(raster.pixels), 1) < _PAINTED_INK_FLOOR:
        return CheckResult("painted", "fail", "canvas is blank")
    return CheckResult("painted", "pass")


def _colorblind_safe_palette(raster: Raster) -> CheckResult:
    verdict = score_palette(raster)
    if verdict.collapsed:
        return CheckResult(
            "colorblind_safe_palette",
            "fail",
            "two mark colours look alike under colour-blind vision",
        )
    if verdict.hue_count < 2:
        return CheckResult(
            "colorblind_safe_palette", "pass", "fewer than two hues: nothing to confuse"
        )
    return CheckResult("colorblind_safe_palette", "pass")


def tier1_review(profile: Profile, *, backend: Backend | None) -> ReviewReport:
    """Tier 1 for one artifact. ``backend`` is ``None`` on the custom rail."""
    checks = _tier1_checks(profile, backend)
    failed = any(check.outcome == "fail" for check in checks)
    resolved = any(check.outcome != "not_checked" for check in checks)
    return ReviewReport(
        tiers_run=(1,),
        tiers_skipped={2: "blocked" if failed else "unavailable"},
        passed=resolved and not failed,
        budget_exhausted=False,
        checks=tuple(checks),
    )


def _injection_pattern(profile: Profile) -> CheckResult:
    """Screens ADR-0011's untrusted paths only. ``detail`` names the path,
    never the matched text, so attacker text does not travel into the report."""
    hits = [
        path
        for path, text in _untrusted_strings(profile)
        if _INSTRUCTION_LIKE.search(text)
    ]
    if not hits:
        return CheckResult("injection_pattern", "pass")
    return CheckResult(
        "injection_pattern",
        "fail",
        "instruction-like text in: " + ", ".join(hits),
    )


def _untrusted_strings(profile: Profile) -> Iterator[tuple[str, str]]:
    for index, column in enumerate(profile.columns):
        yield f"columns[{index}].name", column.name
        yield f"columns[{index}].reported_type", column.reported_type
        if isinstance(column, StringColumn) and column.stats is not None:
            yield f"columns[{index}].stats.min", column.stats.min
            yield f"columns[{index}].stats.max", column.stats.max
        for position, top in enumerate(getattr(column, "top", None) or []):
            if isinstance(top.value, str):
                yield f"columns[{index}].top[{position}].value", top.value
    for row, sample in enumerate(profile.sample_rows):
        for key, value in sample.items():
            yield f"sample_rows[{row}] key", str(key)
            if isinstance(value, str):
                yield f"sample_rows[{row}].{key}", value


# ---------------------------------------------------------------------------
# Tier 2 (ADR-0026 Decision 3): the hand-authored applicability table over
# the 48 chart types. Never derived from `vocab.json`'s own signals — they
# are the tripwire (test below), not the source (ADR-0026 Context).
# ---------------------------------------------------------------------------

_TIER2_ITEMS: tuple[Tier2CheckName, ...] = (
    "marks_present",
    "axis_labels_present",
    "legend_presence",
    "label_overlap",
    "bar_chart_y_axis_baseline",
)

# Chart types with no cartesian x/y axes, so `axis_labels_present` can never
# resolve for them. Two layers, per ADR-0026's own worked example: the 11
# types with no `x`/`y` channel on any backend, plus the three the naive
# "has an x/y channel" heuristic gets wrong — Radar (polar axes), Sankey and
# Network Graph (a layout, not axes) all declare `x`/`y` in the pin without
# drawing a cartesian plot.
_NON_CARTESIAN: frozenset[str] = frozenset(
    {
        "Choropleth",
        "Donut Chart",
        "Doughnut Chart",
        "Gauge Chart",
        "KPI Card",
        "Map",
        "Parallel Coordinates",
        "Pie Chart",
        "Sunburst Chart",
        "Tree",
        "Treemap",
        "Radar Chart",
        "Sankey Diagram",
        "Network Graph",
    }
)

# The length-mark family (`mark_cognitive_channel == "length"` on at least
# one backend, at the flint-chart 0.5.1 pin) — every one gets
# `bar_chart_y_axis_baseline`. Checked against the live pin by
# `test_every_length_mark_chart_type_is_classified` below, so a Flint bump
# that adds a length-mark type fails a build instead of silently skipping
# the check (ADR-0026 Decision 3, exhaustiveness test 2).
_BASELINE_APPLICABLE: frozenset[str] = frozenset(
    {
        "Bar Chart",
        "Bar Table",
        "Bullet Chart",
        "Combo Chart",
        "Grouped Bar Chart",
        "Histogram",
        "Lollipop Chart",
        "Pyramid Chart",
        "Stacked Bar Chart",
        "Waterfall Chart",
    }
)

# A length-mark chart type the table deliberately does not baseline-check,
# with why. Empty at authoring time — every current length-mark type is in
# `_BASELINE_APPLICABLE` — kept so a future exemption has somewhere to go
# without weakening the exhaustiveness test into silently passing everything.
_BASELINE_EXEMPT: Mapping[str, str] = {}

# The subset of the global channel vocabulary Flint treats as a series
# channel (`SERIES_CHANNELS` in the vendored IIFE also lists "series" and
# "stroke", which are not names in our channel vocabulary at all —
# `strokeDash` is a distinct channel, not the same grouping heuristic, so it
# is deliberately left out here).
_SERIES_CHANNELS: frozenset[str] = frozenset({"color", "group", "detail", "shape"})


def _binds_series_channel(encodings: Mapping[str, object]) -> bool:
    return any(channel in encodings for channel in _SERIES_CHANNELS)


def applicable_tier2_items(
    chart_type: str, encodings: Mapping[str, object]
) -> tuple[Tier2CheckName, ...]:
    """Tier 2 items that can resolve for this (Flint) chart spec (ADR-0026
    Decision 3). An inapplicable item is omitted entirely, never
    ``not_checked`` — the host can know, on Flint, before ever calling the
    critic."""
    items: list[Tier2CheckName] = ["marks_present", "label_overlap"]
    if chart_type not in _NON_CARTESIAN:
        items.append("axis_labels_present")
    if _binds_series_channel(encodings):
        items.append("legend_presence")
    if chart_type in _BASELINE_APPLICABLE:
        items.append("bar_chart_y_axis_baseline")
    return tuple(name for name in _TIER2_ITEMS if name in items)


def _flint_length_mark_chart_types() -> frozenset[str]:
    """Read live from ``vocab.json`` — the tripwire ADR-0026 Decision 3's
    second exhaustiveness test runs against, never the source of truth for
    ``applicable_tier2_items`` itself."""
    import json
    from pathlib import Path

    vocab_path = Path(__file__).with_name("frame") / "vocab.json"
    raw = json.loads(vocab_path.read_text(encoding="utf-8"))
    backends = raw.get("backends", {})
    found: set[str] = set()
    for charts in backends.values():
        for chart_type, spec in charts.items():
            if spec.get("mark_cognitive_channel") == "length":
                found.add(chart_type)
    return frozenset(found)


def _verdict_to_check(name: Tier2CheckName, critique_result: Critique) -> CheckResult:
    verdict = critique_result.verdicts[name]
    return CheckResult(name, to_check_outcome(verdict), critique_result.note)


def flint_review(
    profile: Profile,
    frame: InputFrame,
    envelope: Envelope,
    backend: Backend,
    instruction: str,
    *,
    rasteriser: Rasteriser | None,
    critique_client: ModelClient | None,
) -> ReviewReport:
    """Tier 1, which rasterises once when a rasteriser is supplied and scores
    ``painted`` from the picture, then — when a critic is also supplied and
    Tier 1 did not fail — a Flint critique on the same PNG (ADR-0026,
    ADR-0027, #254). Stops at
    the report: review repair (spending the ``quality=`` budget on a
    repairable fail) is the planner's loop, so ``budget_exhausted`` stays
    false here."""
    checks = _tier1_checks(profile, backend)
    tier1_failed = any(check.outcome == "fail" for check in checks)
    if tier1_failed:
        return ReviewReport(
            tiers_run=(1,),
            tiers_skipped={2: "blocked"},
            passed=False,
            budget_exhausted=False,
            checks=tuple(checks),
        )
    png: bytes | None = None
    if rasteriser is not None:
        png = rasteriser.rasterise(envelope)
        raster = decode_png(png)
        checks = [
            _painted(raster) if check.name == "painted" else check for check in checks
        ]
        # A blank canvas has no palette to judge, so the palette check stays
        # not_checked on a `painted` fail.
        if not any(check.outcome == "fail" for check in checks):
            checks = [
                _colorblind_safe_palette(raster)
                if check.name == "colorblind_safe_palette"
                else check
                for check in checks
            ]
        if any(check.outcome == "fail" for check in checks):
            return ReviewReport(
                tiers_run=(1,),
                tiers_skipped={2: "blocked"},
                passed=False,
                budget_exhausted=False,
                checks=tuple(checks),
            )
    tier1_resolved = any(check.outcome != "not_checked" for check in checks)
    if png is None or critique_client is None:
        return ReviewReport(
            tiers_run=(1,),
            tiers_skipped={2: "unavailable"},
            passed=tier1_resolved,
            budget_exhausted=False,
            checks=tuple(checks),
        )

    encodings = {
        channel: encoding.field
        for channel, encoding in frame.chart_spec.encodings.items()
    }
    items = applicable_tier2_items(frame.chart_spec.chart_type, encodings)
    context = CritiqueContext(
        instruction=instruction,
        chart_type=frame.chart_spec.chart_type,
        backend=backend,
        encodings=encodings,
        row_count=envelope.row_count,
        items=items,
    )
    result = critique(png, context, client=critique_client)
    tier2_checks = tuple(_verdict_to_check(name, result) for name in items)
    all_checks = tuple(checks) + tier2_checks
    any_fail = any(check.outcome == "fail" for check in all_checks)
    tier2_resolved = any(check.outcome != "not_checked" for check in tier2_checks)
    return ReviewReport(
        tiers_run=(1, 2),
        tiers_skipped={},
        passed=tier1_resolved and tier2_resolved and not any_fail,
        budget_exhausted=False,
        checks=all_checks,
    )
