# 20. The planner's public surface: `create_chart_agent`, `ChartResult`, and `UnanswerableInstructionError`

- **Status:** Accepted
- **Date:** 2026-09-02
- **Settled on:** [#91](https://github.com/thearcscode/chartagent/issues/91)
- **Builds on:** ADR-0005 (`bind` is the public seam; the flat `errors.py` taxonomy under
  `ChartAgentError`; `pydantic.ValidationError` never crosses the seam), ADR-0018
  (`ChartRecipe`/`BoundRecipe` are not constructed at P1), ADR-0019 (the planner's two-step
  contract; `InexpressibleRequestError`/`PlannerFailureError` named; no `ChartRecipe` at P1)
- **Amends:** ADR-0019's Consequences — **"`__all__` grows by two" is wrong.** Neither
  `InexpressibleRequestError` nor `PlannerFailureError` is exported; they follow every other
  error subclass (`chartagent.errors`-only). `__all__` instead grows by one, and it isn't an
  error — it's `ChartResult`. ADR-0019's "`UnanswerableInstructionError` ... decided
  elsewhere" is discharged here.
- **Leaves open:** `create_chart_agent`/`create_chart` themselves — signatures only, no
  implementation, pending #92's planner. `history=` and conversational refinement (needs a
  VFS, P2). `quality` (needs the P2 review gate). Where a caller-supplied `backend=` override
  enters the call — [#93](https://github.com/thearcscode/chartagent/issues/93).

## Context

ADR-0019 fixed the planner's *internals* — two model calls, a backend-free frame, a fixed
ranking — and cut four questions it deliberately left unanswered into children. This ADR
answers the one about what a **caller** types: the entry point's shape, what the result
object carries, and the third P1 error PRD P0.9 named but ADR-0019 declined to define,
because defining it needed this ticket's fence between *inexpressible* (the grammar can't
say it) and *unanswerable* (the data can't back it up).

Nothing here is a build spec for the planner — `plan/` doesn't exist, and neither does a
prompt. What's fixed is the outer contract the planner will be built to satisfy: a caller's
verbs, `bind`'s existing signature and error taxonomy, and (per ADR-0018) the fact that no
`ChartRecipe` exists to complicate the result type at P1.

## Decision

### 1. `create_chart_agent(model=...)` → `ChartAgent.create_chart(data, instruction)`

A factory holding the one thing worth holding reusably at P1:

```python
class ChartAgent:
    def __init__(self, *, model: str) -> None: ...
    def create_chart(self, data: DataSource, instruction: str) -> ChartResult: ...

def create_chart_agent(*, model: str) -> ChartAgent: ...
```

**No `sandbox=`, `outputs=`, `quality=`, or `history=`.** Sandbox configuration has nothing
to configure before P2's sandbox exists; `outputs` was PRD's multi-backend list, superseded
by ADR-0019's single ranked backend; `quality` and `history` are Decision 4 and Decision 6
below. **`backend=` is deliberately absent too** — a caller override is real (ADR-0019
Decision 3: "a backend named in the instruction wins over the list"), but *where* it enters
the call is #93's question, not this one's, and adding a placeholder kwarg here would answer
it by accident.

**`create_chart` plans and binds in one call.** It profiles the source, runs both planner
steps, picks a backend, and calls `bind` itself — a caller gets a compiled-ready chart back,
not a frame they must remember to bind separately. `bind` stays public and unchanged;
`create_chart` is a composition on top of it, not a replacement for it.

**Sync only.** `bind` is synchronous because ADR-0005 decided it makes no network call;
`create_chart` is the one call here that does (the planner's two model calls), but every
caller proven so far — Studio's FastAPI routes on ADR-0006's sync-`def`-in-a-threadpool,
direct scripts — is fine with that. An async twin (`acreate_chart`) is a pure addition
later, never a breaking change, so it isn't built pre-emptively.

**Single-shot only — no `history=` at P1.** PRD §7.8's conversational refinement
(`history=result.messages`) leans on VFS-backed artifact references, and there is no VFS
until P2's sandbox lands — `HistoryReferenceError` stays fog for exactly that reason. A
reduced P1 stand-in (passing back a prior `ChartResult` directly, no reference indirection)
was considered and rejected: refinement done right needs the planner to see the *prior
planning decision*, which is P2 machinery, and a stand-in now risks a signature that has to
be widened rather than merely added to once the real one exists.

### 2. `ChartResult` wraps `Envelope`, and carries nothing else at P1

```python
class ChartResult:
    envelope: Envelope
    def refresh(self, data: DataSource) -> ChartResult: ...
```

**A thin wrapper, not itself a wire type.** `Envelope`'s wire format is frozen at exactly
three keys (ADR-0005) precisely so nothing widens it by accident; a `ChartResult` that
flattened those fields onto itself would either duplicate that contract or drift from it the
first time one changes. Studio (a plain public-API consumer) reaches `.envelope.to_dict()`
to serialise; `ChartResult` itself never goes on the wire.

**`refresh(data)` re-binds, never re-plans** — this is CONTEXT.md's zero-LLM refresh, spelled
out as a method: `bind(stripped_input, data, backend=self.envelope.backend)`, where
`stripped_input` is `envelope.input` with the `"data"` key removed first.
`InputFrame`'s own validator rejects inline `data` as a `SpecShapeError`
(`src/chartagent/frame/input.py`, the `extra_forbidden` check at `("data",)`) — the exact
frame `bind` returned already carries bound rows at `input["data"]`
(`src/chartagent/bind.py:117`), so passing it straight back in is a guaranteed rejection, not
a hypothetical one. **Returns a new `ChartResult`**; the original is untouched. No
`instruction=` parameter — there is nothing to re-plan — and no in-place mutation, matching
every other frozen-ish object in this codebase (`Advisory`, `DriftedField`).

### 3. `UnanswerableInstructionError`, and the fence that keeps it out of bucket 1

```python
class UnanswerableInstructionError(ChartAgentError):
    kind: Literal["missing_column", "missing_role"]
    keys: tuple[str, ...]
```

**The fence is column existence.** If the instruction names or requires a column that
genuinely isn't in the profiled source — wrong grain, a concept the data doesn't carry —
that's `UnanswerableInstructionError`. If every referenced concept maps to a real column but
the transform menu or the chart-type vocabulary can't shape them into any of the 48, that's
still `InexpressibleRequestError` (ADR-0019). This is mechanical, not a judgement call, which
is what stops bucket 1 silently absorbing bad instructions — the exact failure mode ADR-0019
Decision 5 flagged and left to this ticket to close.

- **`kind="missing_column"`**: `keys` names the specific columns claimed but absent.
- **`kind="missing_role"`**: `keys` names the **absent source buckets** — the same
  seven-value vocabulary `source_schema` already uses (`number`, `string`, `boolean`, `date`,
  `timestamp`, `timestamptz`, `other`; ADR-0010), not a new role taxonomy. An unspecific ask
  ("make it look nicer" against no coherent question) is the limiting case of this kind, with
  `keys=()` — not a third `kind`, because every unanswerable request bottoms out at "some
  column needs to play some role I don't have," and a nonspecific ask is just the case where
  the model can't name which bucket.
- **No `reference` field beyond `keys`.** A claimed gap the profile already fills — a named
  column that *does* exist — is not this error at all: it's a **step-1 schema failure**
  (ADR-0019 Decision 7's pattern, same treatment as a bucket-2 claim carrying a valid
  `transform`), retried and then a planner-failure miss if it survives the retry.

Step 1's tagged union (ADR-0019 Decision 2) therefore grows a third member on top of
`Fragment | Inexpressible{bucket}` — the `UnanswerableInstructionError` shape above, elicited
the same way. Formalising that as a pydantic schema is #92's job (the prompt renderer); this
ADR fixes the shape it must match.

### 4. Caller semantics: docstrings, not a `retryable` flag

None of the three P1 errors gets a machine-readable retry signal. `PlannerFailureError`
already exhausted retries at the level that knows what retrying means
(`reason="retries_exhausted"`); `InexpressibleRequestError` and `UnanswerableInstructionError`
need the instruction or the data changed, which no boolean expresses. Whether a caller
retries the *whole* `create_chart` call is a product decision (cost, UX) this library
shouldn't make for them by exposing a flag that reads as a recommendation. Guidance lives in
each error's docstring instead.

**`bind`'s own errors surface un-wrapped.** Since `create_chart` calls `bind` internally
(Decision 1), `BackendCapabilityError`, `SchemaDriftError`, `TransformError`, and
`RawSqlRejectedError` can all now originate from a `create_chart` call too. They need no
wrapping: every one is already a `ChartAgentError` subclass, so `except ChartAgentError`
catches everything from one call site regardless of which internal verb raised it — exactly
what ADR-0005's flat taxonomy bought.

### 5. `quality` does not exist at P1

PRD §7.8's `quality="balanced"` governs the review gate, which is P2 ("Review-gate tier
design" is still fog on the map). Omitted entirely rather than accepted as a reserved
no-op — a kwarg that silently does nothing reads as "it works, I just haven't tuned it,"
which is worse than a clean `TypeError` when P2 adds it for real.

### 6. Implementation scope: what ships in this PR, and where it lives

`ChartResult.refresh()` only needs `bind` (already public); the three errors are typed
exceptions with no planner dependency; the scorer change is mechanical. All three ship as
real code now. `create_chart_agent`/`create_chart` need the planner (no `plan/` module, no
prompt) and stay signatures-only until #92.

- **New `chartagent/result.py`** holds `ChartResult`. Not `plan/` — creating that directory
  now, for one wrapper class that does no planning, would misname it before anything
  planning-shaped lives there; #92 owns `plan/` for the planner's private internals. Not
  `envelope.py` either, which stays `Envelope`'s own module, single-purpose the way
  `errors.py` is flat. **`chartagent.result` is a stable import path** — #92 does not relocate
  `ChartResult` into `plan/` later.
- **`ChartResult` joins `__all__`** beside `Envelope`, following the result-type precedent.
  The three errors stay `chartagent.errors`-only, following the error-subclass precedent
  (every existing subclass — `SpecVocabularyError`, `BackendCapabilityError`, etc. — is
  reached the same way, never re-exported at the top level).
- **The scorer gains `miss_kind: "unanswerable_instruction"`**, a sibling to the existing
  `planner_failure` constant in `tools/score_corpus.py`, not a new bucket. The reconciliation
  identity extends:

  ```
  hits + buckets 1–4 + planner_failure + unanswerable_instruction + unattributed = n
  ```

## Consequences

- **`__all__` grows by one, and ADR-0019's Consequences said two.** Corrected here:
  `ChartResult` is the addition; neither new-named error is exported.
- **`create_chart_agent`/`create_chart` are a signed contract with no implementation.** #92
  builds against this shape; if the planner's real constraints force a change here, this ADR
  gets an erratum rather than the ticket being silently reopened.
- **The scorer's reconciliation identity changes for the second time** (ADR-0019 added
  `planner_failure`; this ADR adds `unanswerable_instruction`) — both are sibling `miss_kind`
  values, never buckets, keeping the four-bucket vocabulary ADR-0013/ADR-0014 closed shut.
- **`bind`'s error surface is now reachable two ways** (directly, and through
  `create_chart`), with no new wrapping layer — a consequence of Decision 1, priced in
  Decision 4.
- **History and quality are named absences, not silent ones.** A caller reading this ADR
  knows `history=`/`quality=` are coming at P2, rather than discovering their omission by
  trial and error.

## Alternatives rejected

- **A plain top-level function instead of a factory.** Simpler at P1 (nothing to hold besides
  `model`), but the factory is where P2's sandbox/quality config will land, and reshaping a
  function into a factory later is a breaking change; the reverse never is.
- **`create_chart` stops at the planned frame, leaving `bind` to the caller.** Matches
  ADR-0019's own "frame stays backend-free" framing, but defeats the purpose of a one-call
  entry point — PRD §7.8's `result.artifacts`/`result.spec` only make sense against bound
  output.
- **`ChartResult` as its own serialisable `pydantic.BaseModel`**, flattening `Envelope`'s
  fields. Rejected because it duplicates or drifts from `Envelope`'s frozen three-key wire
  contract, which ADR-0005 fixed specifically to prevent that.
- **A `role: str` field on `UnanswerableInstructionError`** naming a semantic role
  (`"temporal"`, `"measure"`) rather than reusing `keys` with the source-bucket vocabulary.
  Rejected as a parallel vocabulary next to `source_schema`'s seven buckets, for no
  expressive gain — the profiler already speaks in buckets, not roles.
- **A third `kind` for an unspecific ("vibes") ask.** Rejected — it's the limiting case of
  `missing_role` with `keys=()`, not a different failure shape, and a third catch-all value
  would tempt every future ambiguous case to land there by default.
- **A `retryable: bool` on the error taxonomy.** Rejected — none of the three has a retry
  semantics simple enough for a boolean to be honest (see Decision 4).
- **A reduced `history=` at P1** (caller passes back the previous `ChartResult` directly, no
  VFS indirection). Rejected — real refinement needs the planner to see the prior planning
  decision, and a stand-in now is more likely to need widening than extension once P2's VFS
  exists.
- **Creating `plan/` now** to hold `ChartResult`. Rejected — the directory should be named by
  what actually lives there; #92 is what gives it a reason to exist.

## Evidence

- `src/chartagent/bind.py:117` — `payload["data"] = {"values": rows}`, confirming `Envelope.input`
  already carries bound rows that `refresh()` must strip before re-binding.
- `src/chartagent/frame/input.py` — the `extra_forbidden` check at `("data",)` raising
  `SpecShapeError("input frame must not carry inline data")`, confirming that check fires
  unconditionally on a bound frame handed back to `bind` unmodified.
- `src/chartagent/__init__.py` — current `__all__` exports `Envelope` (a result type) but no
  error subclass beyond the `ChartAgentError` base, the precedent both `ChartResult` and the
  three new errors follow.
- `tools/score_corpus.py` — `PLANNER_FAILURE_KIND` and the `hits + buckets + planner_failure +
  unattributed = n` reconciliation this ADR extends by one term.

## Related

- [#91](https://github.com/thearcscode/chartagent/issues/91) — the grilling this settles.
- [#79](https://github.com/thearcscode/chartagent/issues/79) / ADR-0019 — the parent ticket,
  amended above.
- [#92](https://github.com/thearcscode/chartagent/issues/92) — the prompt renderer; builds
  `plan/` and implements `create_chart_agent`/`create_chart` against this contract.
- [#93](https://github.com/thearcscode/chartagent/issues/93) — backend ranking; now
  unblocked, and owns where a caller's `backend=` override enters the call.
