"""The `profile.json` contract, as Pydantic models. Settled on #5 / ADR-0011.

Internal at P1 (Decision 1): these models are not in `chartagent.__all__`. The
artifact is a VFS file the planner reads (PRD 7.6), and our own Phase-2 checks.

Three things in here are load-bearing and easy to undo by accident:

  * `columns` is a LIST, never a name-keyed map -- a map collapses the duplicate
    column names ADR-0008 D4's identifier allowlist has to see.
  * Optionality is keyed on TWO cases only, emptiness and degradation, plus one
    documented exception (`StringStats.iso8601_parse_rate`). It is never keyed on
    type: that is what the discriminated union is for.
  * Every field is classified trusted/untrusted by the `TRUSTED`/`UNTRUSTED`
    ClassVars, and `test_every_field_is_classified` fails CI on a field that is
    in neither. The classification is NOT a field in profile.json.
"""

from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, Field

# --- Frozen constants (ADR-0011). Changing one changes the artifact. ----------

SAMPLE_ROWS = 10           # k, uniform (Decision 6)
SATURATION_CAP = 1001      # N: exact below, `>= N` above (Decision 4)
TOP_K = 10                 # string top-value enumeration (Decision 8)
REPORTED_TYPE_BUDGET = 120 # characters before rung 1 truncates to the head
BUDGET_BYTES = 10 * 1024   # the hard cap the ladder holds (Decision 5)

Bucket = Literal["number", "string", "boolean", "date", "timestamp", "timestamptz", "other"]

# The ladder, in firing order. Rungs fire for the WHOLE profile or not at all --
# a per-column rung makes `stats: None` undecodable (Decision 5).
Rung = Literal["reported_type_head", "sample_rows", "top_values", "percentiles", "columns"]


class _Model(BaseModel):
    """Base carrying the taint classification every subclass must complete."""
    TRUSTED: ClassVar[frozenset[str]] = frozenset()
    UNTRUSTED: ClassVar[frozenset[str]] = frozenset()


class TopValue(_Model):
    """One enumerated value and its row count. The value is data; the count is ours."""
    value: Any
    count: int
    TRUSTED = frozenset({"count"})
    UNTRUSTED = frozenset({"value"})


class NumberStats(_Model):
    """Every field required: absence of the whole object is the only signal."""
    min: float
    max: float
    p01: float
    p25: float
    p50: float
    p75: float
    p99: float
    TRUSTED = frozenset({"min", "max", "p01", "p25", "p50", "p75", "p99"})


class TemporalStats(_Model):
    """ISO-8601 strings, UTC for `timestamptz` (ADR-0008 D9). Computed, so ours."""
    min: str
    max: str
    p01: str
    p25: str
    p50: str
    p75: str
    p99: str
    TRUSTED = frozenset({"min", "max", "p01", "p25", "p50", "p75", "p99"})


class StringStats(_Model):
    """`min`/`max` are values copied from the data, so they are untrusted.

    `iso8601_parse_rate` is the one documented third optionality case: it is
    absent when the reported head is not VARCHAR (Decision 9). That stays
    decodable because degradation drops this whole object -- so inside a
    *present* `StringStats`, `None` can only mean "the head was not VARCHAR".
    """
    min: str
    max: str
    top_k_coverage: float
    iso8601_parse_rate: float | None = None
    TRUSTED = frozenset({"top_k_coverage", "iso8601_parse_rate"})
    UNTRUSTED = frozenset({"min", "max"})


class _Column(_Model):
    name: str
    reported_type: str


class NumberColumn(_Column):
    bucket: Literal["number"] = "number"
    null_rate: float
    distinct: int
    saturated: bool
    stats: NumberStats | None = None
    TRUSTED = frozenset({"bucket", "null_rate", "distinct", "saturated", "stats"})
    UNTRUSTED = frozenset({"name", "reported_type"})


class TemporalColumn(_Column):
    """One variant for three buckets: they chart differently (ADR-0010 D3) but
    share a stats shape, so splitting the model would buy nothing."""
    bucket: Literal["date", "timestamp", "timestamptz"]
    null_rate: float
    distinct: int
    saturated: bool
    stats: TemporalStats | None = None
    TRUSTED = frozenset({"bucket", "null_rate", "distinct", "saturated", "stats"})
    UNTRUSTED = frozenset({"name", "reported_type"})


class StringColumn(_Column):
    bucket: Literal["string"] = "string"
    null_rate: float
    distinct: int
    saturated: bool
    top: list[TopValue] | None = None      # dropped at rung 3, before `stats`
    stats: StringStats | None = None       # dropped at rung 4
    TRUSTED = frozenset({"bucket", "null_rate", "distinct", "saturated", "top", "stats"})
    UNTRUSTED = frozenset({"name", "reported_type"})


class BooleanColumn(_Column):
    """No `stats`: `top` enumerates every value including null, so coverage is
    definitionally 1.0 and there is nothing left to report."""
    bucket: Literal["boolean"] = "boolean"
    null_rate: float
    distinct: int
    saturated: bool
    top: list[TopValue] | None = None
    TRUSTED = frozenset({"bucket", "null_rate", "distinct", "saturated", "top"})
    UNTRUSTED = frozenset({"name", "reported_type"})


class OtherColumn(_Column):
    """No statistics at all, and therefore no scan at all (Decision 3).

    Nothing in `other` was chartable in the first place (ADR-0010 D4), so
    counting its nulls spends a column read on a number nobody reads. A source
    of 300 BLOB columns costs a footer read to profile.
    """
    bucket: Literal["other"] = "other"
    TRUSTED = frozenset({"bucket"})
    UNTRUSTED = frozenset({"name", "reported_type"})


Column = Annotated[
    NumberColumn | TemporalColumn | StringColumn | BooleanColumn | OtherColumn,
    Field(discriminator="bucket"),
]


class Truncation(_Model):
    """Present only when a rung fired; never a zeroed object."""
    rungs: list[Rung]
    omitted_count: int | None = None      # rung 5 only
    TRUSTED = frozenset({"rungs", "omitted_count"})


class Profile(_Model):
    """No source identity, no timestamps, no version field (Decision 2)."""
    row_count: int
    columns: list[Column]
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)
    truncation: Truncation | None = None
    TRUSTED = frozenset({"row_count", "columns", "truncation"})
    UNTRUSTED = frozenset({"sample_rows"})   # keys AND values


ALL_MODELS = [
    TopValue, NumberStats, TemporalStats, StringStats, NumberColumn,
    TemporalColumn, StringColumn, BooleanColumn, OtherColumn, Truncation, Profile,
]


def untrusted_paths() -> list[str]:
    """The manifest the prompt renderer consumes. Not a field in profile.json."""
    paths: list[str] = []
    for name in sorted(Profile.UNTRUSTED):
        paths.append(f"{name}[] (keys and values)" if name == "sample_rows" else name)
    for model in (NumberColumn, TemporalColumn, StringColumn, BooleanColumn, OtherColumn):
        for f in sorted(model.UNTRUSTED):
            p = f"columns[{model.__name__}].{f}"
            if p not in paths:
                paths.append(p)
    for f in sorted(StringStats.UNTRUSTED):
        paths.append(f"columns[StringColumn].stats.{f}")
    for f in sorted(TopValue.UNTRUSTED):
        paths.append(f"columns[*].top[].{f}")
    return paths


def test_every_field_is_classified() -> None:
    """The mechanism. A new field in neither set fails here, not in review."""
    for model in ALL_MODELS:
        declared = set(model.model_fields)
        classified = set(model.TRUSTED) | set(model.UNTRUSTED)
        missing, unknown = declared - classified, classified - declared
        assert not missing, f"{model.__name__}: unclassified field(s) {sorted(missing)}"
        assert not unknown, f"{model.__name__}: classified non-field(s) {sorted(unknown)}"
        overlap = set(model.TRUSTED) & set(model.UNTRUSTED)
        assert not overlap, f"{model.__name__}: field(s) in both sets {sorted(overlap)}"
