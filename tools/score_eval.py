"""The eval gate on the frozen 150 (ADR-0029, spec #271).

Reads the frozen ``eval/pre-registration.json`` and one run's harness records,
then either accepts the run or refuses with a named reason. This slice (#280)
scores nothing: it proves the gate cannot be fooled about *which* set it is
scoring. Later slices extend ``score`` with the published figures.

Exit codes: 0 report written, 1 named check failed, 2 usage error.

    python tools/score_eval.py <outputs.json> --mode nightly --json <r.json>
        [--repo DIR] [--prereg FILE] [--instrument NAME=FILE ...]

Files:
  * pre-registration: ``requests`` (the public 150; each ``id``, ``instruction``,
    ``dataset_path``, ``dataset_sha256``), ``holdout_pool`` (same shape),
    ``holdout_permutation``, ``smoke_ids``, ``human_calibration_permutation``.
  * outputs.json: ``{"records": [{"request_id", "quality", ...}]}``, one record
    per (case, quality). Harness records only, never PNG bytes.
  * ``--instrument``: another instrument's requests, a JSON list or an object
    with ``requests``; each entry carries ``instruction`` (or
    ``query_rewritten``) and ``dataset_sha256``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
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
        return [str(i) for i in prereg.get("holdout_permutation") or []][
            :HOLDOUT_SIZE
        ]
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
            "interval_spans_target": interval["lower"]
            <= EXECUTABLE_TARGET
            <= interval["upper"],
            "misses": sorted(misses[quality]),
        }
    return {"target": EXECUTABLE_TARGET, "by_quality": by_quality}


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
        if row["interval_spans_target"]:
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
    return "\n".join(lines) + "\n"


def score(
    prereg: Mapping[str, Any],
    outputs: Mapping[str, Any],
    *,
    mode: str,
    tag_digest: str | None,
    prereg_sha256: str,
    dataset_sha256: Mapping[str, str | None],
    instruments: Mapping[str, Iterable[tuple[str, str]]],
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
            issues.append(_issue("PARSE", f"record lacks request_id/quality: {record!r}"))
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
    issues.extend(_id_issues(prereg, mode, seen))
    issues.extend(_overlap_issues(prereg, instruments))
    if issues:
        raise Refusal(issues)

    return {
        "status": "accepted",
        "mode": mode,
        "tag": TAG,
        "prereg_sha256": prereg_sha256,
        "flint_version": prereg.get("flint_version"),
        "fixture_commit": prereg.get("fixture_commit"),
        "n": len(expected_ids(prereg, mode)),
        "qualities": sorted({q for _, q in seen}),
        "executable": _executable(well_formed, len(expected_ids(prereg, mode))),
    }


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


def _dataset_digests(
    repo: Path, prereg: Mapping[str, Any]
) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for item in [*(prereg.get("requests") or []), *(prereg.get("holdout_pool") or [])]:
        path = repo / str(item.get("dataset_path"))
        out[str(item["id"])] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
    return out


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
    parser.add_argument("--instrument", action="append", default=[])
    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 2

    repo = Path(ns.repo)
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
        )
    except Refusal as refusal:
        return _fail(refusal.issues)

    if ns.json_path:
        Path(ns.json_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if ns.md_path:
        Path(ns.md_path).write_text(render_markdown(report), encoding="utf-8")
    print(f"OK: {ns.mode} run accepted ({report['n']} cases).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
