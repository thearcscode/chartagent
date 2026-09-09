"""The join: outputs.json, provenance manifest, and the real scorer end-to-end.

ADR-0013, ADR-0014 D13. Issue #128 (parent #122).

    python tools/join_corpus.py join --model <model> --purpose gate|plumbing

The ``join`` verb reads the record leg's journal
(``build/corpus/journal.jsonl``, ``tools/record_corpus.py``) and the paint
leg's journal (``build/corpus/paint_journal.jsonl``,
``tools/paint_corpus.py``) and writes the one file
``tools/score_corpus.py`` already knows how to read: ``corpus/outputs.json``.

``outputs.json`` carries three top-level keys: ``decoding`` (copied from
``chartagent.plan.client.PRODUCT_DECODING``, never a hand-typed copy, so
the scorer's ``DECODING`` check compares the product's settings against
themselves), ``runs`` (one merged record per journalled attempt), and
``manifest`` (provenance). It carries **no envelopes** — the scorer never
reads them, and 150 copies of inlined rows would bury the readable
evidence — so every deterministic-rail run carries ``envelope_sha256``
instead, tying a committed row back to the document that produced its
paint facts. ``tools/score_corpus.py`` is not modified by this tool and
ignores unknown top-level keys, so ``manifest`` is additive.

The manifest records what a reader needs years later: the model string; a
``purpose`` field marking a gate run apart from a plumbing run (any
provider the shipped ``ModelClient`` accepts works, so the pipeline can be
rehearsed cheaply — ``purpose`` is what makes a rehearsal impossible to
mistake for the published Wilson bound); the authoring pin
(``flint_version``, ``fixture_commit``) read from the pre-registration and
the scoring pin (``flint_version``, ``bundle_sha256``) read from
``vocab.json``, so ADR-0014 D13's *score the pin we ship* is auditable;
the pre-registration's own sha256; the renderer pins vendored for the
paint leg; the library's git commit; the run date; the recorder's own
transport-retry counts (not observable from the journal alone, since a
retry never reaches a run record — passed in by the caller, who reads
them off ``record_corpus.py``'s printed summary); and the aggregate
per-step planner call counts (summed from every journalled run's
``step1_calls`` / ``step2_calls``).

The join refuses to overwrite an existing ``corpus/outputs.json`` without
``--force``, so a stray re-run cannot silently replace a scored artefact.
It also refuses — before writing anything — if a deterministic-rail
record in the record journal has no matching paint record: a gap there is
a paint leg left unfinished, never a row this tool guesses at.

Exit 0 = ``corpus/outputs.json`` was written.
Exit 1 = a named check failed; nothing was written.
Exit 2 = usage error.

Adds nothing to ``chartagent.__all__``. ``tools/score_corpus.py`` is untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, cast

from chartagent.plan.client import PRODUCT_DECODING

REPO = Path(__file__).resolve().parents[1]
DEFAULT_JOURNAL = REPO / "build" / "corpus" / "journal.jsonl"
DEFAULT_PAINT_JOURNAL = REPO / "build" / "corpus" / "paint_journal.jsonl"
DEFAULT_OUTPUTS = REPO / "corpus" / "outputs.json"
DEFAULT_PREREG = REPO / "corpus" / "pre-registration.json"
DEFAULT_VOCAB = REPO / "src" / "chartagent" / "frame" / "vocab.json"
DEFAULT_VENDOR_PIN = REPO / "tools" / "paint" / "vendor" / "vendor.json"

PURPOSES = ("gate", "plumbing")

# A miss's diagnostic fields ride through unchanged from the record leg — the
# scorer reads them by name (tools/score_corpus.py's read_escape_reason and
# read_miss_kind) and this tool never re-derives or re-labels one.
_MISS_DIAGNOSTIC_KEYS = ("escape_reason", "miss_kind", "reason", "residual_error")


def _fail(issues: list[str]) -> int:
    for line in issues:
        print(line)
    print(f"\nFAIL — {len(issues)} check(s) failed.")
    return 1


def _canonical(data: bytes) -> bytes:
    """Hash the pre-registration as LF, the same freeze score_corpus.py uses."""
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _digest(data: bytes) -> str:
    return hashlib.sha256(_canonical(data)).hexdigest()


def envelope_sha256(envelope: Mapping[str, Any]) -> str:
    """A canonical digest of the envelope that produced a run's paint facts.

    ``outputs.json`` carries no envelopes; this is what ties a committed row
    back to the document without inlining it. Canonical: sorted keys, no
    incidental whitespace, so the digest depends only on content, never on
    how the journal line happened to serialise it.
    """
    blob = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _record_key(record: Mapping[str, Any]) -> tuple[str, int]:
    return (str(record["request_id"]), int(record["run"]))


def _read_journal(path: Path) -> dict[tuple[str, int], dict[str, Any]]:
    """Read a ``(request_id, run)``-keyed journal. Missing file reads empty —
    a journal with nothing in it is a normal state for the paint leg when
    every request in a small run happened to miss."""
    if not path.is_file():
        return {}
    records: dict[tuple[str, int], dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        records[_record_key(record)] = record
    return records


def join_runs(
    record_journal: Mapping[tuple[str, int], Mapping[str, Any]],
    paint_journal: Mapping[tuple[str, int], Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Merge the record leg's journal with the paint leg's into the run
    records ``tools/score_corpus.py`` already knows how to read.

    A ``rail: "deterministic"`` record's ``envelope`` is replaced by its
    ``envelope_sha256`` and folded together with its paint facts:
    ``emitted_compilable`` from the assembler's own accept/refuse (never
    from whether it painted), ``painted``, and ``compiled_row_count``.
    ``bound_row_count`` is read from the record leg — the envelope's own
    ``row_count`` — since the paint leg only ever carries it through
    unchanged for its own journal's readability.

    A miss (``rail: null``) carries no envelope and is passed through with
    the paint-shaped fields set to their miss defaults (``False`` /
    ``None``) and whichever of ``escape_reason``, ``miss_kind`` /
    ``reason``, or ``residual_error`` the record leg wrote — never guessed
    at, never re-labelled.

    Every deterministic-rail record must have a matching paint record. A
    gap is a paint leg left unfinished and is returned as a named issue
    rather than a row silently dropped or invented; the caller refuses to
    write anything when any issue comes back.
    """
    runs: list[dict[str, Any]] = []
    issues: list[str] = []
    for key in sorted(record_journal):
        request_id, run = key
        record = record_journal[key]
        rail = record.get("rail")
        merged: dict[str, Any] = {
            "request_id": request_id,
            "run": run,
            "rail": rail,
            "step1_calls": record.get("step1_calls"),
            "step2_calls": record.get("step2_calls"),
        }
        if rail == "deterministic":
            paint = paint_journal.get(key)
            if paint is None:
                issues.append(
                    f"PAINT_MISSING      {request_id} run {run}: no paint "
                    "record for a deterministic-rail attempt — run the "
                    "paint leg to completion before joining"
                )
                continue
            envelope = record["envelope"]
            merged.update(
                {
                    "raw_sql_used": bool(record.get("raw_sql_used")),
                    "emitted_compilable": bool(paint.get("accepted")),
                    "painted": bool(paint.get("painted")),
                    "compiled_row_count": paint.get("compiled_row_count"),
                    "bound_row_count": record.get("bound_row_count"),
                    "envelope_sha256": envelope_sha256(envelope),
                    "backend": envelope.get("backend"),
                }
            )
            if paint.get("error"):
                merged["error"] = paint["error"]
        else:
            merged.update(
                {
                    "raw_sql_used": False,
                    "emitted_compilable": False,
                    "painted": False,
                    "compiled_row_count": None,
                    "bound_row_count": None,
                }
            )
            for diag_key in _MISS_DIAGNOSTIC_KEYS:
                if diag_key in record:
                    merged[diag_key] = record[diag_key]
        runs.append(merged)
    return runs, issues


def read_renderer_pins(path: Path) -> dict[str, Any]:
    """The vendored renderer pins (ADR-0003 D5), minus the pin file's own
    ``_comment`` — the same filter ``tools/paint_corpus.py``'s preflight
    check applies, duplicated locally rather than imported so this tool
    does not reach into the paint leg's internals for one dict."""
    raw = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    return {name: record for name, record in raw.items() if not name.startswith("_")}


def library_commit(repo: Path) -> str | None:
    """The tree's own commit, so a reader years later can check out the
    state that produced the number. ``None`` if git is unavailable — a
    missing commit is disclosed, never guessed at."""
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def build_manifest(
    *,
    model: str,
    purpose: str,
    prereg: Mapping[str, Any],
    vocab: Mapping[str, Any],
    prereg_sha256: str,
    renderer_pins: Mapping[str, Any],
    commit: str | None,
    run_date: str,
    transport_retries: int,
    transport_exhausted: int,
    runs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    call_counts = {
        "step1_calls": sum(int(run.get("step1_calls") or 0) for run in runs),
        "step2_calls": sum(int(run.get("step2_calls") or 0) for run in runs),
    }
    return {
        "model": model,
        "purpose": purpose,
        "authoring_pin": {
            "flint_version": prereg.get("flint_version"),
            "fixture_commit": prereg.get("fixture_commit"),
        },
        "scoring_pin": {
            "flint_version": vocab.get("flint_version"),
            "bundle_sha256": vocab.get("bundle_sha256"),
        },
        "prereg_sha256": prereg_sha256,
        "renderer_pins": dict(renderer_pins),
        "library_commit": commit,
        "run_date": run_date,
        "transport_retries": transport_retries,
        "transport_exhausted": transport_exhausted,
        "call_counts": call_counts,
    }


def build_outputs(
    runs: list[dict[str, Any]], manifest: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "decoding": dict(PRODUCT_DECODING),
        "runs": runs,
        "manifest": dict(manifest),
    }


def _cmd_join(ns: argparse.Namespace) -> int:
    out_path = Path(ns.out)
    if out_path.exists() and not ns.force:
        return _fail(
            [
                f"OUTPUTS_EXISTS     {out_path} already exists — pass --force "
                "to overwrite a committed artefact"
            ]
        )

    prereg_path = Path(ns.prereg)
    if not prereg_path.is_file():
        return _fail([f"PARSE              {prereg_path} is missing"])
    prereg_bytes = prereg_path.read_bytes()
    prereg_sha256 = _digest(prereg_bytes)
    try:
        prereg_doc = cast(dict[str, Any], json.loads(prereg_bytes))
    except json.JSONDecodeError as exc:
        return _fail([f"PARSE              {prereg_path}: {exc}"])

    vocab_path = Path(ns.vocab)
    if not vocab_path.is_file():
        return _fail([f"PARSE              {vocab_path} is missing"])
    try:
        vocab_doc = cast(
            dict[str, Any], json.loads(vocab_path.read_text(encoding="utf-8"))
        )
    except json.JSONDecodeError as exc:
        return _fail([f"PARSE              {vocab_path}: {exc}"])

    vendor_pin_path = Path(ns.vendor_pin)
    if not vendor_pin_path.is_file():
        return _fail([f"PARSE              {vendor_pin_path} is missing"])
    try:
        renderer_pins = read_renderer_pins(vendor_pin_path)
    except json.JSONDecodeError as exc:
        return _fail([f"PARSE              {vendor_pin_path}: {exc}"])

    journal_path = Path(ns.journal)
    record_journal = _read_journal(journal_path)
    if not record_journal:
        return _fail(
            [
                f"JOURNAL            {journal_path} is missing or empty — "
                "run the record leg first (tools/record_corpus.py)"
            ]
        )
    paint_journal = _read_journal(Path(ns.paint_journal))

    runs, issues = join_runs(record_journal, paint_journal)
    if issues:
        return _fail(issues)

    manifest = build_manifest(
        model=ns.model,
        purpose=ns.purpose,
        prereg=prereg_doc,
        vocab=vocab_doc,
        prereg_sha256=prereg_sha256,
        renderer_pins=renderer_pins,
        commit=library_commit(REPO),
        run_date=ns.date or date.today().isoformat(),
        transport_retries=ns.transport_retries,
        transport_exhausted=ns.transport_exhausted,
        runs=runs,
    )
    outputs = build_outputs(runs, manifest)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(outputs, indent=2) + "\n", encoding="utf-8")
    print(f"OK — wrote {out_path} ({len(runs)} run(s) joined)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="join_corpus.py")
    sub = parser.add_subparsers(dest="verb", required=True)

    join = sub.add_parser(
        "join",
        help="Merge the record and paint journals into corpus/outputs.json.",
    )
    join.add_argument("--model", required=True, help="The model string that ran.")
    join.add_argument(
        "--purpose",
        required=True,
        choices=PURPOSES,
        help="'gate' for the published Wilson bound, 'plumbing' for a rehearsal.",
    )
    join.add_argument("--journal", default=str(DEFAULT_JOURNAL))
    join.add_argument("--paint-journal", default=str(DEFAULT_PAINT_JOURNAL))
    join.add_argument("--out", default=str(DEFAULT_OUTPUTS))
    join.add_argument("--prereg", default=str(DEFAULT_PREREG))
    join.add_argument("--vocab", default=str(DEFAULT_VOCAB))
    join.add_argument("--vendor-pin", default=str(DEFAULT_VENDOR_PIN))
    join.add_argument(
        "--transport-retries",
        type=int,
        default=0,
        help="Read off tools/record_corpus.py's printed transport summary.",
    )
    join.add_argument(
        "--transport-exhausted",
        type=int,
        default=0,
        help="Read off tools/record_corpus.py's printed transport summary.",
    )
    join.add_argument("--date", default=None)
    join.add_argument(
        "--force", action="store_true", help="Overwrite an existing --out file."
    )

    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 2

    if ns.verb == "join":
        return _cmd_join(ns)
    return 2  # pragma: no cover — argparse enforces a known verb


if __name__ == "__main__":
    raise SystemExit(main())
