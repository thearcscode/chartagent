"""Run the frozen 50 through the shipped planner into a resumable journal.

ADR-0014 D12, D13. Issue #124 (parent #122).

    python tools/record_corpus.py record --model <model>

The ``record`` verb asks the shipped planner for a chart for each of the 50
pre-registered requests, three times each, and appends one JSON object per
attempt to a journal under ``build/corpus/`` (already gitignored). Re-running
skips any ``(request_id, run)`` already in the journal and makes no model
call for it — a crash or a rate limit costs nothing already paid for.

Before it spends anything it refuses to start unless
``corpus/pre-registration.json`` hashes to the digest recorded at the
``corpus-prereg-v1`` tag, and unless every one of the 50 datasets matches its
recorded sha256 — a swapped Parquet is caught before a bill, not after it has
quietly moved a score.

Every way ``create_chart`` can end maps to one journal record: a returned
``ChartResult`` is ``rail: "deterministic"`` plus the envelope; a well-formed
verdict (``InexpressibleRequestError``, ``PlannerFailureError``,
``UnanswerableInstructionError``) is a miss with ``rail: null``; any other
``ChartAgentError`` is a residual error, also ``rail: null``, with no bucket
and no miss kind invented for it. Residual errors do not abort the run — the
remaining attempts are made regardless — and are printed as a named summary
when the run ends.

Exit 0 = the run finished (residual errors do not change this).
Exit 1 = a named pre-flight check failed; nothing was spent.
Exit 2 = usage error.

Adds nothing to chartagent.__all__. ``plan/prompts/`` is untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from chartagent import ChartAgent, ChartResult, DataSource, create_chart_agent
from chartagent.errors import (
    ChartAgentError,
    InexpressibleRequestError,
    PlannerFailureError,
    UnanswerableInstructionError,
)

REPO = Path(__file__).resolve().parents[1]
TAG = "corpus-prereg-v1"
PREREG_IN_TAG = "corpus/pre-registration.json"
CORPUS_PREREG_V1_SHA256 = (
    "e4372c8d9309440f0ba1d6d58db841cfda7ffd0b2003120d11f3b7b2aae84c79"
)
RUNS_PER_REQUEST = 3
DEFAULT_JOURNAL = REPO / "build" / "corpus" / "journal.jsonl"


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


def _load_json(path: Path) -> tuple[Any | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"PARSE              {exc}"


def check_prereg_hash(repo: Path, prereg_path: Path) -> list[str]:
    """Refuse to start unless the file hashes to the tag's recorded digest."""
    prereg_bytes = prereg_path.read_bytes() if prereg_path.is_file() else b""
    file_digest = _digest(prereg_bytes) if prereg_bytes else ""
    expected = tagged_digest(repo)
    if file_digest != expected:
        return [
            f"PREREG_HASH        {prereg_path} digest {file_digest or '(missing)'}, "
            f"want {expected} as recorded at {TAG}"
        ]
    return []


def check_datasets(repo: Path, requests: list[Mapping[str, Any]]) -> list[str]:
    """Refuse to start unless every pinned dataset matches its recorded sha256."""
    issues: list[str] = []
    for item in requests:
        request_id = item.get("id")
        dataset_path = repo / str(item["dataset_path"])
        expected = item.get("dataset_sha256")
        if not dataset_path.is_file():
            issues.append(f"DATASET            {request_id}: {dataset_path} is missing")
            continue
        actual = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
        if actual != expected:
            issues.append(
                f"DATASET            {request_id}: {dataset_path} sha256 {actual}, "
                f"want {expected}"
            )
    return issues


def _fail(issues: list[str]) -> int:
    for line in issues:
        print(line)
    print(f"\nFAIL — {len(issues)} check(s) failed.")
    return 1


def attempt(agent: ChartAgent, data: DataSource, instruction: str) -> dict[str, Any]:
    """Run one ``create_chart`` call and map its outcome to a journal record.

    Never raises for any :class:`~chartagent.errors.ChartAgentError` — every
    such outcome maps to a record. A non-``ChartAgentError`` (transport,
    auth, model-string) propagates un-wrapped; the recorder does not retry
    or reclassify it (issue #125's job).
    """
    try:
        result = agent.create_chart(data, instruction)
    except InexpressibleRequestError as exc:
        return {"rail": None, "escape_reason": {"bucket": exc.bucket}}
    except PlannerFailureError as exc:
        return {"rail": None, "miss_kind": "planner_failure", "reason": exc.reason}
    except UnanswerableInstructionError:
        return {"rail": None, "miss_kind": "unanswerable_instruction"}
    except ChartAgentError as exc:
        return {
            "rail": None,
            "residual_error": {"type": type(exc).__name__, "message": str(exc)},
        }
    assert isinstance(result, ChartResult)
    envelope = result.envelope
    x_chartagent = envelope.input.get("x_chartagent")
    transform = (
        x_chartagent.get("transform") if isinstance(x_chartagent, Mapping) else None
    )
    raw_sql_used = isinstance(transform, Mapping) and "raw_sql" in transform
    return {
        "rail": "deterministic",
        "envelope": envelope.to_dict(),
        "bound_row_count": envelope.row_count,
        "raw_sql_used": bool(raw_sql_used),
    }


def _read_journal(path: Path) -> dict[tuple[str, int], dict[str, Any]]:
    if not path.is_file():
        return {}
    records: dict[tuple[str, int], dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        records[(record["request_id"], int(record["run"]))] = record
    return records


def run_record(
    agent: ChartAgent,
    prereg: Mapping[str, Any],
    repo: Path,
    journal_path: Path,
) -> dict[tuple[str, int], dict[str, Any]]:
    """Journal three attempts per request, in pre-registration order.

    Skips any ``(request_id, run)`` already in the journal — no model call
    is made for it. Returns every record the journal now holds, old and new.
    """
    records = _read_journal(journal_path)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("a", encoding="utf-8") as handle:
        for item in prereg["requests"]:
            request_id = item["id"]
            dataset_path = repo / str(item["dataset_path"])
            instruction = item["query_rewritten"]
            for run in range(1, RUNS_PER_REQUEST + 1):
                key = (request_id, run)
                if key in records:
                    continue
                outcome = attempt(agent, str(dataset_path), instruction)
                record = {"request_id": request_id, "run": run, **outcome}
                handle.write(json.dumps(record) + "\n")
                handle.flush()
                records[key] = record
    return records


def _print_residual_summary(records: dict[tuple[str, int], dict[str, Any]]) -> None:
    residuals = [record for record in records.values() if "residual_error" in record]
    if not residuals:
        print("Residual errors: none.")
        return
    residuals.sort(key=lambda record: (record["request_id"], record["run"]))
    print(f"Residual errors: {len(residuals)}.")
    for record in residuals:
        err = record["residual_error"]
        print(
            f"  {record['request_id']} run {record['run']}: "
            f"{err['type']}: {err['message']}"
        )


def _cmd_record(ns: argparse.Namespace) -> int:
    prereg_path = Path(ns.prereg)
    journal_path = Path(ns.journal)

    hash_issues = check_prereg_hash(REPO, prereg_path)
    if hash_issues:
        return _fail(hash_issues)

    prereg_doc, err = _load_json(prereg_path)
    if err:
        return _fail([err])
    assert isinstance(prereg_doc, dict)

    requests = list(prereg_doc.get("requests") or [])
    dataset_issues = check_datasets(REPO, requests)
    if dataset_issues:
        return _fail(dataset_issues)

    agent = create_chart_agent(model=ns.model)
    records = run_record(agent, prereg_doc, REPO, journal_path)
    _print_residual_summary(records)
    print(f"OK — {len(records)} attempt(s) journalled at {journal_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="record_corpus.py")
    sub = parser.add_subparsers(dest="verb", required=True)

    record = sub.add_parser(
        "record", help="Run the frozen 50 three times each into the journal."
    )
    record.add_argument("--model", required=True)
    record.add_argument(
        "--prereg", default=str(REPO / "corpus" / "pre-registration.json")
    )
    record.add_argument("--journal", default=str(DEFAULT_JOURNAL))

    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 2

    if ns.verb == "record":
        return _cmd_record(ns)
    return 2  # pragma: no cover — argparse enforces a known verb


if __name__ == "__main__":
    raise SystemExit(main())
