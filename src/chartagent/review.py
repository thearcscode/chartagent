"""``ReviewReport`` and ``CheckResult`` — the review gate's result types
(ADR-0005 Decision 9, ADR-0024), with the Tier-1 checks that need no
rasteriser.

Thin by design: there is no ``Rasteriser`` and no Tier 2 yet, so the raster
checks report ``not_checked`` ("unavailable") and Tier 2 lands in
``tiers_skipped``. An internal error in a check raises; it never becomes a
``CheckResult`` (ADR-0024 Decision 2).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Literal

from chartagent.frame.input import Backend
from chartagent.profile.models import Profile, StringColumn

CheckName = Literal[
    "injection_pattern", "painted", "colorblind_safe_palette", "data_truthfulness"
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


def tier1_review(profile: Profile, *, backend: Backend | None) -> ReviewReport:
    """Tier 1 for one artifact. ``backend`` is ``None`` on the custom rail.

    Which checks appear follows ADR-0024 Decision 4: Excel gets only
    ``injection_pattern``; Flint adds ``painted`` and
    ``colorblind_safe_palette``; the custom rail adds ``colorblind_safe_palette``
    and ``data_truthfulness``. The image-derived ones are ``not_checked`` —
    they could pass or fail with a rasteriser, and none is wired."""
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
