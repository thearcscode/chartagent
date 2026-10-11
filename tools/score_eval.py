"""The eval gate on the frozen 150 (ADR-0029, spec #271).

Reads the frozen ``eval/pre-registration.json`` and one run's harness records,
then either accepts the run or refuses with a named reason. This slice (#280)
scores nothing: it proves the gate cannot be fooled about *which* set it is
scoring. Later slices extend ``score`` with the published figures.

Exit codes: 0 report written, 1 named check failed, 2 usage error.

    python tools/score_eval.py <outputs.json> --mode nightly --json <r.json>
        [--repo DIR] [--prereg FILE] [--instrument NAME=FILE ...] [--date YYYY-MM-DD]

Writes by mode: only ``publish`` writes eval/report.{json,md}, eval/outputs.json
and the dated copy under eval/runs/<date>/ (fixed paths; --json/--md refused).
``nightly`` and ``smoke`` write nothing under eval/. ``holdout`` writes only
under eval/holdout/. A refused run writes nothing.

Files:
  * pre-registration: ``requests`` (the public 150; each ``id``, ``instruction``,
    ``dataset_path``, ``dataset_sha256``), ``holdout_pool`` (same shape),
    ``holdout_permutation``, ``smoke_ids``, ``human_calibration_permutation``.
  * outputs.json: ``{"records": [{"request_id", "quality", ...}]}``, one record
    per (case, quality). Harness records only, never PNG bytes.
  * eval/report-notes.md: a publish run that misses a balanced target needs one
    dated "Named review" entry in it (format: see the #278 section below).
  * ``--instrument``: another instrument's requests, a JSON list or an object
    with ``requests``; each entry carries ``instruction`` (or
    ``query_rewritten``) and ``dataset_sha256``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from datetime import date as _date
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
TAG = "eval-benchmark-v1"
PREREG_IN_TAG = "eval/pre-registration.json"
MODES = ("smoke", "nightly", "holdout", "publish")
QUALITIES = ("fast", "balanced", "best")
HOLDOUT_SIZE = 30
EXECUTABLE_TARGET = 0.95
RUBRIC_TARGET = 0.85
REFERENCE_QUALITY = "balanced"
_PNG_MARKERS = ("iVBORw0KGgo", "\x89PNG", "data:image/png")
_FLINT_ONLY_FIELDS = ("painted", "compiled_row_count", "bound_row_count")


def _wilson_interval(k: int, n: int) -> dict[str, float]:
    """The pressure-corpus scorer's Wilson implementation, loaded not copied."""
    path = Path(__file__).with_name("score_corpus.py")
    spec = importlib.util.spec_from_file_location("_score_corpus_wilson", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result: dict[str, float] = module.wilson_interval(k, n)
    return result


class Refusal(Exception):
    """The gate refuses the run; ``issues`` are the named, printable reasons."""

    def __init__(self, issues: list[str]) -> None:
        super().__init__("; ".join(issues))
        self.issues = issues


def _issue(name: str, text: str) -> str:
    return f"{name:<12}{text}"


def _canonical(data: bytes) -> bytes:
    """Hash the pre-registration as LF. A Windows CRLF checkout is the same freeze."""
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def digest(data: bytes) -> str:
    return hashlib.sha256(_canonical(data)).hexdigest()


def tagged_digest(repo: Path) -> str | None:
    """The digest of the pre-registration at the tag, or None if there is no tag.

    There is deliberately no fallback constant: an unfrozen set must never look
    frozen.
    """
    result = subprocess.run(
        ["git", "show", f"{TAG}:{PREREG_IN_TAG}"],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    if result.returncode == 0 and result.stdout:
        return digest(result.stdout)
    return None


def _ids(items: Iterable[Mapping[str, Any]]) -> list[str]:
    return [str(item["id"]) for item in items]


def expected_ids(prereg: Mapping[str, Any], mode: str) -> list[str]:
    if mode == "smoke":
        return [str(i) for i in prereg.get("smoke_ids") or []]
    if mode == "holdout":
        return [str(i) for i in prereg.get("holdout_permutation") or []][:HOLDOUT_SIZE]
    return _ids(prereg.get("requests") or [])


def _id_issues(
    prereg: Mapping[str, Any], mode: str, pairs: set[tuple[str, str]]
) -> list[str]:
    expected = set(expected_ids(prereg, mode))
    holdout = set(_ids(prereg.get("holdout_pool") or []))
    allowed = ("balanced",) if mode == "smoke" else QUALITIES
    issues: list[str] = []
    by_quality: dict[str, set[str]] = {}
    for case_id, quality in pairs:
        by_quality.setdefault(quality, set()).add(case_id)
    for quality in sorted(by_quality):
        if quality not in allowed:
            issues.append(
                _issue(
                    "IDS",
                    f"quality {quality!r} is not allowed in a {mode} run "
                    f"(allowed: {', '.join(allowed)})",
                )
            )
    for quality in allowed:
        if quality not in by_quality and mode == "smoke":
            by_quality[quality] = set()
    if mode == "publish":
        absent = [q for q in QUALITIES if q not in by_quality]
        if absent:
            issues.append(
                _issue(
                    "IDS",
                    f"a publish run needs all three qualities; "
                    f"missing {', '.join(absent)}",
                )
            )
    for quality in sorted(q for q in by_quality if q in allowed):
        got = by_quality[quality]
        parts: list[str] = []
        missing = sorted(expected - got)
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        leaked = sorted((got - expected) & holdout) if mode != "holdout" else []
        if leaked:
            parts.append(f"hold-out id in a {mode} run: {', '.join(leaked)}")
        extra = sorted(got - expected - set(leaked))
        if extra:
            parts.append(f"extra {', '.join(extra)}")
        if parts:
            issues.append(
                _issue("IDS", f"{quality}: record set is not the {mode} ID set: ")
                + "; ".join(parts)
            )
    return issues


def _overlap_issues(
    prereg: Mapping[str, Any],
    instruments: Mapping[str, Iterable[tuple[str, str]]],
) -> list[str]:
    issues: list[str] = []
    requests = [*(prereg.get("requests") or []), *(prereg.get("holdout_pool") or [])]
    for name in sorted(instruments):
        pairs = set(instruments[name])
        hit = [
            str(r["id"])
            for r in requests
            if (str(r.get("instruction")), str(r.get("dataset_sha256"))) in pairs
        ]
        if hit:
            issues.append(
                _issue(
                    "OVERLAP",
                    f"(instruction, dataset sha256) shared with {name}: "
                    f"{', '.join(hit)}",
                )
            )
    return issues


def _carries_png(value: Any) -> bool:
    if isinstance(value, (bytes, bytearray)):
        return True
    if isinstance(value, str):
        return value.startswith(_PNG_MARKERS)
    if isinstance(value, Mapping):
        return any(_carries_png(v) for v in value.values())
    if isinstance(value, list):
        return any(_carries_png(v) for v in value)
    return False


def _record_issues(record: Mapping[str, Any]) -> list[str]:
    """Refusals for one record: harness faults and authoring faults, not misses."""
    name = f"{record['request_id']} ({record['quality']})"
    issues: list[str] = []
    if record.get("create_chart_calls", 1) != 1:
        issues.append(
            _issue(
                "CALLS",
                f"{name}: {record.get('create_chart_calls')} create_chart calls; "
                "exactly one per (case, quality), no retries or majority-of-three",
            )
        )
    if _carries_png(record):
        issues.append(
            _issue("PNG", f"{name}: outputs.json carries PNG bytes; records only")
        )
    if str(record.get("backend") or "").lower() == "excel":
        issues.append(
            _issue("AUTHORING", f"{name}: names the Excel backend, an authoring fault")
        )
    rail = record.get("rail")
    if rail == "flint":
        if record.get("painted") not in ("pass", "fail", "not_checked") and not (
            record.get("error")
        ):
            issues.append(
                _issue(
                    "RAIL",
                    f"{name}: Flint record has no painted verdict "
                    "(a custom-rail record mislabelled flint?)",
                )
            )
        if record.get("painted") == "not_checked":
            issues.append(
                _issue(
                    "HARNESS",
                    f"{name}: Flint record has painted: not_checked; "
                    "the harness is misconfigured (no rasteriser)",
                )
            )
    elif rail == "custom":
        stray = [f for f in _FLINT_ONLY_FIELDS if f in record]
        if stray or record.get("backend") not in (None, "custom"):
            issues.append(
                _issue(
                    "RAIL",
                    f"{name}: custom-rail record carries Flint fields "
                    f"{', '.join(stray) or 'backend'}; a custom hit is the "
                    "rasteriser's verdict, never a painted CheckResult",
                )
            )
    else:
        issues.append(_issue("RAIL", f"{name}: rail {rail!r} is not flint or custom"))
    return issues


def _is_hit(record: Mapping[str, Any]) -> bool:
    if record.get("error"):
        return False
    if record.get("rail") == "custom":
        return record.get("raster_nonblank") is True
    return (
        record.get("painted") == "pass"
        and record.get("compiled_row_count") is not None
        and record.get("compiled_row_count") == record.get("bound_row_count")
    )


def _spans(interval: Mapping[str, float], target: float) -> bool:
    return interval["lower"] <= target <= interval["upper"]


def _executable(records: Iterable[Mapping[str, Any]], n: int) -> dict[str, Any]:
    misses: dict[str, list[str]] = {}
    hits: dict[str, int] = {}
    for record in records:
        quality = str(record["quality"])
        hits.setdefault(quality, 0)
        misses.setdefault(quality, [])
        if _is_hit(record):
            hits[quality] += 1
        else:
            misses[quality].append(str(record["request_id"]))
    by_quality: dict[str, Any] = {}
    for quality in sorted(hits):
        k = hits[quality]
        interval = _wilson_interval(k, n)
        by_quality[quality] = {
            "k": k,
            "n": n,
            "rate": k / n if n else 0.0,
            "wilson_95": interval,
            "misses": sorted(misses[quality]),
        }
        if quality == REFERENCE_QUALITY:
            by_quality[quality]["interval_spans_target"] = _spans(
                interval, EXECUTABLE_TARGET
            )
    return {"target": EXECUTABLE_TARGET, "by_quality": by_quality}


# --- rubric pass rate over executable hits (#273) ----------------------------

APPROPRIATENESS = "chart_type_appropriateness"
CUSTOM_ITEMS = (
    "marks_present",
    "label_overlap",
    "axis_labels_present",
    "legend_presence",
    "bar_chart_y_axis_baseline",
)
_BANNED_PROVENANCE = ("ReviewReport", "critic_note", "module")
_FAMILIES = (
    ("anthropic", ("claude", "anthropic")),
    ("google", ("gemini", "google", "gemma")),
    ("openai", ("gpt", "openai", "o1", "o3", "o4")),
)


def _family(model: str) -> str:
    """The vendor family of a model id, with or without a ``vendor:`` prefix."""
    name = model.lower().rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    for family, markers in _FAMILIES:
        if any(name.startswith(m) for m in markers):
            return family
    return name.split("-", 1)[0]


def _sent_items(verdict: Mapping[str, Any]) -> tuple[str, ...]:
    """What the judge was sent: the Tier-2 host table on Flint, all five on the
    custom rail, and chart-type appropriateness always."""
    if verdict.get("rail") == "custom":
        return (*CUSTOM_ITEMS, APPROPRIATENESS)
    from chartagent.review import applicable_tier2_items

    items = applicable_tier2_items(
        str(verdict.get("chart_type")), verdict.get("encodings") or {}
    )
    return (*items, APPROPRIATENESS)


def _judge_issues(
    verdicts: list[Mapping[str, Any]],
    records: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[str]:
    issues: list[str] = []
    for v in verdicts:
        key = (str(v.get("request_id")), str(v.get("quality")))
        name = f"{key[0]} ({key[1]})"
        record = records.get(key)
        if record is None or not _is_hit(record):
            issues.append(
                _issue(
                    "JUDGE",
                    f"{name}: verdict for a case with no executable hit; "
                    "the judge never runs without a picture",
                )
            )
            continue
        if not v.get("png_sha256"):
            issues.append(
                _issue("JUDGE", f"{name}: verdict has no PNG; the judge needs one")
            )
        if _family(str(v.get("judge_model"))) == _family(str(v.get("critic_model"))):
            issues.append(
                _issue(
                    "FAMILY",
                    f"{name}: judge {v.get('judge_model')} is in the critic's "
                    f"family ({v.get('critic_model')})",
                )
            )
        banned = [b for b in _BANNED_PROVENANCE if b in (v.get("provenance") or [])]
        if banned:
            issues.append(
                _issue(
                    "PROVENANCE",
                    f"{name}: judge provenance includes {', '.join(banned)}",
                )
            )
    judged = {(str(v.get("request_id")), str(v.get("quality"))) for v in verdicts}
    for key in sorted(k for k, r in records.items() if _is_hit(r) and k not in judged):
        issues.append(
            _issue("JUDGE", f"{key[0]} ({key[1]}): executable hit has no verdict")
        )
    return issues


def _rubric(
    records: Iterable[Mapping[str, Any]],
    verdicts: Iterable[Mapping[str, Any]],
    n: int,
) -> dict[str, Any]:
    hits: dict[str, int] = {}
    for record in records:
        quality = str(record["quality"])
        hits.setdefault(quality, 0)
        hits[quality] += 1 if _is_hit(record) else 0
    passed: dict[str, int] = {q: 0 for q in hits}
    failed: dict[str, list[str]] = {q: [] for q in hits}
    unchecked: dict[str, dict[str, int]] = {q: {} for q in hits}
    for v in verdicts:
        quality = str(v["quality"])
        given = v.get("verdicts") or {}
        ok = True
        for item in _sent_items(v):
            outcome = given.get(item, "not_checked")
            unchecked[quality].setdefault(item, 0)
            if outcome == "not_checked":
                unchecked[quality][item] += 1
            ok = ok and outcome == "pass"
        if ok:
            passed[quality] += 1
        else:
            failed[quality].append(str(v["request_id"]))
    by_quality: dict[str, Any] = {}
    for quality in sorted(hits):
        k, total = passed[quality], hits[quality]
        by_quality[quality] = {
            "k": k,
            "n": total,
            "excluded": n - total,
            "rate": k / total if total else 0.0,
            "wilson_95": _wilson_interval(k, total),
            "failed": sorted(failed[quality]),
            "not_checked_by_item": dict(sorted(unchecked[quality].items())),
        }
        if quality == REFERENCE_QUALITY:
            by_quality[quality]["interval_spans_target"] = _spans(
                by_quality[quality]["wilson_95"], RUBRIC_TARGET
            )
    return {"target": RUBRIC_TARGET, "by_quality": by_quality}


def _rubric_markdown(report: Mapping[str, Any]) -> list[str]:
    lines = [
        "",
        "## Rubric pass rate",
        "",
        "Executable hits only; the excluded count never reached the judge. A "
        "case passes only if every sent item is `pass`.",
        "",
        "| Quality | Passed | Rate | Wilson 95% | Excluded |",
        "| --- | --- | --- | --- | --- |",
    ]
    rows = report["rubric"]["by_quality"]
    for quality, row in rows.items():
        w = row["wilson_95"]
        lines.append(
            f"| {quality} | {row['k']}/{row['n']} | {row['rate']:.3f} | "
            f"Wilson 95% [{w['lower']:.3f}, {w['upper']:.3f}] | "
            f"{row['excluded']} excluded |"
        )
    balanced = rows.get(REFERENCE_QUALITY)
    if balanced is not None:
        where = "spans" if balanced["interval_spans_target"] else "does not span"
        lines += [
            "",
            f"The {report['rubric']['target']:.0%} reference line is read from "
            f"{REFERENCE_QUALITY} only; its interval {where} it.",
        ]
    for quality, row in rows.items():
        counts = ", ".join(f"{i} {c}" for i, c in row["not_checked_by_item"].items())
        lines += ["", f"`not_checked` at {quality}: {counts}"]
    return lines


# --- the figure allow-list and the delivery companion (#274) -----------------
#
# The report publishes exactly the figures ADR-0029 defines, each with its
# denominator in words. ``FIGURES`` is the allow-list; ``REPORT_META`` is every
# other top-level key (provenance, no figures). ``enforce_allow_list`` runs on
# every report, so a figure outside the set cannot be rendered. To add a
# figure, add it to ``FIGURES`` through ``_figure`` (which refuses any name or
# denominator the ADR does not define: the rubric pass rate is only ever over
# executable hits) and put its section in the report.

REPORT_META = (
    "status",
    "mode",
    "tag",
    "prereg_sha256",
    "flint_version",
    "fixture_commit",
    "n",
    "qualities",
    "cell1",
    "designed_miss_budget",
    "reference_lines",
    "named_review",
    "cost_latency_misses",
)
_DENOMINATORS = {
    "executable": "every request",
    "delivery": "served",
    "rubric": "executable hits",
}


class Figure:
    def __init__(self, name: str, title: str, definition: str, denominator: str):
        check_figure(name, denominator)
        self.name = name
        self.title = title
        self.definition = definition
        self.denominator = denominator


def check_figure(name: str, denominator: str) -> None:
    """Refuse a figure the ADR does not define, or one over the wrong denominator."""
    if name not in _DENOMINATORS:
        raise ValueError(f"figure {name!r} is not in the ADR-0029 allow-list")
    if _DENOMINATORS[name] not in denominator:
        raise ValueError(
            f"figure {name!r} must be over {_DENOMINATORS[name]}, got {denominator!r}"
        )


def _figure(name: str, title: str, definition: str, denominator: str) -> Figure:
    return Figure(name, title, definition, denominator)


FIGURES: dict[str, Figure] = {
    f.name: f
    for f in (
        _figure(
            "executable",
            "Executable-output rate",
            "the share of requests whose output built and drew a non-blank chart",
            "every request in the set (n is the frozen set size); raises, blank "
            "canvases and raster/assemble throws are misses",
        ),
        _figure(
            "delivery",
            "Delivery rate",
            "the share of served Flint-rail requests that painted with the "
            "compiled row count equal to the bound row count",
            "served requests only (a record without an error); the excluded "
            "count of unserved requests is published beside it",
        ),
        _figure(
            "rubric",
            "Rubric pass rate",
            "the share of judged cases where every sent item is pass; "
            "not_checked on a sent item fails the case",
            "executable hits only; the excluded count (raises, blanks, throws) "
            "is published beside it",
        ),
    )
}


def enforce_allow_list(report: Mapping[str, Any]) -> None:
    """Raise unless every top-level key is provenance or an allow-listed figure."""
    for key in report:
        if key not in REPORT_META and key not in FIGURES:
            raise ValueError(f"report key {key!r} is not an allow-listed figure")


def _delivery(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Served-only delivery (the Q1 predicate), per quality, excluded count beside.

    Flint rail only: ``painted`` and the row counts are Flint-rail concepts, and
    the custom rail's verdict is the rasteriser's, so it is not in this figure.
    """
    delivered: dict[str, int] = {}
    served: dict[str, int] = {}
    excluded: dict[str, list[str]] = {}
    for record in records:
        if record.get("rail") != "flint":
            continue
        quality = str(record["quality"])
        delivered.setdefault(quality, 0)
        served.setdefault(quality, 0)
        excluded.setdefault(quality, [])
        if record.get("error"):
            excluded[quality].append(str(record["request_id"]))
            continue
        served[quality] += 1
        if _is_hit(record):
            delivered[quality] += 1
    by_quality = {
        quality: {
            "delivered": delivered[quality],
            "served": served[quality],
            "rate": delivered[quality] / served[quality] if served[quality] else 0.0,
            "excluded": len(excluded[quality]),
            "excluded_ids": sorted(excluded[quality]),
        }
        for quality in sorted(delivered)
    }
    return {"by_quality": by_quality}


def _definitions_markdown() -> list[str]:
    lines = ["", "## Definitions", ""]
    for figure in FIGURES.values():
        lines.append(
            f"- **{figure.title}**: {figure.definition}. "
            f"Denominator: {figure.denominator}."
        )
    lines.append(
        "- The two rates stand beside each other and are never multiplied together."
    )
    return lines


def _delivery_markdown(report: Mapping[str, Any]) -> list[str]:
    lines = [
        "",
        "## Delivery rate",
        "",
        "| Quality | Delivered | Served | Rate | Excluded (not served) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for quality, row in report["delivery"]["by_quality"].items():
        excluded = ", ".join(row["excluded_ids"]) or "none"
        lines.append(
            f"| {quality} | {row['delivered']} | {row['served']} | "
            f"{row['rate']:.3f} | {row['excluded']} ({excluded}) |"
        )
    return lines


# --- cell-1 era and designed-miss budget (#275) ------------------------------

CELL1_RAISES_BEFORE_SEAM = 4
ROW_DROPS = 2
DISCRETIONARY_BEFORE_SEAM = 1
ERAS = ("auto", "shipped", "absent")


def seam_in_wheel() -> bool:
    """True when the ``generate_recipe`` seam (ADR-0030) is importable."""
    try:
        from chartagent.plan.recipe import generate_recipe  # noqa: F401
    except ImportError:
        return False
    return True


def _cell1(
    prereg: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]],
    mode: str,
    *,
    era_flag: str,
) -> dict[str, Any]:
    """Read cell-1 by era. The tag is never consulted for an expected outcome."""
    shipped = seam_in_wheel() if era_flag == "auto" else era_flag == "shipped"
    in_run = set(expected_ids(prereg, mode))
    cases = [
        item
        for item in [
            *(prereg.get("requests") or []),
            *(prereg.get("holdout_pool") or []),
        ]
        if item.get("cell") == 1 and str(item["id"]) in in_run
    ]
    ids = sorted(str(item["id"]) for item in cases)
    by_quality: dict[str, Any] = {}
    for record in records:
        if str(record["request_id"]) not in ids:
            continue
        row = by_quality.setdefault(
            str(record["quality"]), {"hits": 0, "unexpected": []}
        )
        hit = _is_hit(record)
        row["hits"] += int(hit)
        if hit != shipped:
            row["unexpected"].append(str(record["request_id"]))
    for row in by_quality.values():
        row["unexpected"].sort()
    return {
        "era": "shipped" if shipped else "absent",
        "era_source": "detected" if era_flag == "auto" else "override",
        "expected_executable": shipped,
        "expected_rail": "custom",
        "case_ids": ids,
        "intents": {str(i["id"]): i.get("intent") for i in cases},
        "appropriateness_basis": "intent_tag",
        "by_quality": dict(sorted(by_quality.items())),
    }


def _budget(n: int, era: str) -> dict[str, Any]:
    before = CELL1_RAISES_BEFORE_SEAM + ROW_DROPS
    return {
        "era": era,
        "n": n,
        "before_seam": {
            "cell1_raises": CELL1_RAISES_BEFORE_SEAM,
            "row_drops": ROW_DROPS,
            "authored": before,
            "discretionary": DISCRETIONARY_BEFORE_SEAM,
        },
        "after_seam": {"row_drops": ROW_DROPS, "authored": ROW_DROPS},
        "ceilings": {
            "before_seam": {
                "authored": (n - before) / n if n else 0.0,
                "with_discretionary": (n - before - DISCRETIONARY_BEFORE_SEAM) / n
                if n
                else 0.0,
            },
            "after_seam": {"authored": (n - ROW_DROPS) / n if n else 0.0},
        },
    }


def _render_cell1(report: Mapping[str, Any]) -> list[str]:
    cell1 = report["cell1"]
    budget = report["designed_miss_budget"]
    ceil = budget["ceilings"]
    n = budget["n"]
    lines = ["", "## Cell-1 era and the designed-miss budget", ""]
    if cell1["era"] == "shipped":
        lines.append(
            f"The `generate_recipe` seam shipped ({cell1['era_source']}): cell-1 "
            "is an expected hit, read from the library, not from a stored tag."
        )
    else:
        lines.append(
            f"The `generate_recipe` seam absent ({cell1['era_source']}): cell-1 "
            "is an expected miss, scored as if the seam were not in the wheel."
        )
    lines.append(
        f"The tag is not edited and n stays {n} either way; cell-1 cases "
        f"({', '.join(cell1['case_ids']) or 'none'}) keep their uncarryable "
        "intent tag for appropriateness."
    )
    for quality, row in cell1["by_quality"].items():
        extra = (
            f"; against expectation: {', '.join(row['unexpected'])}"
            if row["unexpected"]
            else ""
        )
        lines.append(f"- {quality}: {row['hits']} cell-1 executable{extra}")
    lines += [
        "",
        f"Before the seam the corpus carries six authored misses: four cell-1 "
        f"raises and two row-drops, plus one discretionary. At n={n} that is "
        f"{ceil['before_seam']['authored']:.1%} ceiling on the authored six and "
        f"{ceil['before_seam']['with_discretionary']:.1%} with the discretionary one, "
        "so a rate near 94.7% is the budget, not a regression. After the seam "
        f"only the two row-drops remain ({ceil['after_seam']['authored']:.1%} ceiling).",
    ]
    return lines


def render_markdown(report: Mapping[str, Any]) -> str:
    executable = report["executable"]
    target = executable["target"]
    lines = [
        f"# Executable-output rate ({report['mode']})",
        "",
        f"Tag `{report['tag']}`, pre-registration `{report['prereg_sha256']}`.",
        f"Every request counts (n={report['n']}); raises, blank canvases and "
        f"raster/assemble throws are misses. {target:.0%} is a reference "
        "point, and the interval is the finding.",
        "",
        "| Quality | Hits | Rate | Wilson 95% | Interval vs reference |",
        "| --- | --- | --- | --- | --- |",
    ]
    for quality, row in executable["by_quality"].items():
        w = row["wilson_95"]
        if "interval_spans_target" not in row:
            where = f"no reference line ({REFERENCE_QUALITY} only)"
        elif row["interval_spans_target"]:
            where = "spans the reference"
        else:
            where = "above" if w["lower"] > target else "below"
        lines.append(
            f"| {quality} | {row['k']}/{row['n']} | {row['rate']:.3f} | "
            f"Wilson 95% [{w['lower']:.3f}, {w['upper']:.3f}] | {where} |"
        )
    for quality, row in executable["by_quality"].items():
        if row["misses"]:
            lines += ["", f"Misses at {quality}: {', '.join(row['misses'])}"]
    if "rubric" in report:
        lines += _rubric_markdown(report)
    lines += _render_cell1(report)
    lines += _render_review(report)
    lines += _delivery_markdown(report) + _definitions_markdown()
    return "\n".join(lines) + "\n"


# --- the named review on a missed target (#278) -------------------------------
#
# ADR-0029 Decision 12. Fires only on a ``publish`` run (the full set, every
# quality) whose ``balanced`` executable point estimate is under 95% or whose
# rubric point estimate is under 85%. A Wilson interval spanning the target is
# not a trip; fast, best, p95, smoke, nightly and hold-out never fire it.
#
# The gate does not fail the run for the miss. It blocks the publish write
# until ``eval/report-notes.md`` holds exactly one entry for the run's date:
#
#     **Named review (ADR-0029 Decision 12) — YYYY-MM-DD.**
#     <free text>
#
# An entry runs from its heading line to the next line that starts with ``**``.
# It must contain every missed case id (balanced executable misses, balanced
# rubric failures), the word of each target missed (``executable``, ``rubric``),
# every cost/latency miss name (see below), and must say that the pre-seam
# cell-1 raises and the two row-drops are named *as authored*. Nothing in a run
# or a note lowers 95% or 85%; that is a new ADR.
#
# Cost and latency misses (ADR-0028 D9) arrive as the optional run-level list
# ``outputs["cost_latency_misses"]`` of names such as ``cost_p50`` /
# ``latency_p50``; it is copied to ``report["cost_latency_misses"]``. The
# ADR-0028 table slice (#277) can fill it from its own table instead.

NOTES_PATH = "eval/report-notes.md"
_ENTRY_HEAD = re.compile(r"^\*\*Named review\b[^\n]*", re.MULTILINE | re.IGNORECASE)
_LOWERING = re.compile(
    r"\b(?:lower\w*|relax\w*|reduc\w*|soften\w*)\b[^.\n]{0,60}"
    r"(?:\btargets?\b|\b95\s*%|\b85\s*%)",
    re.IGNORECASE,
)
_TARGET_KEYS = ("executable_target", "rubric_target", "target", "targets")


def _entries_for(notes: str, day: str) -> list[str]:
    """Named-review entries dated ``day``: heading line through the next ``**``."""
    lines = notes.splitlines()
    found: list[str] = []
    for i, line in enumerate(lines):
        if not _ENTRY_HEAD.match(line) or day not in line:
            continue
        body = [line]
        for follow in lines[i + 1 :]:
            if follow.startswith("**"):
                break
            body.append(follow)
        found.append("\n".join(body))
    return found


def _named_review(
    report: Mapping[str, Any], outputs: Mapping[str, Any], mode: str
) -> dict[str, Any]:
    misses: list[str] = []
    if mode == "publish":
        ex = report["executable"]["by_quality"].get(REFERENCE_QUALITY)
        if ex is not None and ex["rate"] < EXECUTABLE_TARGET:
            misses += ["executable", *ex["misses"]]
        rub = (report.get("rubric") or {}).get("by_quality", {}).get(REFERENCE_QUALITY)
        if rub is not None and rub["rate"] < RUBRIC_TARGET:
            misses += ["rubric", *rub["failed"]]
        if misses:
            misses += [str(m) for m in outputs.get("cost_latency_misses") or []]
    return {"fires": bool(misses), "misses": misses}


def _review_issues(review: Mapping[str, Any], notes: str | None, day: str) -> list[str]:
    if not review["fires"]:
        return []
    where = f"{NOTES_PATH} needs one entry dated {day}"
    entries = _entries_for(notes or "", day)
    if not entries:
        return [
            _issue(
                "REVIEW",
                f"named review fires (a balanced target is missed): {where} "
                f"covering {', '.join(review['misses'])}",
            )
        ]
    if len(entries) > 1:
        return [_issue("REVIEW", f"{NOTES_PATH} has {len(entries)} entries dated {day}; one entry per run")]
    entry = entries[0]
    issues: list[str] = []
    if _LOWERING.search(entry):
        issues.append(
            _issue(
                "TARGET",
                f"{NOTES_PATH} entry {day} lowers 95% or 85%; that needs a new ADR",
            )
        )
    uncovered = [
        m
        for m in review["misses"]
        if not re.search(rf"(?<![\w-]){re.escape(m)}(?![\w-])", entry)
    ]
    if uncovered:
        issues.append(
            _issue(
                "REVIEW",
                f"{NOTES_PATH} entry {day} does not cover: {', '.join(uncovered)}",
            )
        )
    low = entry.lower()
    if not (
        "cell-1" in low and "row-drop" in low and "as authored" in low
    ):
        issues.append(
            _issue(
                "REVIEW",
                f"{NOTES_PATH} entry {day} must name the pre-seam cell-1 raises "
                "and the two row-drops as authored, not as a new lever",
            )
        )
    return issues


def _render_review(report: Mapping[str, Any]) -> list[str]:
    review = report["named_review"]
    if not review["fires"]:
        return []
    return [
        "",
        "## Named review (ADR-0029 Decision 12)",
        "",
        f"A balanced target was missed. {NOTES_PATH} holds the dated entry "
        f"covering: {', '.join(review['misses'])}. The pre-seam cell-1 raises "
        "and the two row-drops are named there as authored, not as a new "
        "lever. Neither 95% nor 85% is lowered by a run or a note.",
    ]


def score(
    prereg: Mapping[str, Any],
    outputs: Mapping[str, Any],
    *,
    mode: str,
    tag_digest: str | None,
    prereg_sha256: str,
    dataset_sha256: Mapping[str, str | None],
    instruments: Mapping[str, Iterable[tuple[str, str]]],
    cell1_era: str = "auto",
    notes: str | None = None,
    day: str = "",
) -> dict[str, Any]:
    """Accept the run and return its report, or raise ``Refusal``."""
    issues: list[str] = []
    if tag_digest is None:
        issues.append(
            _issue("TAG", f"tag {TAG} does not exist; no fallback digest is used")
        )
    elif prereg_sha256 != tag_digest:
        issues.append(
            _issue(
                "HASH",
                f"pre-registration digest {prereg_sha256} differs from "
                f"tag {TAG} digest {tag_digest}",
            )
        )

    for item in [*(prereg.get("requests") or []), *(prereg.get("holdout_pool") or [])]:
        case_id = str(item["id"])
        actual = dataset_sha256.get(case_id)
        if actual != item.get("dataset_sha256"):
            issues.append(
                _issue(
                    "DATASET",
                    f"{case_id} {item.get('dataset_path')} sha256 "
                    f"{actual or '(missing)'}, freeze says {item.get('dataset_sha256')}",
                )
            )

    seen: set[tuple[str, str]] = set()
    repeated: set[tuple[str, str]] = set()
    for record in outputs.get("records") or []:
        try:
            key = (str(record["request_id"]), str(record["quality"]))
        except (KeyError, TypeError):
            issues.append(
                _issue("PARSE", f"record lacks request_id/quality: {record!r}")
            )
            continue
        (repeated if key in seen else seen).add(key)
    for case_id, quality in sorted(repeated):
        issues.append(
            _issue("REPEATS", f"more than one record for ({case_id}, {quality})")
        )

    well_formed = [
        r
        for r in outputs.get("records") or []
        if isinstance(r, Mapping) and "request_id" in r and "quality" in r
    ]
    for record in well_formed:
        issues.extend(_record_issues(record))
    verdicts = [
        v for v in outputs.get("judge_verdicts") or [] if isinstance(v, Mapping)
    ]
    if mode == "smoke" and "judge_verdicts" in outputs:
        issues.append(
            _issue("JUDGE", "a smoke run is executable only: no judge, no rubric")
        )
    elif "judge_verdicts" in outputs:
        issues.extend(
            _judge_issues(
                verdicts,
                {(str(r["request_id"]), str(r["quality"])): r for r in well_formed},
            )
        )
    issues.extend(_id_issues(prereg, mode, seen))
    issues.extend(_overlap_issues(prereg, instruments))
    for key in _TARGET_KEYS:
        if key in outputs:
            issues.append(
                _issue(
                    "TARGET",
                    f"outputs carry {key!r}: 95% and 85% are fixed; "
                    "lowering them needs a new ADR",
                )
            )
    if issues:
        raise Refusal(issues)

    n = len(expected_ids(prereg, mode))
    cell1 = _cell1(prereg, well_formed, mode, era_flag=cell1_era)
    report: dict[str, Any] = {
        "status": "accepted",
        "mode": mode,
        "tag": TAG,
        "prereg_sha256": prereg_sha256,
        "flint_version": prereg.get("flint_version"),
        "fixture_commit": prereg.get("fixture_commit"),
        "n": len(expected_ids(prereg, mode)),
        "qualities": sorted({q for _, q in seen}),
        "executable": _executable(well_formed, n),
        "delivery": _delivery(well_formed),
        "cell1": cell1,
        "designed_miss_budget": _budget(len(expected_ids(prereg, mode)), cell1["era"]),
        "reference_lines": {
            "basis": REFERENCE_QUALITY,
            "executable": {"target": EXECUTABLE_TARGET},
            "rubric": {"target": RUBRIC_TARGET},
        },
    }
    if "judge_verdicts" in outputs:
        report["rubric"] = _rubric(well_formed, verdicts, n)
    if outputs.get("cost_latency_misses"):
        report["cost_latency_misses"] = [str(m) for m in outputs["cost_latency_misses"]]
    report["named_review"] = _named_review(report, outputs, mode)
    review_issues = _review_issues(report["named_review"], notes, day)
    if review_issues:
        raise Refusal(review_issues)
    enforce_allow_list(report)
    return report


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _instrument_pairs(path: Path) -> list[tuple[str, str]]:
    doc = _load_json(path)
    items = doc.get("requests", []) if isinstance(doc, dict) else doc
    return [
        (
            str(item.get("instruction", item.get("query_rewritten"))),
            str(item.get("dataset_sha256")),
        )
        for item in items
    ]


def _dataset_digests(repo: Path, prereg: Mapping[str, Any]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for item in [*(prereg.get("requests") or []), *(prereg.get("holdout_pool") or [])]:
        path = repo / str(item.get("dataset_path"))
        out[str(item["id"])] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
    return out


# --- what each run mode may write (#276) -------------------------------------
#
# Only ``publish`` writes the committed latest table and a dated snapshot.
# ``nightly`` and ``smoke`` write nothing under eval/ (a table goes to a path
# the caller names outside it, or nowhere). ``holdout`` writes only under
# eval/holdout/. The paths are fixed here, not chosen by the caller.

LATEST = ("eval/report.json", "eval/report.md", "eval/outputs.json")
RUNS_DIR = "eval/runs"
HOLDOUT_DIR = "eval/holdout"


def _under(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def _write_issues(mode: str, repo: Path, paths: Iterable[str | None]) -> list[str]:
    """Refuse a caller-chosen report path the mode may not write."""
    issues: list[str] = []
    for raw in paths:
        if not raw:
            continue
        path = Path(raw)
        if mode == "holdout":
            ok = _under(path, repo / HOLDOUT_DIR)
            rule = f"a hold-out run writes only under {HOLDOUT_DIR}/"
        else:
            ok = not _under(path, repo / "eval")
            rule = f"a {mode} run writes none of the committed files under eval/"
        if not ok:
            issues.append(_issue("WRITE", f"{raw}: {rule}"))
    return issues


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_publish(
    repo: Path, report: Mapping[str, Any], outputs_text: str, day: str
) -> None:
    js = json.dumps(report, indent=2) + "\n"
    md = render_markdown(report)
    for base in (repo / "eval", repo / RUNS_DIR / day):
        _write(base / "report.json", js)
        _write(base / "report.md", md)
        _write(base / "outputs.json", outputs_text)


def _read_notes(repo: Path) -> str | None:
    path = repo / NOTES_PATH
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _fail(issues: list[str]) -> int:
    for line in issues:
        print(line)
    print(f"FAIL: {len(issues)} check(s) failed.")
    return 1


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(
            "usage: python tools/score_eval.py <outputs.json> "
            f"--mode {{{','.join(MODES)}}} [--json report.json]",
            file=sys.stderr,
        )
        return 2
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("outputs")
    parser.add_argument("--mode", required=True, choices=MODES)
    parser.add_argument("--repo", default=str(REPO))
    parser.add_argument("--prereg", default=None)
    parser.add_argument("--json", dest="json_path", default=None)
    parser.add_argument("--md", dest="md_path", default=None)
    parser.add_argument("--cell1-era", dest="cell1_era", choices=ERAS, default="auto")
    parser.add_argument("--date", default=None)
    parser.add_argument("--instrument", action="append", default=[])
    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 2

    repo = Path(ns.repo)
    if ns.mode == "publish" and (ns.json_path or ns.md_path):
        print(
            "usage: a publish run writes fixed paths; --json/--md are not accepted",
            file=sys.stderr,
        )
        return 2
    day = ns.date or _date.today().isoformat()
    if ns.mode == "publish" and (len(day) != 10 or not day.replace("-", "").isdigit()):
        print(f"usage: --date must be YYYY-MM-DD, got {day!r}", file=sys.stderr)
        return 2
    write_issues = _write_issues(ns.mode, repo, [ns.json_path, ns.md_path])
    if write_issues:
        return _fail(write_issues)
    prereg_path = Path(ns.prereg) if ns.prereg else repo / PREREG_IN_TAG
    instruments: dict[str, list[tuple[str, str]]] = {}
    for spec in ns.instrument:
        name, sep, file = spec.partition("=")
        if not sep or not name or not file:
            print(f"usage: --instrument NAME=FILE, got {spec!r}", file=sys.stderr)
            return 2
        try:
            instruments[name] = _instrument_pairs(Path(file))
        except (OSError, ValueError, AttributeError) as exc:
            return _fail([_issue("PARSE", f"{file}: {exc}")])

    try:
        prereg_bytes = prereg_path.read_bytes()
        prereg = json.loads(prereg_bytes)
        outputs = _load_json(Path(ns.outputs))
    except (OSError, ValueError) as exc:
        return _fail([_issue("PARSE", str(exc))])

    try:
        report = score(
            prereg,
            outputs,
            mode=ns.mode,
            tag_digest=tagged_digest(repo),
            prereg_sha256=digest(prereg_bytes),
            dataset_sha256=_dataset_digests(repo, prereg),
            instruments=instruments,
            cell1_era=ns.cell1_era,
            notes=_read_notes(repo),
            day=day,
        )
    except Refusal as refusal:
        return _fail(refusal.issues)

    if ns.mode == "publish":
        _write_publish(repo, report, Path(ns.outputs).read_text(encoding="utf-8"), day)
    else:
        json_path, md_path = ns.json_path, ns.md_path
        if ns.mode == "holdout":
            json_path = json_path or str(repo / HOLDOUT_DIR / "report.json")
            md_path = md_path or str(repo / HOLDOUT_DIR / "report.md")
        if json_path:
            _write(Path(json_path), json.dumps(report, indent=2) + "\n")
        if md_path:
            _write(Path(md_path), render_markdown(report))
    print(f"OK: {ns.mode} run accepted ({report['n']} cases).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
