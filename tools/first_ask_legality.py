"""First-ask legality: the measurement runner and the untyped-planner baseline.

ADR-0023 Decision 8. Issue #146 (parent #16) — consumes #145's committed
fixture and instruction set, and journals through #144's attempt seam.

    python tools/first_ask_legality.py run --model anthropic:claude-sonnet-4-6
    python tools/first_ask_legality.py report --model anthropic:claude-sonnet-4-6

The ``run`` verb asks the shipped planner for a chart against #145's
instruction set (``tests/data/first_ask/instructions.json``), three times
per instruction, at ``chartagent.plan.client.PRODUCT_DECODING``'s
temperature 0 (never overridden here), and appends one JSON object per
``(id, run)`` to a resumable journal under ``build/first_ask/`` (gitignored,
matching ``tools/record_corpus.py``'s convention). Re-running skips any
``(id, run)`` already in the journal and makes no model call for it.

Every ask is journalled through ``ChartAgent._attempt_observer``
(``chartagent.plan.agent.Attempt``, issue #144): ``step``, ``ask``,
``outcome`` (``decode | assemble | refuted | ok``), and, where applicable,
``emit``, ``rejected_emit``, ``checker``. Unlike ``tools/record_corpus.py``,
this tool does not retry transport/auth/rate-limit faults itself — a
25-instruction x 3-run measurement is cheap enough that a crash simply
re-runs (the journal is still resumable per-attempt).

**First-ask legality** reads only each run's *first* step-1 attempt
(``attempts[0]``, always step 1 ask 1 — step 1 runs before step 2 on every
call) and never anything a repair produced. It is published twice:
verdicts included (any legal ``ok`` — fragment, inexpressible, or
unanswerable — over instructions x 3 runs) and verdicts excluded (a
well-formed ``inexpressible``/``unanswerable`` first ask is dropped from
*both* the numerator and the denominator, leaving ``emit: fragment`` as the
only numerator, over the runs that were not a verdict). Beside it, never
folded in: the first attempt's outcome breakdown, and repair success — of
the runs whose first step-1 attempt missed, the share whose next step-1
attempt (the one retry ADR-0019 budgets there) reached ``ok``.

``corpus/`` — the frozen 50, ``corpus-prereg-v1`` — is never read, adapted,
or re-scored by this tool. #145's fixture and instruction set are their own
from-scratch series (ADR-0023 Decision 8).

Exit 0 = the run finished / the report was written.
Exit 1 = a named pre-flight check failed; nothing was spent or written.
Exit 2 = usage error.

Adds nothing to ``chartagent.__all__``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

from chartagent import ChartAgent, create_chart_agent
from chartagent.errors import (
    ChartAgentError,
    InexpressibleRequestError,
    PlannerFailureError,
    UnanswerableInstructionError,
)
from chartagent.plan.agent import Attempt

REPO = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO / "tests" / "data"
DEFAULT_INSTRUCTIONS = FIXTURES_DIR / "first_ask" / "instructions.json"
DEFAULT_JOURNAL = REPO / "build" / "first_ask" / "journal.jsonl"
DEFAULT_REPORT = REPO / "docs" / "research" / "first-ask-legality.md"
DEFAULT_VOCAB = REPO / "src" / "chartagent" / "frame" / "vocab.json"
# The paths #145 committed — the fixture-commit manifest field is the most
# recent commit that touched either.
_FIXTURE_PATHS = (
    "tests/data/first_ask/instructions.json",
    "tests/data/orders_dated.csv",
)

RUNS_PER_INSTRUCTION = 3
# The P1-exit recording's model string (ADR-0023 Decision 8).
MODEL = "anthropic:claude-sonnet-4-6"

_VERDICT_EMITS = frozenset({"inexpressible", "unanswerable"})
_OUTCOMES = ("decode", "assemble", "refuted", "ok")


# ---------------------------------------------------------------------------
# Running the measurement
# ---------------------------------------------------------------------------


def _attempt_row(record: Attempt) -> dict[str, Any]:
    """One ``Attempt`` as its journal shape — absent fields left out
    entirely, never written as ``null`` (matches ``tools/record_corpus.py``,
    issue #144)."""
    row: dict[str, Any] = {
        "step": record.step,
        "ask": record.ask,
        "outcome": record.outcome,
    }
    if record.emit is not None:
        row["emit"] = record.emit
    if record.rejected_emit is not None:
        row["rejected_emit"] = record.rejected_emit
    if record.checker is not None:
        row["checker"] = record.checker
    return row


def attempt(agent: ChartAgent, data: Any, instruction: str) -> dict[str, Any]:
    """Run one ``create_chart`` call and return its attempt journal.

    Never raises for any :class:`~chartagent.errors.ChartAgentError` — every
    such outcome (a rail hit, a well-formed verdict, a planner failure)
    still produced attempts, and the first-ask measurement reads only
    ``attempts[0]``, which exists regardless of how the call ended.
    Installs an :class:`~chartagent.plan.agent.Attempt` observer at
    ``agent._attempt_observer`` for the duration of the call, the seam
    ``assemble`` and refuted-unanswerable failures need since those happen
    inside the agent, never at the model client.

    A transport/auth/rate-limit fault (not a ``ChartAgentError``)
    propagates: unlike the frozen-50 recorder, this tool does not retry
    those itself.

    Records ``model`` as ``agent._model`` — the string that actually
    produced these attempts, not whatever ``--model`` a later ``report``
    invocation happens to be called with. The report's manifest reads the
    model back off the journal rather than accepting it as an independent
    flag, so the two can never disagree.
    """
    attempts: list[dict[str, Any]] = []
    agent._attempt_observer = lambda record: attempts.append(_attempt_row(record))
    try:
        agent.create_chart(data, instruction, quality="fast")
    except InexpressibleRequestError as exc:
        outcome: dict[str, Any] = {
            "rail": None,
            "escape_reason": {"bucket": exc.bucket},
        }
    except PlannerFailureError as exc:
        outcome = {"rail": None, "miss_kind": "planner_failure", "reason": exc.reason}
    except UnanswerableInstructionError:
        outcome = {"rail": None, "miss_kind": "unanswerable_instruction"}
    except ChartAgentError as exc:
        outcome = {
            "rail": None,
            "residual_error": {"type": type(exc).__name__, "message": str(exc)},
        }
    else:
        outcome = {"rail": "deterministic"}
    finally:
        agent._attempt_observer = None
    return {"model": agent._model, **outcome, "attempts": attempts}


def _load_instructions(path: Path) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", json.loads(path.read_text(encoding="utf-8")))


def _read_journal(path: Path) -> dict[tuple[str, int], dict[str, Any]]:
    if not path.is_file():
        return {}
    records: dict[tuple[str, int], dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        records[(record["id"], int(record["run"]))] = record
    return records


def run_measurement(
    agent: ChartAgent,
    instructions: Sequence[Mapping[str, Any]],
    fixtures_dir: Path,
    journal_path: Path,
    *,
    runs_per_instruction: int = RUNS_PER_INSTRUCTION,
) -> dict[tuple[str, int], dict[str, Any]]:
    """Journal ``runs_per_instruction`` attempts per instruction, in the
    instruction set's own order. Skips any ``(id, run)`` already in the
    journal — no model call is made for it. Returns every record the
    journal now holds, old and new."""
    records = _read_journal(journal_path)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("a", encoding="utf-8") as handle:
        for item in instructions:
            instruction_id = item["id"]
            fixture_path = fixtures_dir / item["fixture"]
            for run in range(1, runs_per_instruction + 1):
                key = (instruction_id, run)
                if key in records:
                    continue
                outcome = attempt(agent, str(fixture_path), item["instruction"])
                record = {"id": instruction_id, "run": run, **outcome}
                handle.write(json.dumps(record) + "\n")
                handle.flush()
                records[key] = record
    return records


# ---------------------------------------------------------------------------
# The rate: first step-1 attempt only
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FirstAskRates:
    """First-ask legality, both views, plus what stays beside it and never
    folds in (ADR-0023 Decision 8)."""

    included_ok: int
    included_total: int
    excluded_ok: int
    excluded_total: int
    breakdown: dict[str, int]
    repair_eligible: int
    repair_succeeded: int

    @property
    def included_rate(self) -> float | None:
        return self.included_ok / self.included_total if self.included_total else None

    @property
    def excluded_rate(self) -> float | None:
        return self.excluded_ok / self.excluded_total if self.excluded_total else None

    @property
    def repair_rate(self) -> float | None:
        return (
            self.repair_succeeded / self.repair_eligible
            if self.repair_eligible
            else None
        )


def _first_step1_attempt(attempts: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    for record in attempts:
        if record["step"] == 1:
            return record
    raise ValueError("a run's attempts carry no step-1 attempt")


def _repair_reached_ok(attempts: Sequence[Mapping[str, Any]]) -> bool:
    """True if any step-1 attempt *after* the first reached ``ok`` — the one
    retry ADR-0019 budgets at step 1, i.e. a repair succeeded."""
    step1 = [record for record in attempts if record["step"] == 1]
    return any(record["outcome"] == "ok" for record in step1[1:])


def compute_first_ask_rates(runs: Sequence[Mapping[str, Any]]) -> FirstAskRates:
    """First-ask legality from each run's first step-1 attempt only.

    ``runs`` are journal records (or any mapping carrying an ``attempts``
    list shaped like #144's per-attempt journal). A repaired run's first
    attempt is whatever it was before the repair — repair success is
    counted separately and never folds into either rate.
    """
    first_attempts = [_first_step1_attempt(run["attempts"]) for run in runs]
    breakdown = dict(Counter(record["outcome"] for record in first_attempts))
    included_ok = sum(1 for record in first_attempts if record["outcome"] == "ok")
    verdicts = sum(
        1
        for record in first_attempts
        if record["outcome"] == "ok" and record.get("emit") in _VERDICT_EMITS
    )
    fragment_ok = sum(
        1
        for record in first_attempts
        if record["outcome"] == "ok" and record.get("emit") == "fragment"
    )
    repair_eligible_runs = [
        run for run, record in zip(runs, first_attempts) if record["outcome"] != "ok"
    ]
    repair_succeeded = sum(
        1 for run in repair_eligible_runs if _repair_reached_ok(run["attempts"])
    )
    return FirstAskRates(
        included_ok=included_ok,
        included_total=len(runs),
        excluded_ok=fragment_ok,
        excluded_total=len(runs) - verdicts,
        breakdown=breakdown,
        repair_eligible=len(repair_eligible_runs),
        repair_succeeded=repair_succeeded,
    )


# ---------------------------------------------------------------------------
# The manifest and the report
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def fixture_commit(repo: Path) -> str | None:
    """The most recent commit touching #145's fixture or instruction set —
    ``None`` if git is unavailable, never guessed at."""
    return _git(repo, "log", "-1", "--format=%H", "--", *_FIXTURE_PATHS)


def library_commit(repo: Path) -> str | None:
    """The tree's own commit, so a reader years later can check out the
    state that produced the number."""
    return _git(repo, "rev-parse", "HEAD")


class MixedModelJournalError(ValueError):
    """The journal's runs were not all produced by the same model string."""

    def __init__(self, models: set[str]) -> None:
        super().__init__(
            f"journal carries more than one model string: {sorted(models)} — "
            "report against a journal produced by a single `run` model"
        )
        self.models = models


def journal_model(runs: Sequence[Mapping[str, Any]]) -> str:
    """The one model string that produced every run — read off the journal
    itself (each record's ``model``, written by :func:`attempt`) rather than
    accepted as an independent ``report`` flag, so the manifest can never
    name a model that didn't actually produce the data."""
    models = {str(run["model"]) for run in runs}
    if len(models) != 1:
        raise MixedModelJournalError(models)
    return next(iter(models))


def read_flint_pin(vocab_path: Path) -> dict[str, Any]:
    vocab = cast("dict[str, Any]", json.loads(vocab_path.read_text(encoding="utf-8")))
    return {
        "flint_version": vocab.get("flint_version"),
        "bundle_sha256": vocab.get("bundle_sha256"),
    }


def build_manifest(
    *, model: str, repo: Path, vocab_path: Path, run_date: str
) -> dict[str, Any]:
    return {
        "fixture_commit": fixture_commit(repo),
        "library_commit": library_commit(repo),
        "model": model,
        "flint_pin": read_flint_pin(vocab_path),
        "run_date": run_date,
    }


def _pct(rate: float | None) -> str:
    return f"{rate:.1%}" if rate is not None else "n/a"


def render_report(rates: FirstAskRates, manifest: Mapping[str, Any]) -> str:
    flint_pin = manifest["flint_pin"]
    breakdown_line = ", ".join(
        f"`{name}` {rates.breakdown.get(name, 0)}" for name in _OUTCOMES
    )
    lines = [
        f"# First-ask legality — {manifest['run_date']}",
        "",
        "Untyped planner — after ADR-0023 Decision 4's item-key fix (#143) and "
        "#144's per-ask journal, before the typed menu (#147). Fixture and "
        f"instruction set (#145) at commit `{manifest['fixture_commit']}`. "
        f"Library commit `{manifest['library_commit']}`. Model "
        f"`{manifest['model']}`, temperature 0. Flint "
        f"`{flint_pin['flint_version']}` / bundle `{flint_pin['bundle_sha256']}`.",
        "",
        "There is no gate (ADR-0023 Decision 8). This is the *before* half of "
        "the after-measurement #147 will run on the same committed set.",
        "",
        "## First-ask legality",
        "",
        f"Verdicts included: {rates.included_ok} of {rates.included_total} "
        f"({_pct(rates.included_rate)}).",
        "",
        f"Verdicts excluded: {rates.excluded_ok} of {rates.excluded_total} "
        f"({_pct(rates.excluded_rate)}).",
        "",
        "## First step-1 attempt outcome breakdown",
        "",
        f"{breakdown_line}.",
        "",
        "## Repair success",
        "",
        f"Of the runs whose first step-1 attempt missed, "
        f"{rates.repair_succeeded} of {rates.repair_eligible} "
        f"({_pct(rates.repair_rate)}) reached `ok` on the extra ask.",
        "",
        "## Manifest",
        "",
        f"- Fixture/instruction commit (#145): `{manifest['fixture_commit']}`",
        f"- Library commit: `{manifest['library_commit']}`",
        f"- Model: `{manifest['model']}`",
        f"- Flint pin: `{flint_pin['flint_version']}` / `{flint_pin['bundle_sha256']}`",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _fail(issues: list[str]) -> int:
    for line in issues:
        print(line)
    print(f"\nFAIL — {len(issues)} check(s) failed.")
    return 1


def _cmd_run(ns: argparse.Namespace) -> int:
    instructions_path = Path(ns.instructions)
    if not instructions_path.is_file():
        return _fail([f"INSTRUCTIONS       {instructions_path} is missing"])
    instructions = _load_instructions(instructions_path)

    fixtures_dir = Path(ns.fixtures_dir)
    missing = [
        item["id"]
        for item in instructions
        if not (fixtures_dir / item["fixture"]).is_file()
    ]
    if missing:
        return _fail(
            [f"FIXTURE            missing fixture file(s) for: {', '.join(missing)}"]
        )

    agent = create_chart_agent(model=ns.model)
    records = run_measurement(agent, instructions, fixtures_dir, Path(ns.journal))
    print(f"OK — {len(records)} run(s) journalled at {ns.journal}")
    return 0


def _cmd_report(ns: argparse.Namespace) -> int:
    journal_path = Path(ns.journal)
    records = _read_journal(journal_path)
    if not records:
        return _fail(
            [
                f"JOURNAL            {journal_path} is missing or empty — "
                "run the measurement first (`first_ask_legality.py run`)"
            ]
        )
    run_list = list(records.values())

    try:
        model = journal_model(run_list)
    except MixedModelJournalError as exc:
        return _fail([f"MIXED_MODEL        {exc}"])

    rates = compute_first_ask_rates(run_list)
    manifest = build_manifest(
        model=model,
        repo=REPO,
        vocab_path=Path(ns.vocab),
        run_date=ns.date or date.today().isoformat(),
    )
    report = render_report(rates, manifest)
    out_path = Path(ns.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"OK — wrote {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(prog="first_ask_legality.py")
    sub = parser.add_subparsers(dest="verb", required=True)

    run = sub.add_parser(
        "run", help="Journal three attempts per instruction in #145's set."
    )
    run.add_argument(
        "--model",
        required=True,
        help="e.g. anthropic:claude-sonnet-4-6 — the P1-exit recording's "
        f"string ({MODEL}). Required: this makes a billed call per attempt "
        "and the string is journalled as provenance, never defaulted.",
    )
    run.add_argument("--instructions", default=str(DEFAULT_INSTRUCTIONS))
    run.add_argument("--fixtures-dir", default=str(FIXTURES_DIR))
    run.add_argument("--journal", default=str(DEFAULT_JOURNAL))

    report = sub.add_parser(
        "report",
        help="Compute both rates and write docs/research/first-ask-legality.md.",
    )
    report.add_argument("--journal", default=str(DEFAULT_JOURNAL))
    report.add_argument("--vocab", default=str(DEFAULT_VOCAB))
    report.add_argument("--out", default=str(DEFAULT_REPORT))
    report.add_argument("--date", default=None)

    try:
        ns = parser.parse_args(args)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 2

    if ns.verb == "run":
        return _cmd_run(ns)
    if ns.verb == "report":
        return _cmd_report(ns)
    return 2  # pragma: no cover — argparse enforces a known verb


if __name__ == "__main__":
    raise SystemExit(main())
