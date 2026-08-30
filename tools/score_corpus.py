"""Score recorded planner outputs against the tagged pressure corpus.

ADR-0013 and ADR-0014.

Exit 0 = the report was written.
Exit 1 = a named check failed.
Exit 2 = usage error.

    python tools/score_corpus.py <outputs.json> --json <report.json> --md <report.md>

Adds nothing to chartagent.__all__. No planner is built here; the live
P1-exit run is a data change. Decoding settings are the product's.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from chartagent.errors import ChartAgentError, RawSqlRejectedError
from chartagent.frame.input import InputFrame
from chartagent.transform.engine import open_connection
from chartagent.transform.raw_sql import validate_raw_sql

REPO = Path(__file__).resolve().parents[1]
TAG = "corpus-prereg-v1"
PREREG_IN_TAG = "corpus/pre-registration.json"
CORPUS_PREREG_V1_SHA256 = (
    "e4372c8d9309440f0ba1d6d58db841cfda7ffd0b2003120d11f3b7b2aae84c79"
)
PRODUCT_DECODING: dict[str, float] = {"temperature": 0}
GATE_THRESHOLD = 0.60
WILSON_Z = 1.96
BUCKET2_SENTENCE = (
    "Bucket 2 reads zero by construction and the menu lever is fed by "
    "the raw_sql_used rate, not by the histogram."
)
POISSON_NOTE = (
    "At this frozen mixture the count is Poisson-binomial, whose SD is "
    "1.44× smaller than the binomial at the same mean, so Wilson overstates "
    "sampling uncertainty and the gate is harder to clear than costed."
)
BACKENDS = ("vegalite", "echarts", "chartjs", "plotly", "excel")


def wilson_interval(k: int, n: int, z: float = WILSON_Z) -> dict[str, float]:
    if n == 0:
        return {"lower": 0.0, "upper": 0.0}
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z2 / (4 * n)) / n) / denom
    return {"lower": centre - margin, "upper": centre + margin}


def _canonical(data: bytes) -> bytes:
    """Hash the tagged JSON as LF. A Windows CRLF checkout is the same freeze."""
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _digest(data: bytes) -> str:
    return hashlib.sha256(_canonical(data)).hexdigest()


def tagged_digest(repo: Path) -> str:
    result = subprocess.run(
        ["git", "show", f"{TAG}:{PREREG_IN_TAG}"],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    if result.returncode == 0 and result.stdout:
        return _digest(result.stdout)
    return CORPUS_PREREG_V1_SHA256


def union_chart_types(vocab: Mapping[str, Any]) -> frozenset[str]:
    backends = vocab.get("backends")
    if not isinstance(backends, Mapping):
        return frozenset()
    names: set[str] = set()
    for charts in backends.values():
        if isinstance(charts, Mapping):
            names.update(str(name) for name in charts)
    return frozenset(names)


def backend_forced(vocab: Mapping[str, Any]) -> dict[str, int]:
    backends = vocab.get("backends")
    if not isinstance(backends, Mapping):
        return {"neither_vegalite_nor_plotly": 0, "exactly_one_backend": 0}
    union = union_chart_types(vocab)
    neither = 0
    exactly_one = 0
    for chart in union:
        present = [name for name in BACKENDS if chart in (backends.get(name) or {})]
        if "vegalite" not in present and "plotly" not in present:
            neither += 1
        if len(present) == 1:
            exactly_one += 1
    return {
        "neither_vegalite_nor_plotly": neither,
        "exactly_one_backend": exactly_one,
    }


def read_escape_reason(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """Read the escape reason from any home the recorder used.

    Issue #86 / ADR-0014 D16: the scorer must not depend on where the
    value is written. ChartRecipe.escape_reason is the settled home
    (ADR-0018); the other candidates are recorded-output shims.
    """
    recipe = record.get("recipe")
    xc = record.get("x_chartagent")
    candidates = (
        record.get("escape_reason"),
        recipe.get("escape_reason") if isinstance(recipe, Mapping) else None,
        xc.get("escape") if isinstance(xc, Mapping) else None,
        record.get("reason"),
    )
    for value in candidates:
        parsed = _parse_reason(value)
        if parsed is not None:
            return parsed
    return None


def _parse_reason(value: object) -> dict[str, Any] | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value in {1, 2, 3, 4}:
        return {"bucket": value}
    if isinstance(value, Mapping):
        bucket = value.get("bucket")
        if isinstance(bucket, int) and bucket in {1, 2, 3, 4}:
            return dict(value)
    return None


def _majority(votes: list[bool]) -> bool:
    return sum(votes) >= 2


def _two_one(votes: list[bool]) -> bool:
    return sum(votes) in {1, 2}


def _rail_vote(run: Mapping[str, Any]) -> bool:
    return run.get("rail") == "deterministic"


def _raw_sql_vote(run: Mapping[str, Any]) -> bool:
    return bool(run.get("raw_sql_used"))


def _emitted_vote(run: Mapping[str, Any]) -> bool:
    return bool(run.get("emitted_compilable"))


def _delivery_vote(run: Mapping[str, Any]) -> bool:
    if not run.get("emitted_compilable"):
        return False
    compiled = run.get("compiled_row_count")
    bound = run.get("bound_row_count")
    if not isinstance(compiled, int) or not isinstance(bound, int):
        return False
    return bool(run.get("painted")) and compiled == bound


def _transform(frame: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if frame is None:
        return None
    xc = frame.get("x_chartagent")
    if not isinstance(xc, Mapping):
        return None
    transform = xc.get("transform")
    return transform if isinstance(transform, Mapping) else None


def _load_json(path: Path) -> tuple[Any | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"PARSE              {exc}"


def _share_row(k: int, n: int, *, interval: bool) -> dict[str, Any]:
    row: dict[str, Any] = {"k": k, "n": n}
    if interval:
        row["wilson_95"] = wilson_interval(k, n)
    return row


def score(
    prereg: Mapping[str, Any],
    outputs: Mapping[str, Any],
    vocab: Mapping[str, Any],
    *,
    scored_at: str,
    prereg_sha256: str,
) -> dict[str, Any]:
    requests = list(prereg["requests"])
    union = union_chart_types(vocab)
    runs_by_id: dict[str, list[dict[str, Any]]] = {}
    for raw in outputs.get("runs") or []:
        if not isinstance(raw, Mapping):
            continue
        request_id = raw.get("request_id")
        if not isinstance(request_id, str):
            continue
        runs_by_id.setdefault(request_id, []).append(dict(raw))
    for records in runs_by_id.values():
        records.sort(key=lambda item: int(item.get("run") or 0))

    connection = open_connection()
    rows: list[dict[str, Any]] = []
    cell_moves: list[dict[str, Any]] = []
    genuine_bucket2: list[str] = []
    try:
        for item in requests:
            request_id = item["id"]
            authoring_cell = int(item["cell"])
            frame = item.get("reference_frame")
            expressible_if = item.get("expressible_if") or []
            intersected = [
                name
                for name in expressible_if
                if isinstance(name, str) and name in union
            ]
            scoring_cell = authoring_cell
            if authoring_cell == 1 and intersected:
                scoring_cell = 0
                cell_moves.append(
                    {
                        "id": request_id,
                        "authoring_cell": authoring_cell,
                        "scoring_cell": scoring_cell,
                        "intersected": intersected,
                    }
                )
            expected_outcome = "miss" if frame is None else "hit"
            if scoring_cell != 1 and authoring_cell == 1 and intersected:
                expected_outcome = "hit"
            expected_bucket = item.get("expected_bucket")
            if expected_outcome == "hit":
                expected_bucket = None

            sql_refused = False
            if authoring_cell == 2:
                transform = _transform(frame if isinstance(frame, Mapping) else None)
                sql = transform.get("raw_sql") if transform is not None else None
                if isinstance(sql, str):
                    try:
                        validate_raw_sql(connection, sql)
                    except RawSqlRejectedError:
                        sql_refused = True
                        genuine_bucket2.append(request_id)

            facade_invalid = False
            if isinstance(frame, Mapping):
                try:
                    InputFrame.model_validate(frame)
                except ChartAgentError:
                    facade_invalid = True

            records = runs_by_id.get(request_id, [])
            rail_votes = [_rail_vote(run) for run in records]
            raw_sql_votes = [_raw_sql_vote(run) for run in records]
            delivery_votes = [_delivery_vote(run) for run in records]
            emitted_votes = [_emitted_vote(run) for run in records]
            rail_hit = _majority(rail_votes) if rail_votes else False
            raw_sql_used = _majority(raw_sql_votes) if raw_sql_votes else False
            delivered = _majority(delivery_votes) if delivery_votes else False
            in_delivery = _majority(emitted_votes) if emitted_votes else False

            reported_bucket: int | None = None
            if sql_refused:
                rail_hit = False
                raw_sql_used = False
                delivered = False
                in_delivery = False
                reported_bucket = 2
            elif not rail_hit:
                reasons = [read_escape_reason(run) for run in records]
                buckets = [parsed["bucket"] for parsed in reasons if parsed is not None]
                if buckets:
                    reported_bucket = Counter(buckets).most_common(1)[0][0]
            if facade_invalid and expected_outcome == "hit":
                # Narrowing bump: the tagged frame is no longer façade-valid.
                expected_outcome = "miss"
                expected_bucket = 1

            reported_outcome = "hit" if rail_hit else "miss"
            surprise_hit = (
                authoring_cell == 1
                and item.get("expected_outcome") == "miss"
                and reported_outcome == "hit"
                and not intersected
            )
            rows.append(
                {
                    "id": request_id,
                    "stratum": item["stratum"],
                    "authoring_cell": authoring_cell,
                    "scoring_cell": scoring_cell,
                    "rail_hit": rail_hit,
                    "rail_votes": rail_votes,
                    "raw_sql_used": raw_sql_used,
                    "raw_sql_votes": raw_sql_votes,
                    "delivered": delivered,
                    "delivery_votes": delivery_votes,
                    "in_delivery_denominator": in_delivery and rail_hit,
                    "expected_outcome": expected_outcome,
                    "expected_bucket": expected_bucket,
                    "reported_outcome": reported_outcome,
                    "reported_bucket": reported_bucket,
                    "surprise_hit": surprise_hit,
                    "facade_invalid": facade_invalid,
                }
            )
    finally:
        connection.close()

    n = len(rows)
    rail_k = sum(row["rail_hit"] for row in rows)
    rail_interval = wilson_interval(rail_k, n)
    gate_tripped = rail_interval["lower"] < GATE_THRESHOLD

    def _stratum(name: str) -> dict[str, Any]:
        subset = [row for row in rows if row["stratum"] == name]
        k = sum(row["rail_hit"] for row in subset)
        return _share_row(k, len(subset), interval=True)

    cells: dict[str, dict[str, int]] = {}
    for cell in range(5):
        subset = [row for row in rows if row["authoring_cell"] == cell]
        cells[str(cell)] = {
            "k": sum(row["rail_hit"] for row in subset),
            "n": len(subset),
        }

    def _raw_sql(name: str | None) -> dict[str, Any]:
        subset = [
            row
            for row in rows
            if row["rail_hit"] and (name is None or row["stratum"] == name)
        ]
        k = sum(row["raw_sql_used"] for row in subset)
        return _share_row(k, len(subset), interval=name is not None)

    delivery_subset = [row for row in rows if row["in_delivery_denominator"]]
    delivery_k = sum(row["delivered"] for row in delivery_subset)
    excluded = n - len(delivery_subset)

    histogram = Counter(
        row["reported_bucket"]
        for row in rows
        if not row["rail_hit"] and row["reported_bucket"] is not None
    )
    confusion: dict[str, dict[str, int]] = {}
    for row in rows:
        if row["rail_hit"]:
            continue
        expected = row["expected_bucket"]
        reported = row["reported_bucket"]
        if expected is None or reported is None:
            continue
        left = str(expected)
        right = str(reported)
        confusion.setdefault(left, {})
        confusion[left][right] = confusion[left].get(right, 0) + 1

    two_one = {
        "rail": sum(_two_one(row["rail_votes"]) for row in rows if row["rail_votes"]),
        "raw_sql_used": sum(
            _two_one(row["raw_sql_votes"]) for row in rows if row["raw_sql_votes"]
        ),
        "delivery": sum(
            _two_one(row["delivery_votes"]) for row in rows if row["delivery_votes"]
        ),
    }

    scoring_pin = {
        "flint_version": vocab.get("flint_version"),
        "bundle_sha256": vocab.get("bundle_sha256"),
    }
    return {
        "scored_at": scored_at,
        "tag": TAG,
        "prereg_sha256": prereg_sha256,
        "decoding": dict(PRODUCT_DECODING),
        "authoring_pin": {
            "flint_version": prereg.get("flint_version"),
            "fixture_commit": prereg.get("fixture_commit"),
        },
        "scoring_pin": scoring_pin,
        "backend_forced": backend_forced(vocab),
        "rail_share": {
            "k": rail_k,
            "n": n,
            "wilson_95": rail_interval,
            "gate_tripped": gate_tripped,
            "threshold": GATE_THRESHOLD,
        },
        "raw_sql_used": {
            "pooled": _raw_sql(None),
            "common_path": _raw_sql("common_path"),
            "adversarial": _raw_sql("adversarial"),
        },
        "delivery_rate": {
            **_share_row(delivery_k, len(delivery_subset), interval=True),
            "excluded": excluded,
        },
        "strata": {
            "common_path": _stratum("common_path"),
            "adversarial": _stratum("adversarial"),
        },
        "cells": cells,
        "two_one_counts": two_one,
        "escape_reason_histogram": {
            str(bucket): int(histogram.get(bucket, 0)) for bucket in (1, 2, 3, 4)
        },
        "cell_moves": cell_moves,
        "genuine_bucket2_ids": genuine_bucket2,
        "facade_invalid_ids": [row["id"] for row in rows if row["facade_invalid"]],
        "bucket_confusion": confusion,
        "requests": rows,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    share = report["rail_share"]
    raw = report["raw_sql_used"]
    delivery = report["delivery_rate"]
    strata = report["strata"]
    cells = report["cells"]
    hist = report["escape_reason_histogram"]
    authoring = report["authoring_pin"]
    scoring = report["scoring_pin"]
    forced = report["backend_forced"]
    lines = [
        f"# Rail-share score — {report['scored_at']}",
        "",
        f"Tag `{report['tag']}`. Pre-registration sha256 `{report['prereg_sha256']}`.",
        "",
        f"**Authoring pin:** Flint `{authoring['flint_version']}` / "
        f"fixture `{authoring['fixture_commit']}`.",
        f"**Scoring pin:** Flint `{scoring['flint_version']}` / "
        f"bundle `{scoring['bundle_sha256']}`.",
        "",
        "## Rail share (gated)",
        "",
        f"{share['k']} of {share['n']}. Wilson 95% "
        f"[{share['wilson_95']['lower']:.3f}, {share['wilson_95']['upper']:.3f}]. "
        + (
            "Gate tripped: Wilson lower bound is below 60%."
            if share["gate_tripped"]
            else "Gate clear: Wilson lower bound is at or above 60%."
        ),
        "",
        POISSON_NOTE,
        "",
        "Goal 3's ≥75% is a published target, not a gate.",
        "",
        f"Common-path stratum: {strata['common_path']['k']} of "
        f"{strata['common_path']['n']}, Wilson 95% "
        f"[{strata['common_path']['wilson_95']['lower']:.3f}, "
        f"{strata['common_path']['wilson_95']['upper']:.3f}].",
        f"Adversarial stratum: {strata['adversarial']['k']} of "
        f"{strata['adversarial']['n']}, Wilson 95% "
        f"[{strata['adversarial']['wilson_95']['lower']:.3f}, "
        f"{strata['adversarial']['wilson_95']['upper']:.3f}].",
        "",
        "Backend-forced counts (pin fact, beside the share, never inside it): "
        f"{forced['neither_vegalite_nor_plotly']} of the union on neither "
        "Vega-Lite nor Plotly; "
        f"{forced['exactly_one_backend']} on exactly one backend.",
        "",
        "## Per-cell rail counts (k of n; no rates, no intervals)",
        "",
        "Counts are against the tagged snapshot. Cell moves on the scoring "
        "pin are listed below and do not rewrite the tag.",
        "",
    ]
    for cell in range(5):
        row = cells[str(cell)]
        lines.append(f"- cell {cell}: {row['k']} of {row['n']}")
    lines.extend(
        [
            "",
            "## raw_sql_used (menu coverage)",
            "",
            f"Pooled: {raw['pooled']['k']} of {raw['pooled']['n']}.",
            f"Common-path: {raw['common_path']['k']} of {raw['common_path']['n']}, "
            f"Wilson 95% [{raw['common_path']['wilson_95']['lower']:.3f}, "
            f"{raw['common_path']['wilson_95']['upper']:.3f}].",
            f"Adversarial: {raw['adversarial']['k']} of {raw['adversarial']['n']}, "
            f"Wilson 95% [{raw['adversarial']['wilson_95']['lower']:.3f}, "
            f"{raw['adversarial']['wilson_95']['upper']:.3f}].",
            "",
            "## Delivery rate",
            "",
            f"{delivery['k']} of {delivery['n']} painted with matching row counts. "
            f"Excluded from the denominator: {delivery['excluded']}. "
            "The combined end-to-end figure is not minted.",
            "",
            "## Escape-reason histogram",
            "",
            f"Bucket 1: {hist['1']}. Bucket 2: {hist['2']}. "
            f"Bucket 3: {hist['3']}. Bucket 4: {hist['4']}.",
            "",
            BUCKET2_SENTENCE,
        ]
    )
    genuine = report.get("genuine_bucket2_ids") or []
    if genuine:
        lines.extend(
            [
                "",
                "A pre-registered cell-2 raw_sql refused at scoring appears as a "
                f"genuine bucket-2 miss ({', '.join(genuine)}).",
            ]
        )
    lines.extend(
        [
            "",
            "## Expected versus reported",
            "",
        ]
    )
    surprises = [row for row in report["requests"] if row.get("surprise_hit")]
    if surprises:
        ids = ", ".join(row["id"] for row in surprises)
        lines.append(f"Surprise hit on a cell-1 request: {ids}.")
    else:
        lines.append("No surprise hit on a cell-1 request.")
    mismatches = [
        row
        for row in report["requests"]
        if row["expected_outcome"] != row["reported_outcome"]
    ]
    lines.append("")
    if not mismatches:
        lines.append("Every request's reported outcome matches the expected outcome.")
    else:
        for row in mismatches:
            lines.append(
                f"- {row['id']}: expected {row['expected_outcome']}, "
                f"reported {row['reported_outcome']}"
            )
    invalid = report.get("facade_invalid_ids") or []
    if invalid:
        lines.extend(
            [
                "",
                "Non-null frames that failed the scoring façade: "
                + ", ".join(invalid)
                + ".",
            ]
        )
    lines.extend(["", "## Bucket confusion (among actual misses)", ""])
    confusion = report.get("bucket_confusion") or {}
    if not confusion:
        lines.append("No bucket confusion among actual misses.")
    else:
        for expected, found in sorted(confusion.items()):
            bits = [f"reported {got}: {count}" for got, count in sorted(found.items())]
            lines.append(f"- expected {expected}: {', '.join(bits)}")
    moves = report.get("cell_moves") or []
    lines.extend(["", "## Cell moves on the scoring pin", ""])
    if not moves:
        lines.append("No cell moved between the tagged snapshot and the scoring pin.")
    else:
        for move in moves:
            names = ", ".join(move["intersected"])
            lines.append(
                f"- {move['id']} moved from cell {move['authoring_cell']} to "
                f"cell {move['scoring_cell']} ({names})."
            )
    two = report["two_one_counts"]
    lines.extend(
        [
            "",
            "## Per-request 2–1 counts",
            "",
            f"Rail {two['rail']}, raw_sql_used {two['raw_sql_used']}, "
            f"delivery {two['delivery']}.",
            "",
        ]
    )
    return "\n".join(lines)


def _fail(issues: list[str]) -> int:
    for line in issues:
        print(line)
    print(f"\nFAIL — {len(issues)} check(s) failed.")
    return 1


def _check_outputs(outputs: Mapping[str, Any], request_ids: list[str]) -> list[str]:
    issues: list[str] = []
    decoding = outputs.get("decoding")
    recorded_temp = None
    if isinstance(decoding, Mapping):
        try:
            recorded_temp = float(decoding["temperature"])  # type: ignore[arg-type]
        except (KeyError, TypeError, ValueError):
            recorded_temp = None
    if recorded_temp != float(PRODUCT_DECODING["temperature"]):
        issues.append(
            f"DECODING           recorded {decoding!r}, want {PRODUCT_DECODING!r}"
        )
    runs = outputs.get("runs")
    if not isinstance(runs, list):
        issues.append("PARSE              outputs.runs must be a list")
        return issues
    counts: Counter[str] = Counter()
    for raw in runs:
        if not isinstance(raw, Mapping):
            issues.append("PARSE              a run is not an object")
            continue
        request_id = raw.get("request_id")
        if isinstance(request_id, str):
            counts[request_id] += 1
    for request_id in request_ids:
        got = counts.get(request_id, 0)
        if got != 3:
            issues.append(
                f"RUNS               {request_id}: {got} runs, want 3 "
                "(cell 1 is not skipped)"
            )
    return issues


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(
            "usage: python tools/score_corpus.py <outputs.json> "
            "--json <report.json> --md <report.md>",
            file=sys.stderr,
        )
        return 2
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("outputs")
    parser.add_argument("--json", dest="json_path", required=True)
    parser.add_argument("--md", dest="md_path", required=True)
    parser.add_argument(
        "--prereg",
        default=str(REPO / "corpus" / "pre-registration.json"),
    )
    parser.add_argument(
        "--vocab",
        default=str(REPO / "src" / "chartagent" / "frame" / "vocab.json"),
    )
    parser.add_argument("--date", default=None)
    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 2

    prereg_path = Path(ns.prereg)
    outputs_path = Path(ns.outputs)
    vocab_path = Path(ns.vocab)
    issues: list[str] = []

    prereg_bytes = prereg_path.read_bytes() if prereg_path.is_file() else b""
    file_digest = _digest(prereg_bytes) if prereg_bytes else ""
    expected = tagged_digest(REPO)
    if expected != CORPUS_PREREG_V1_SHA256:
        issues.append(
            f"HASH               tag {TAG} digest {expected}, "
            f"recorded {CORPUS_PREREG_V1_SHA256}"
        )
    if file_digest != CORPUS_PREREG_V1_SHA256:
        issues.append(
            f"HASH               {prereg_path} digest {file_digest or '(missing)'}, "
            f"want {CORPUS_PREREG_V1_SHA256} as recorded at {TAG}"
        )

    prereg_doc, prereg_err = _load_json(prereg_path)
    outputs_doc, outputs_err = _load_json(outputs_path)
    vocab_doc, vocab_err = _load_json(vocab_path)
    for err in (prereg_err, outputs_err, vocab_err):
        if err:
            issues.append(err)
    if issues:
        return _fail(issues)
    assert isinstance(prereg_doc, dict)
    assert isinstance(outputs_doc, dict)
    assert isinstance(vocab_doc, dict)
    request_ids = [
        item["id"] for item in prereg_doc.get("requests") or [] if "id" in item
    ]
    issues.extend(_check_outputs(outputs_doc, request_ids))
    if issues:
        return _fail(issues)

    scored_at = ns.date or date.today().isoformat()
    report = score(
        prereg_doc,
        outputs_doc,
        vocab_doc,
        scored_at=scored_at,
        prereg_sha256=file_digest,
    )
    json_path = Path(ns.json_path)
    md_path = Path(ns.md_path)
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"OK — wrote {json_path} and {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
