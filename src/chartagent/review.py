"""``ReviewReport`` and ``CheckResult`` — the review gate's result types
(ADR-0005 Decision 9, ADR-0024), the Tier-1 checks (``injection_pattern``
needs no rasteriser; ``painted`` and ``colorblind_safe_palette`` need one),
and Tier 2 (ADR-0026, ADR-0027): the applicability table over the 48 chart
types and ``flint_review``, which runs Tier 1 then, when a rasteriser and a
critic are both supplied, a Flint critique. :func:`custom_review` is the
custom rail's counterpart (#264): it paints the recipe once as a
``BoundDocument`` and scores ``colorblind_safe_palette`` and
``data_truthfulness`` from that paint.

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
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import pyarrow as pa

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
from chartagent.rasterise import DocumentPaint, Rasteriser
from chartagent.recipe import BoundDocument, ChartRecipe

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


def _blocked_report(checks: Sequence[CheckResult]) -> ReviewReport:
    """A Tier-1 fail: the report stops here and Tier 2 is blocked."""
    return ReviewReport(
        tiers_run=(1,),
        tiers_skipped={2: "blocked"},
        passed=False,
        budget_exhausted=False,
        checks=tuple(checks),
    )


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
        return _blocked_report(checks)
    png: bytes | None = None
    if rasteriser is not None:
        png = rasteriser.rasterise(envelope)
        raster = decode_png(png)
        checks = [
            _painted(raster) if check.name == "painted" else check for check in checks
        ]
        # A blank canvas has no palette to judge, so the palette check stays
        # not_checked on a `painted` fail, with a detail that says why.
        painted_failed = any(check.outcome == "fail" for check in checks)
        checks = [
            (
                CheckResult(
                    "colorblind_safe_palette",
                    "not_checked",
                    "canvas is blank: no palette to judge",
                )
                if painted_failed
                else _colorblind_safe_palette(raster)
            )
            if check.name == "colorblind_safe_palette"
            else check
            for check in checks
        ]
        if any(check.outcome == "fail" for check in checks):
            return _blocked_report(checks)
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


# ADR-0025 Decision 6: frozen in library code, never configuration.
_REL_TOL = 1e-9
_ABS_TOL = 1e-12
# The declaration of a paint that offered none (a protocol-only rasteriser).
_NO_DECLARATION: object = object()


def _paint_png(rasteriser: Rasteriser, bound: BoundDocument) -> tuple[bytes, object]:
    """One paint. A rasteriser that offers the sibling ``paint_document``
    (#265) paints once and returns a ``DocumentPaint``; its PNG and the
    module's ``getPlottedSeries()`` declaration come back. A protocol-only one
    is asked for the PNG alone and the declaration is ``_NO_DECLARATION``.
    Duck-typed: the ``Rasteriser`` protocol is unchanged."""
    paint = getattr(rasteriser, "paint_document", None)
    if paint is None:
        return rasteriser.rasterise(bound), _NO_DECLARATION
    painted: DocumentPaint = paint(bound)
    return painted.png, painted.declaration


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _scalar_equal(declared: object, real: object) -> bool:
    if _is_number(declared) and _is_number(real):
        d, r = float(declared), float(real)  # type: ignore[arg-type]
        return abs(d - r) <= max(_REL_TOL * max(abs(d), abs(r)), _ABS_TOL)
    return type(declared) is type(real) and declared == real


def _point_matches(point: Mapping[str, object], row: Mapping[str, object]) -> bool:
    return all(
        key in row and _scalar_equal(value, row[key]) for key, value in point.items()
    )


def _valid_point(point: object) -> bool:
    return (
        isinstance(point, dict)
        and len(point) > 0
        and all(
            isinstance(key, str)
            and key != ""
            and (value is None or isinstance(value, (str, int, float, bool)))
            for key, value in point.items()
        )
    )


def _data_truthfulness(
    declaration: object, rows: Sequence[Mapping[str, object]]
) -> CheckResult:
    """ADR-0025: a shape gate, then multiset containment of the declared
    points in the bound rows. Pure: the declaration and rows in, a verdict
    out. ``detail`` is display-only and echoes no row values."""
    if (
        not isinstance(declaration, list)
        or not declaration
        or not all(_valid_point(point) for point in declaration)
    ):
        return CheckResult(
            "data_truthfulness", "not_checked", "no comparable declaration"
        )
    owner: dict[int, int] = {}  # row index -> point index

    def assign(point_index: int, seen: set[int]) -> bool:
        for row_index, row in enumerate(rows):
            if row_index in seen or not _point_matches(declaration[point_index], row):
                continue
            seen.add(row_index)
            if row_index not in owner or assign(owner[row_index], seen):
                owner[row_index] = point_index
                return True
        return False

    for position, point in enumerate(declaration, start=1):
        if assign(position - 1, set()):
            continue
        known = {key for row in rows for key in row}
        unknown = next((key for key in point if key not in known), None)
        if unknown is not None:
            detail = f"point {position}: unknown column {unknown!r}"
        else:
            column = next(
                (
                    key
                    for key in point
                    if not any(
                        key in row and _scalar_equal(point[key], row[key])
                        for row in rows
                    )
                ),
                None,
            )
            if column is not None:
                detail = f"point {position}: {column!r} matches no row"
            else:
                detail = f"point {position}: no unused row left to match"
        return CheckResult("data_truthfulness", "fail", detail)
    return CheckResult("data_truthfulness", "pass")


def custom_review(
    profile: Profile,
    recipe: ChartRecipe,
    rows: Sequence[Mapping[str, object]],
    libraries: Mapping[str, bytes],
    instruction: str,
    *,
    rasteriser: Rasteriser | None,
    critique_client: ModelClient | None,
) -> ReviewReport:
    """The custom rail's review, symmetric to :func:`flint_review`
    (ADR-0024, ADR-0026; #266). ``injection_pattern`` runs first and a fail
    returns at once with no paint. With a rasteriser the recipe is painted
    once and ``colorblind_safe_palette`` is scored from that PNG; ``painted``
    is omitted on this rail. ``data_truthfulness`` is scored from the
    painted module's declaration against ``rows`` (ADR-0025; #267), and
    stays ``not_checked`` "unavailable" without a ``paint_document``. When a
    critic is supplied and Tier 1 did not fail, Tier 2 runs on the same PNG
    with the custom-rail context: the instruction, the transform-output column names and
    ``row_count``. Stops at the report; repair is the planner's loop."""
    checks = _tier1_checks(profile, None)
    if any(check.outcome == "fail" for check in checks):
        return _blocked_report(checks)
    png: bytes | None = None
    if rasteriser is not None:
        bound = BoundDocument(
            document=recipe.document,
            rows=pa.Table.from_pylist([dict(row) for row in rows]),
            theme={},
            libraries=libraries,
        )
        png, declaration = _paint_png(rasteriser, bound)
        raster = decode_png(png)
        resolved: list[CheckResult] = []
        for check in checks:
            if check.name == "colorblind_safe_palette":
                check = _colorblind_safe_palette(raster)
            elif (
                check.name == "data_truthfulness" and declaration is not _NO_DECLARATION
            ):
                check = _data_truthfulness(declaration, rows)
            resolved.append(check)
        checks = resolved
        if any(check.outcome == "fail" for check in checks):
            return _blocked_report(checks)
    tier1_resolved = any(check.outcome != "not_checked" for check in checks)
    if png is None or critique_client is None:
        return ReviewReport(
            tiers_run=(1,),
            tiers_skipped={2: "unavailable"},
            passed=tier1_resolved,
            budget_exhausted=False,
            checks=tuple(checks),
        )
    columns = tuple(dict.fromkeys(key for row in rows for key in row))
    context = CritiqueContext(
        instruction=instruction,
        row_count=len(rows),
        items=_TIER2_ITEMS,
        columns=columns,
    )
    result = critique(png, context, client=critique_client)
    tier2_checks = tuple(_verdict_to_check(name, result) for name in _TIER2_ITEMS)
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
