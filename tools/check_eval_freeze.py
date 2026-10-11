"""Validate the eval benchmark freeze (ADR-0029, spec #282).

Exit 0 = the file is a legal freeze.
Exit 1 = a named check failed.
Exit 2 = usage error.

    python tools/check_eval_freeze.py <eval/pre-registration.json>
        [--repo DIR] [--instrument NAME=FILE ...]

``--repo`` (default: this checkout) is where ``dataset_path`` values resolve and
where the default instruments live. Three other instruments must stay disjoint
from the freeze on ``(instruction, dataset sha256)``:

  * ``corpus-prereg-v1``  default ``<repo>/corpus/pre-registration.json``
    (requests and reserves); the bytes under ``corpus/data/`` must also not be
    reused by any freeze dataset.
  * ``first-ask``         default ``<repo>/tests/data/first_ask/instructions.json``
  * ``injection-suite``   no default; pass ``--instrument injection-suite=FILE``.

``--instrument NAME=FILE`` overrides or supplies one of those. A file is a JSON
list, or an object with ``requests`` (and optionally ``reserves``). Each entry
carries ``instruction`` (or ``query_rewritten``) and ``dataset_sha256`` (or a
``fixture`` file name, resolved next to the instrument file and hashed here).

Adds nothing to chartagent.__all__. The tagged freeze is not this tool's to
author.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from chartagent.transform.engine import open_connection

REPO = Path(__file__).resolve().parents[1]

PUBLIC_MATRIX = {
    "common_path": (90, 0, 12, 2, 16),
    "adversarial": (0, 4, 8, 0, 18),
}
STRATUM_SIZE = {"common_path": 120, "adversarial": 30}
SHAPES = {
    "common_path": {"long": 48, "wide": 48, "nested": 12, "wide_sparse": 12},
    "adversarial": {"long": 6, "wide": 9, "nested": 6, "wide_sparse": 9},
}
COMMON_INTENT_COUNTS = {
    "trend over time": 28,
    "comparison across categories": 36,
    "distribution of one measure": 4,
    "correlation between measures": 8,
    "part-to-whole": 24,
    "ranking / top-N": 8,
    "flow or transition between states": 4,
    "geographic distribution": 4,
    "single value against a target": 4,
}
# cell-4 family -> (common_path, adversarial)
CELL4_TABLE = {"i": (0, 8), "ii": (10, 2), "iii": (4, 4), "iv": (2, 4)}
CELL3_FAMILIES = frozenset({"silent_row_drop", "discrete_overflow"})
SMOKE_SIZE = 30
SMOKE_CELLS = (18, 1, 4, 1, 6)
HOLDOUT_SIZE = 30
HOLDOUT_MIX = {
    "common_path": (15, 0, 3, 1, 5),
    "adversarial": (0, 1, 2, 0, 3),
}
INSTRUMENTS = ("corpus-prereg-v1", "first-ask", "injection-suite")
EXCEL_RE = re.compile(r"\b(excel|xlsx?|xlsm)\b", re.IGNORECASE)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DATA_PREFIX = "eval/data/"

Stratum = Literal["common_path", "adversarial"]
Shape = Literal["long", "wide", "nested", "wide_sparse"]
Source = Literal["nvbench1", "authored"]
Cell = Literal[0, 1, 2, 3, 4]
Outcome = Literal["hit", "miss"]


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    instruction: str
    source: Source
    source_id: str
    query_original: str
    query_rewritten: str
    stratum: Stratum
    cell: Cell
    cell_family: str | None = None
    intent: str
    shape: Shape
    dataset_path: str
    dataset_sha256: str
    reference_frame: dict[str, Any] | None
    expressible_if: list[str] | None = None
    ambiguity_degree: int | None = None
    expected_outcome: Outcome
    expected_bucket: int | None = None

    @field_validator(
        "id",
        "instruction",
        "source_id",
        "query_original",
        "query_rewritten",
        "dataset_path",
    )
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be non-empty")
        return value

    @field_validator("dataset_sha256")
    @classmethod
    def _sha256(cls, value: str) -> str:
        if SHA256_RE.fullmatch(value) is None:
            raise ValueError("must be a lowercase sha256 hex digest")
        return value


class Freeze(BaseModel):
    # Self-describing summary fields (matrix, shape splits, ...) are allowed
    # and ignored; the checks below recompute them from the records.
    model_config = ConfigDict(extra="allow")
    flint_version: str
    fixture_commit: str
    requests: list[Request]
    holdout_pool: list[Request]
    holdout_permutation: list[str]
    smoke_ids: list[str]
    human_calibration_permutation: list[str]

    @field_validator("flint_version", "fixture_commit")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be non-empty")
        return value


def _sibling() -> ModuleType:
    """The corpus validator, reused for per-request frame/intent/expected checks."""
    spec = importlib.util.spec_from_file_location(
        "_check_prereg_sibling", Path(__file__).with_name("check_prereg.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pairs(path: Path) -> list[tuple[str, str]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(doc, dict):
        items = [*doc.get("requests", []), *doc.get("reserves", [])]
    else:
        items = doc
    out: list[tuple[str, str]] = []
    for item in items:
        text = item.get("instruction", item.get("query_rewritten"))
        sha = item.get("dataset_sha256")
        if sha is None and item.get("fixture"):
            fixture = path.parent / str(item["fixture"])
            sha = _sha_file(fixture) if fixture.is_file() else None
        out.append((str(text), str(sha)))
    return out


def validate(
    path: Path, repo: Path = REPO, instruments: dict[str, Path] | None = None
) -> list[str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"PARSE              {exc}"]
    if not isinstance(raw, dict):
        return ["SCHEMA             top level must be an object"]
    try:
        doc = Freeze.model_validate(raw)
    except ValidationError as exc:
        return [
            f"SCHEMA             {err['loc']}: {err['msg']}" for err in exc.errors()
        ]
    files = {
        "corpus-prereg-v1": repo / "corpus" / "pre-registration.json",
        "first-ask": repo / "tests" / "data" / "first_ask" / "instructions.json",
        **(instruments or {}),
    }
    return _check(doc, repo, files)


def _check(doc: Freeze, repo: Path, files: dict[str, Path]) -> list[str]:
    issues: list[str] = []
    issues.extend(_check_ids(doc))
    issues.extend(_check_matrix(doc.requests))
    issues.extend(_check_shapes(doc.requests))
    issues.extend(_check_intents(doc.requests))
    issues.extend(_check_cell1(doc.requests))
    issues.extend(_check_cell34(doc.requests))
    issues.extend(_check_smoke(doc))
    issues.extend(_check_holdout(doc))
    issues.extend(_check_permutations(doc))
    issues.extend(_check_datasets(doc, repo))
    issues.extend(_check_excel(doc))
    issues.extend(_check_disjoint(doc, repo, files))
    issues.extend(_check_requests(doc))
    return issues


def _everyone(doc: Freeze) -> list[Request]:
    return [*doc.requests, *doc.holdout_pool]


def _check_ids(doc: Freeze) -> list[str]:
    issues: list[str] = []
    for label, items in (("request", doc.requests), ("holdout", doc.holdout_pool)):
        counts = Counter(item.id for item in items)
        dupes = sorted(i for i, n in counts.items() if n > 1)
        if dupes:
            issues.append(f"IDS                duplicate {label} ids: {dupes}")
    shared = sorted({i.id for i in doc.requests} & {i.id for i in doc.holdout_pool})
    if shared:
        issues.append(f"IDS                ids shared with hold-out pool: {shared}")
    return issues


def _matrix(items: Iterable[Request], stratum: str) -> tuple[int, ...]:
    counts = [0, 0, 0, 0, 0]
    for item in items:
        if item.stratum == stratum:
            counts[item.cell] += 1
    return tuple(counts)


def _check_matrix(requests: list[Request]) -> list[str]:
    issues: list[str] = []
    if len(requests) != 150:
        issues.append(f"MATRIX             n={len(requests)}, want 150")
    for stratum, want in PUBLIC_MATRIX.items():
        got = _matrix(requests, stratum)
        if got != want:
            issues.append(
                f"MATRIX             {stratum} {list(got)}, want {list(want)}"
            )
        size = sum(1 for item in requests if item.stratum == stratum)
        if size != STRATUM_SIZE[stratum]:
            issues.append(
                f"MATRIX             {stratum} n={size}, want {STRATUM_SIZE[stratum]}"
            )
    return issues


def _check_shapes(requests: list[Request]) -> list[str]:
    issues: list[str] = []
    for stratum, want in SHAPES.items():
        got = dict(Counter(i.shape for i in requests if i.stratum == stratum))
        if got != want:
            issues.append(f"SHAPE              {stratum} {got}, want {want}")
    for item in requests:
        if item.cell != 2:
            continue
        legal = (
            {"wide", "wide_sparse"}
            if item.stratum == "common_path"
            else {"wide", "wide_sparse", "nested"}
        )
        if item.shape not in legal:
            issues.append(
                f"SHAPE              {item.id}: cell-2 {item.stratum} shape "
                f"{item.shape!r} not in {sorted(legal)}"
            )
    return issues


def _check_intents(requests: list[Request]) -> list[str]:
    got = dict(Counter(i.intent for i in requests if i.stratum == "common_path"))
    if got != COMMON_INTENT_COUNTS:
        return [f"INTENTS            common_path {got}, want {COMMON_INTENT_COUNTS}"]
    return []


def _check_cell1(requests: list[Request]) -> list[str]:
    sib = _sibling()
    issues: list[str] = []
    cell1 = [i for i in requests if i.cell == 1]
    if any(i.stratum != "adversarial" for i in cell1):
        issues.append("CELL1              cell-1 case on the common path")
    got = {i.intent for i in cell1}
    if got != set(sib.CELL1_INTENTS):
        issues.append(
            f"CELL1              intents {sorted(got)}, want all of "
            f"{sorted(sib.CELL1_INTENTS)}"
        )
    return issues


def _check_cell34(requests: list[Request]) -> list[str]:
    issues: list[str] = []
    for item in requests:
        if item.cell == 3:
            if item.stratum != "common_path":
                issues.append(f"CELL3              {item.id}: row-drop not common path")
            if item.cell_family not in CELL3_FAMILIES:
                issues.append(
                    f"CELL3              {item.id}: cell_family "
                    f"{item.cell_family!r} not in {sorted(CELL3_FAMILIES)}"
                )
        if item.cell == 4 and item.cell_family not in CELL4_TABLE:
            issues.append(
                f"CELL4_FAMILY       {item.id}: cell_family {item.cell_family!r}"
            )
        if item.cell_family == "ii" and item.cell == 4:
            degree = item.ambiguity_degree
            ok = (
                degree == 2
                if item.stratum == "common_path"
                else degree is not None and degree >= 4
            )
            if not ok:
                issues.append(
                    f"AMBIGUITY          {item.id}: {item.stratum} (ii) degree {degree}"
                )
    table = {
        fam: tuple(
            sum(
                1
                for i in requests
                if i.cell == 4 and i.cell_family == fam and i.stratum == stratum
            )
            for stratum in ("common_path", "adversarial")
        )
        for fam in CELL4_TABLE
    }
    if table != CELL4_TABLE:
        issues.append(f"CELL4_FAMILY       {table}, want {CELL4_TABLE}")
    return issues


def _cells(items: Iterable[Request]) -> tuple[int, ...]:
    counts = [0, 0, 0, 0, 0]
    for item in items:
        counts[item.cell] += 1
    return tuple(counts)


def _check_smoke(doc: Freeze) -> list[str]:
    issues: list[str] = []
    ids = doc.smoke_ids
    if len(ids) != SMOKE_SIZE or len(set(ids)) != len(ids):
        issues.append(f"SMOKE              {len(ids)} ids, want {SMOKE_SIZE} unique")
    by_id = {i.id: i for i in doc.requests}
    unknown = sorted(set(ids) - set(by_id))
    if unknown:
        issues.append(f"SMOKE              not public ids: {unknown}")
    picked = [by_id[i] for i in dict.fromkeys(ids) if i in by_id]
    if not unknown and _cells(picked) != SMOKE_CELLS:
        issues.append(
            f"SMOKE              cells {list(_cells(picked))}, want {list(SMOKE_CELLS)}"
        )
    for cell, want in ((2, (2, 2)), (4, (3, 3))):
        split = Counter(i.stratum for i in picked if i.cell == cell)
        got = (split["common_path"], split["adversarial"])
        if got != want:
            issues.append(
                f"SMOKE              cell {cell} common/adversarial "
                f"{got[0]}/{got[1]}, want {want[0]}/{want[1]}"
            )
    return issues


def _check_holdout(doc: Freeze) -> list[str]:
    issues: list[str] = []
    if len(doc.holdout_pool) != HOLDOUT_SIZE:
        issues.append(
            f"HOLDOUT            n={len(doc.holdout_pool)}, want {HOLDOUT_SIZE}"
        )
    for stratum, want in HOLDOUT_MIX.items():
        got = _matrix(doc.holdout_pool, stratum)
        if got != want:
            issues.append(
                f"HOLDOUT            {stratum} {list(got)}, want {list(want)}"
            )
    return issues


def _check_permutations(doc: Freeze) -> list[str]:
    issues: list[str] = []
    for name, perm, want in (
        (
            "holdout_permutation",
            doc.holdout_permutation,
            [i.id for i in doc.holdout_pool],
        ),
        (
            "human_calibration_permutation",
            doc.human_calibration_permutation,
            [i.id for i in doc.requests],
        ),
    ):
        if len(perm) != len(set(perm)) or sorted(perm) != sorted(want):
            issues.append(
                f"PERMUTATION        {name} must list each of its {len(want)} "
                "ids exactly once"
            )
    return issues


def _check_datasets(doc: Freeze, repo: Path) -> list[str]:
    issues: list[str] = []
    for item in _everyone(doc):
        if not item.dataset_path.startswith(DATA_PREFIX):
            issues.append(
                f"DATASET            {item.id}: {item.dataset_path} is not under "
                f"{DATA_PREFIX}"
            )
        path = repo / item.dataset_path
        if not path.is_file():
            issues.append(f"DATASET            {item.id}: {item.dataset_path} missing")
        elif _sha_file(path) != item.dataset_sha256:
            issues.append(
                f"DATASET            {item.id}: {item.dataset_path} sha256 "
                "differs from the freeze"
            )
    return issues


def _check_excel(doc: Freeze) -> list[str]:
    issues: list[str] = []
    for item in _everyone(doc):
        blob = f"{item.instruction}\n{item.query_original}\n{item.query_rewritten}"
        if EXCEL_RE.search(blob):
            issues.append(f"EXCEL              {item.id}: request names Excel")
    return issues


def _check_disjoint(doc: Freeze, repo: Path, files: dict[str, Path]) -> list[str]:
    issues: list[str] = []
    for name in INSTRUMENTS:
        path = files.get(name)
        if path is None:
            issues.append(
                f"INSTRUMENT         {name}: no file; pass --instrument {name}=FILE"
            )
            continue
        try:
            pairs = set(_pairs(path))
        except (OSError, json.JSONDecodeError, AttributeError, TypeError) as exc:
            issues.append(f"INSTRUMENT         {name}: cannot read {path}: {exc}")
            continue
        hit = [
            i.id for i in _everyone(doc) if (i.instruction, i.dataset_sha256) in pairs
        ]
        if hit:
            issues.append(
                "OVERLAP            (instruction, dataset sha256) shared with "
                f"{name}: {', '.join(hit)}"
            )
    corpus_data = repo / "corpus" / "data"
    corpus_shas = (
        {_sha_file(p) for p in corpus_data.iterdir() if p.is_file()}
        if corpus_data.is_dir()
        else set()
    )
    reused = [i.id for i in _everyone(doc) if i.dataset_sha256 in corpus_shas]
    if reused:
        issues.append(
            "CORPUS_DATA        dataset bytes reused from corpus/data: "
            f"{', '.join(reused)}"
        )
    return issues


def _check_requests(doc: Freeze) -> list[str]:
    sib = _sibling()
    issues: list[str] = []
    connection = open_connection()
    try:
        for item in _everyone(doc):
            issues.extend(_check_request(item, sib, connection))
    finally:
        connection.close()
    return issues


def _check_request(
    item: Request, sib: ModuleType, connection: duckdb.DuckDBPyConnection
) -> list[str]:
    issues: list[str] = []
    if item.source == "nvbench1" and item.instruction != item.query_rewritten:
        issues.append(
            f"INSTRUCTION        {item.id}: nvbench1 instruction must equal "
            "query_rewritten"
        )
    if item.cell in {3, 4}:
        if item.cell_family is None:
            issues.append(
                f"SCHEMA             {item.id}: cell {item.cell} needs cell_family"
            )
    elif item.cell_family is not None:
        issues.append(
            f"SCHEMA             {item.id}: cell {item.cell} must not set cell_family"
        )
    if item.cell == 1:
        if not item.expressible_if:
            issues.append(
                f"EXPRESSIBLE_IF     {item.id}: cell 1 needs a non-empty list"
            )
        if item.reference_frame is not None:
            issues.append(f"NULL_FRAMES        {item.id}: cell 1 frame is not null")
        issues.extend(sib._check_cell1_request(item))
    else:
        if item.expressible_if is not None:
            issues.append(
                f"EXPRESSIBLE_IF     {item.id}: only cell 1 carries expressible_if"
            )
        if item.reference_frame is None:
            issues.append(f"NULL_FRAMES        {item.id}: only cell 1 may be null")
    issues.extend(sib._check_intent(item))
    issues.extend(sib._check_expected(item))
    if item.reference_frame is not None:
        issues.extend(sib._check_frame(item))
        if item.cell == 2:
            issues.extend(sib._check_cell2_sql(item, connection))
    elif item.cell == 2:
        issues.append(f"CELL2_SQL          {item.id}: cell 2 has no frame to check")
    return issues


def _usage() -> int:
    print(
        "usage: python tools/check_eval_freeze.py <pre-registration.json> "
        "[--repo DIR] [--instrument NAME=FILE ...]",
        file=sys.stderr,
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    repo = REPO
    instruments: dict[str, Path] = {}
    positional: list[str] = []
    while args:
        arg = args.pop(0)
        if arg == "--repo" and args:
            repo = Path(args.pop(0))
        elif arg == "--instrument" and args:
            name, sep, file = args.pop(0).partition("=")
            if not sep or name not in INSTRUMENTS or not file:
                return _usage()
            instruments[name] = Path(file)
        elif arg.startswith("-"):
            return _usage()
        else:
            positional.append(arg)
    if len(positional) != 1:
        return _usage()
    path = Path(positional[0])
    issues = validate(path, repo, instruments)
    print(path)
    for line in issues:
        print("  " + line)
    if issues:
        print(f"\nFAIL — {len(issues)} check(s) failed.")
        return 1
    print("\nOK — eval freeze is legal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
