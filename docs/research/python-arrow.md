# Research: Minimum Python floor + Arrow as internal interchange format

Resolves the two open **§13 [Engineering, non-blocking]** questions in `chartagents-prd.md`
(GitHub issue #8). This is AFK research: it surfaces the facts and gives a recommendation with
tradeoffs. The decision itself graduates from these facts.

- **Date:** 2026-07-15
- **Scope:** core deps (DuckDB, Pydantic v2, LangGraph, deepagents, pyarrow, matplotlib);
  Arrow zero-copy story with DuckDB and with pandas/Polars (PRD §7.4 flavor 3).

---

## Question 1 — Minimum supported Python version

### Evidence: `requires-python` of each core dependency

Values read from PyPI package metadata (latest release as of 2026-07-15):

| Dependency         | Latest version | `requires-python` | Classifiers (max) | Binding? |
| ------------------ | -------------- | ----------------- | ----------------- | -------- |
| DuckDB (Python)    | 1.5.4          | `>=3.10.0`        | 3.10 – 3.14       | no       |
| Pydantic v2        | 2.13.4         | `>=3.9`           | 3.9 – 3.14        | no       |
| LangGraph          | 1.2.9          | `>=3.10`          | 3.10 – 3.13       | no       |
| **deepagents**     | 0.6.12         | `>=3.11,<4.0`     | 3.11 – 3.14       | **yes**  |
| pyarrow            | 25.0.0         | `>=3.10`          | 3.10 – 3.14       | no       |
| **matplotlib**     | 3.11.0         | `>=3.11`          | 3.11 – 3.14       | **yes**  |

Sources:
- DuckDB: <https://pypi.org/pypi/duckdb/json> — `requires_python = ">=3.10.0"`. (Note: DuckDB
  raised its floor from 3.9 to 3.10 in the 1.x line; older search results still cite 3.9.)
- Pydantic: <https://pypi.org/pypi/pydantic/json> — classifiers 3.9–3.14; effectively `>=3.9`.
- LangGraph: <https://pypi.org/pypi/langgraph/json> — `requires_python = ">=3.10"`.
- deepagents: <https://pypi.org/pypi/deepagents/json> — `requires_python = "<4.0,>=3.11"`;
  built on the LangChain/LangGraph 1.x stack (langchain-core `>=1.4.8`, langchain `>=1.3.11`).
- pyarrow: <https://pypi.org/pypi/pyarrow/json> — `requires_python = ">=3.10"`.
- matplotlib: <https://pypi.org/pypi/matplotlib/json> — `requires_python = ">=3.11"`.

### Lowest Python that satisfies ALL deps

**Python 3.11.** Two deps set the floor: **matplotlib 3.11** (`>=3.11`) and **deepagents 0.6.12**
(`>=3.11`). Everything else already allows 3.10 or 3.9, so they are not the constraint. 3.10 is
ruled out purely by matplotlib and deepagents.

### What the broader ecosystem targets (SPEC 0 / NEP 29)

The Scientific Python ecosystem follows **SPEC 0** (successor to NEP 29): drop a Python version
**3 years after its release**, i.e. support roughly the last three minor versions.

- Python 3.11 (released 2022-10-24): SPEC 0 recommended-drop **Q4 2025** — already past as of
  mid-2026.
- Python 3.12 (released 2023-10-02): supported through **2026-10-01**.
- Python 3.13 (released 2024-10-07): supported through **2027-10-07**.

So as of July 2026, the SPEC-0-recommended **minimum is 3.12** (3.11 has just aged out of the
window), with the ecosystem actively supporting 3.12 and 3.13. NumPy/pandas/matplotlib are all
moving in lockstep with this schedule (matplotlib's own `>=3.11` floor reflects it).

Sources:
- SPEC 0: <https://scientific-python.org/specs/spec-0000/> — support window table; 3.11
  `2022-10-24 → 2025-10-23`, 3.12 `2023-10-02 → 2026-10-01`, 3.13 `2024-10-07 → 2027-10-07`.
- NEP 29: <https://numpy.org/neps/nep-0029-deprecation_policy.html>.

### Recommendation

**Set the floor at Python 3.11** (`requires-python = ">=3.11"`), and test CI against **3.11,
3.12, 3.13**.

- 3.11 is the true hard minimum: it is the lowest version every core dependency installs on today
  (matplotlib and deepagents both forbid 3.10).
- It is also the widest reach we can offer without patching or pinning around a dependency.

**Tradeoff / alternative — 3.12:** A defensible case exists for starting at **3.12** instead,
since 3.11 has already passed its SPEC-0 drop date (Q4 2025) and the scientific stack now targets
3.12+ as its minimum. For a brand-new project starting mid-2026, choosing 3.12 costs almost
nothing (all deps support it), buys longer alignment with SPEC 0, and unlocks 3.12 language/perf
features. The only thing 3.11 buys over 3.12 is compatibility with users still on 3.11 — a
shrinking population.

**Bottom line:** 3.11 is the *floor the dependencies impose*; 3.12 is the *floor the ecosystem is
moving to*. Recommend `>=3.11` for maximum reach, or `>=3.12` if the team prefers to ride the
SPEC-0 line — either is safe. Do **not** target 3.10 or below (blocked by matplotlib + deepagents).

---

## Question 2 — Arrow as internal interchange format

The PRD (§7.4) already leans on Arrow: flavor-3 "in-memory result set" DataSources take a
DataFrame / Arrow table / list-of-dicts, and DuckDB "queries the frame zero-copy." This verifies
that story.

### DuckDB ↔ Arrow (both directions)

**Confirmed genuinely zero-copy in both directions.** DuckDB streams data to/from Arrow operating
directly on Arrow's buffers — no buffer duplication.

- **Ingest (Arrow → DuckDB):** `duckdb.from_arrow(table)` creates a zero-copy relation, or query
  the Arrow object directly by name via a **replacement scan** (`SELECT * FROM my_arrow_table`).
  DuckDB pushes filters/projections down into the Arrow scan, so only needed columns/partitions
  are touched.
- **Export (DuckDB → Arrow):** `.arrow()` / `.fetch_arrow_table()` return an Arrow Table;
  `.fetch_record_batch()` returns a streaming `RecordBatchReader`. Streaming (not just
  full-materialization) has been supported since the Arrow 7.0 era; the original 2021 blog noted
  full-table-only in Arrow 6.0, which is long resolved.

This is exactly the mechanism PRD flavor 3 depends on: a caller's Arrow table (e.g. a Cortex
Analyst result set) is registered and queried without re-materializing the data.

Sources:
- <https://duckdb.org/2021/12/03/duck-arrow> — "zero-copy streaming of data between DuckDB and
  Arrow and vice versa"; `from_arrow`, replacement scans, `.arrow()`, `fetch_record_batch`.
- <https://arrow.apache.org/blog/2021/12/03/arrow-duckdb/> — Apache Arrow's write-up of the same.
- <https://duckdb.org/2023/08/04/adbc> — DuckDB ADBC, zero-copy transfer over Arrow Database
  Connectivity (relevant if flavor-2 connections later want Arrow-native transport).

### pandas / Polars DataFrame ↔ Arrow (PRD §7.4 flavor 3)

**Polars ↔ Arrow: effectively zero-copy.** `to_arrow()` / `from_arrow()` are zero-copy "for the
most part." Polars implements the **Arrow PyCapsule Interface** (v1.3+) for sharing Arrow data
across libraries without copying.
- Caveat: zero-copy holds when a Series is a **single chunk**; a multi-chunk Series passed to
  `pyarrow.array` will copy. Unsupported types get cast to the nearest supported type.

**pandas ↔ Arrow: zero-copy only for Arrow-backed columns.**
- If a pandas column uses the **PyArrow extension dtype** (pandas 2.x `dtype_backend="pyarrow"`),
  ingest/export is a metadata handshake — no copy. `df.to_pandas(use_pyarrow_extension_array=True)`
  (Polars) and `Table.to_pandas()` with Arrow-backed arrays stay zero-copy and preserve nulls.
- If columns are **classic NumPy-backed**, `to_pandas()` incurs a copy: pandas "consolidates"
  like-typed columns into 2-D NumPy blocks, which forces a **memory doubling** during handoff.
  `split_blocks=True` avoids consolidation (one block per column) but is still not truly zero-copy
  for all dtypes, and object/mixed columns always copy.

Sources:
- Polars Arrow producer/consumer: <https://docs.pola.rs/user-guide/misc/arrow/>.
- `polars.DataFrame.to_arrow`:
  <https://docs.pola.rs/py-polars/html/reference/dataframe/api/polars.DataFrame.to_arrow.html>.
- Arrow ↔ pandas integration (consolidation, memory doubling, `split_blocks`,
  extension arrays): <https://arrow.apache.org/docs/python/pandas.html>.

### Costs / caveats

- **pyarrow is a heavy binary dependency.** The wheel is a large native package (Arrow C++
  bundled); installed footprint is on the order of 100 MB+. This inflates image size and cold-start
  in constrained environments (Lambda-style). conda-forge splits it into multiple packages to
  mitigate; pip has no slim variant out of the box.
  Source: <https://arrow.apache.org/docs/python/install.html>.
- **Version pinning risk.** DuckDB's Python wheel bundles its own Arrow C++, but the *Python-side*
  Arrow interchange still needs a compatible `pyarrow` installed. Keep DuckDB and pyarrow versions
  compatible; both release frequently. Pin a tested pair and bump deliberately (mirrors the PRD's
  existing "pin versions" stance on deepagents churn, §11).
- **Zero-copy is conditional, not automatic.** It breaks on: multi-chunk arrays, object/mixed
  dtypes, NumPy-backed pandas columns, and any type not natively representable. Treat zero-copy as
  a fast path, not a guarantee — code should be correct (and memory-bounded) even when a copy
  happens.
- **Memory behavior.** For the true zero-copy paths, memory is shared (no duplication). The pandas
  consolidation path can transiently double memory; prefer Arrow-backed dtypes or `split_blocks`
  when converting to pandas.

### Recommendation

**Yes — adopt Arrow as the internal interchange format** (confirms the PRD's "leaning yes").

- It is the native, verified zero-copy bridge between DuckDB (our profiling/transform engine) and
  the flavor-3 DataFrame/Arrow inputs — precisely the §7.4 use case. DuckDB ↔ Arrow is zero-copy
  both ways; Polars ↔ Arrow is effectively zero-copy; pandas is zero-copy when Arrow-backed.
- pyarrow is already an effectively-transitive dependency of this stack, so the marginal cost of
  standardizing on Arrow is low relative to the interop win.

**Guardrails to write into the design:**
1. Pin a tested `(duckdb, pyarrow)` version pair; bump together.
2. Document zero-copy as a fast path with explicit fallbacks (multi-chunk, object dtype,
   NumPy-backed pandas → copy). Since flavor-3 result sets are "small by construction" (§7.4,
   §13 adapter-handoff), a fallback copy is cheap and not a correctness risk.
3. Note the pyarrow install weight in packaging docs; consider it when sizing sandbox/runtime
   images.

---

## Summary

| Question             | Recommendation                                                              |
| -------------------- | --------------------------------------------------------------------------- |
| Min Python floor     | **`>=3.11`** (hard floor set by matplotlib + deepagents); `>=3.12` if aligning to SPEC 0. Not below 3.11. Test 3.11–3.13. |
| Arrow as interchange | **Yes.** Zero-copy verified: DuckDB↔Arrow (both ways), Polars↔Arrow; pandas zero-copy only when Arrow-backed. Pin duckdb/pyarrow; treat zero-copy as a fast path with copy fallbacks. |
