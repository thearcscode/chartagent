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
    print(f"OK: {ns.mode} run accepted ({report['n']} cases).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
