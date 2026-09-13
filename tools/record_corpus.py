"""Run the frozen 50 through the shipped planner into a resumable journal.

ADR-0014 D12, D13. Issue #124 (parent #122). Transport retries and per-step
call counts: issue #125. Every ask counted, and a per-attempt journal:
issue #144 (ADR-0023 Decision 8).

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

Transport, auth and rate-limit failures are not planner outcomes: ``RecordingClient``
retries them itself with backoff, at the same private seam
(``agent._client``) ``tests/test_plan_agent.py`` uses to script a model. If
its own retries exhaust, the attempt is left out of the journal entirely —
no record is written, and the run resumes it for free next time. Every
journalled attempt also carries ``step1_calls`` / ``step2_calls``, tagged by
which step's output type the call carried — **counting every ask, decoded or
not** (issue #144; a transport retry inside one ask still doesn't count
twice) — so ADR-0019 D6's per-step retry rate is observable at all. Each
record also carries ``attempts``: one row per ask, with ``step``, ``ask``,
``outcome`` (``decode | assemble | refuted | ok``), and, where applicable,
``emit``, ``rejected_emit`` and ``checker`` — installed at
``ChartAgent._attempt_observer``, the seam ``assemble`` and
refuted-unanswerable failures need since those happen inside the agent, not
at ``RecordingClient``. A series recorded before this fix counted decoded
emits, not asks, and is not comparable on those two columns
(``corpus/report-notes.md``).

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
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from chartagent import ChartAgent, ChartResult, DataSource, create_chart_agent
from chartagent.errors import (
    ChartAgentError,
    InexpressibleRequestError,
    PlannerFailureError,
    UnanswerableInstructionError,
)
from chartagent.plan.agent import Attempt
from chartagent.plan.schema import Step1Result

REPO = Path(__file__).resolve().parents[1]
TAG = "corpus-prereg-v1"
PREREG_IN_TAG = "corpus/pre-registration.json"
CORPUS_PREREG_V1_SHA256 = (
    "e4372c8d9309440f0ba1d6d58db841cfda7ffd0b2003120d11f3b7b2aae84c79"
)
RUNS_PER_REQUEST = 3
DEFAULT_JOURNAL = REPO / "build" / "corpus" / "journal.jsonl"

_TRANSPORT_RETRIES = 5
_TRANSPORT_BACKOFF_SECONDS = 1.0
# pydantic-ai's own signals for a malformed model response (ADR-0019's
# empty_response / invalid_emit). These belong to create_chart's own step
# retry budget and must never be intercepted here as a transport fault.
_EMIT_FAILURE_NAMES = frozenset(
    {"ValidationError", "ToolRetryError", "UnexpectedModelBehavior"}
)


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


def _walk_exceptions(exc: BaseException | None) -> list[BaseException]:
    """Every exception reachable from ``exc`` via cause, context, or group.

    A local copy of the walk ``plan/agent.py`` keeps private — duplicated
    rather than imported, since this tool does not reach into ``plan/``.
    """
    found: list[BaseException] = []
    seen: set[int] = set()

    def walk(current: BaseException | None) -> None:
        if current is None:
            return
        ident = id(current)
        if ident in seen:
            return
        seen.add(ident)
        found.append(current)
        if isinstance(current, BaseExceptionGroup):
            for inner in current.exceptions:
                walk(inner)
        walk(current.__cause__)
        walk(current.__context__)

    walk(exc)
    return found


def _is_transport_fault(exc: BaseException) -> bool:
    """True unless ``exc`` is one of the planner's own emit-failure signals.

    Those (ADR-0019's empty_response / invalid_emit) are ``create_chart``'s
    own retry budget to spend, never this tool's. Everything else reaching
    the client is, by ``ModelClient``'s contract, transport, auth, or a
    rate limit (ADR-0020) — never guessed at further than that.
    """
    names = {type(item).__name__ for item in _walk_exceptions(exc)}
    return not (names & _EMIT_FAILURE_NAMES)


class RecordingClient:
    """Wraps the agent's ``ModelClient``: retries transport/auth/rate-limit
    faults with backoff, and counts asks by which step's output type they
    carried. Installed at ``agent._client`` — the same private seam
    ``tests/test_plan_agent.py`` uses to script a model.

    Delegates every call to the real client and changes no planner
    behaviour: a planner emit-failure signal is never retried here, so
    ``create_chart``'s own budgets, retries, and outcomes are identical
    whether or not this proxy is installed.

    **Counts every ask, decoded or not** (issue #144). A schema decode
    failure (``ValidationError``/``ToolRetryError``/``UnexpectedModelBehavior``,
    ``_is_transport_fault``'s own vocabulary) still cost a real call to the
    model and counts once, same as a call that decodes — only a transport
    retry *within* one ask stays uncounted, because it's the same ask asked
    again. Before this fix the counter incremented only on a decoded
    return, so two decode failures at step 1 recorded ``step1_calls=0``
    instead of ``2`` (ADR-0023 Decision 8's evidence, ``r09``).
    """

    def __init__(
        self,
        client: Any,
        *,
        retries: int = _TRANSPORT_RETRIES,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._retries = retries
        self._sleep = sleep
        self.step1_calls = 0
        self.step2_calls = 0
        self.transport_retries = 0
        self.transport_exhausted = 0

    def reset_step_calls(self) -> None:
        self.step1_calls = 0
        self.step2_calls = 0

    def step_counts(self) -> dict[str, int]:
        return {"step1_calls": self.step1_calls, "step2_calls": self.step2_calls}

    def _count(self, output_type: Any) -> None:
        if output_type is Step1Result:
            self.step1_calls += 1
        else:
            self.step2_calls += 1

    def run(self, output_type: Any, system_prompt: str, user_turn: str) -> Any:
        attempt_number = 0
        while True:
            try:
                result = self._client.run(output_type, system_prompt, user_turn)
            except ChartAgentError:
                self._count(output_type)
                raise
            except Exception as exc:
                if not _is_transport_fault(exc):
                    self._count(output_type)
                    raise
                if attempt_number >= self._retries:
                    self.transport_exhausted += 1
                    raise
                attempt_number += 1
                self.transport_retries += 1
                self._sleep(_TRANSPORT_BACKOFF_SECONDS * (2 ** (attempt_number - 1)))
                continue
            self._count(output_type)
            return result


def _wrap_client(agent: ChartAgent) -> RecordingClient:
    """Install (or return the already-installed) ``RecordingClient``.

    Idempotent — a caller that already wrapped ``agent._client`` (a test
    scripting a model, or an earlier call in the same run) gets the same
    proxy back rather than a second layer of wrapping.
    """
    client = agent._client
    if isinstance(client, RecordingClient):
        return client
    proxy = RecordingClient(client)
    agent._client = proxy  # type: ignore[assignment]
    return proxy


def _attempt_row(record: Attempt) -> dict[str, Any]:
    """One ``Attempt`` as its journal shape — absent fields left out
    entirely, never written as ``null`` (issue #144)."""
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


def attempt(
    agent: ChartAgent, data: DataSource, instruction: str
) -> dict[str, Any] | None:
    """Run one ``create_chart`` call and map its outcome to a journal record.

    Never raises for any :class:`~chartagent.errors.ChartAgentError` — every
    such outcome maps to a record, tagged with ``step1_calls`` /
    ``step2_calls`` (issue #125) and ``attempts``, one row per ask
    (issue #144), installing an :class:`~chartagent.plan.agent.Attempt`
    observer at ``agent._attempt_observer`` for the duration of the call —
    the seam ``assemble`` and refuted-unanswerable failures need, since
    those happen inside the agent, never at ``RecordingClient``.

    Installs :class:`RecordingClient` at ``agent._client`` on first use.

    Returns ``None`` when the recorder's own transport retries exhaust —
    the attempt is left out of the journal so a later invocation retries it
    for free, never recorded as a planner outcome.
    """
    proxy = _wrap_client(agent)
    proxy.reset_step_calls()
    attempts: list[dict[str, Any]] = []
    agent._attempt_observer = lambda record: attempts.append(_attempt_row(record))
    try:
        result = agent.create_chart(data, instruction)
    except InexpressibleRequestError as exc:
        return {
            "rail": None,
            "escape_reason": {"bucket": exc.bucket},
            **proxy.step_counts(),
            "attempts": attempts,
        }
    except PlannerFailureError as exc:
        return {
            "rail": None,
            "miss_kind": "planner_failure",
            "reason": exc.reason,
            **proxy.step_counts(),
            "attempts": attempts,
        }
    except UnanswerableInstructionError:
        return {
            "rail": None,
            "miss_kind": "unanswerable_instruction",
            **proxy.step_counts(),
            "attempts": attempts,
        }
    except ChartAgentError as exc:
        return {
            "rail": None,
            "residual_error": {"type": type(exc).__name__, "message": str(exc)},
            **proxy.step_counts(),
            "attempts": attempts,
        }
    except Exception:
        # Not a ChartAgentError: by ModelClient's contract (ADR-0020) this is
        # transport, auth, or a rate limit, and RecordingClient already spent
        # its retries. Leave the attempt unjournalled rather than record it.
        return None
    finally:
        agent._attempt_observer = None
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
        **proxy.step_counts(),
        "attempts": attempts,
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
    is made for it. An attempt whose transport retries exhaust (``attempt``
    returns ``None``) is printed by name and left out of both the journal
    and the returned mapping — it costs nothing already paid for and is
    retried on the next invocation. Returns every record the journal now
    holds, old and new.
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
                if outcome is None:
                    print(
                        f"TRANSPORT_EXHAUSTED  {request_id} run {run}: "
                        "left unjournalled, will retry on the next invocation"
                    )
                    continue
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


def _print_transport_summary(client: RecordingClient) -> None:
    """Report the recorder's own retry spend, separately from the planner's
    (ADR-0019 D6's per-step retry rate stays a statement about the planner
    alone)."""
    if client.transport_retries == 0 and client.transport_exhausted == 0:
        print("Transport retries: none.")
        return
    print(
        f"Transport retries: {client.transport_retries} "
        f"({client.transport_exhausted} attempt(s) left unjournalled after "
        "exhausting retries)."
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
    proxy = _wrap_client(agent)
    records = run_record(agent, prereg_doc, REPO, journal_path)
    _print_residual_summary(records)
    _print_transport_summary(proxy)
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
