# 23. The transform menu is typed once

- **Status:** Accepted
- **Date:** 2026-09-13
- **Settled on:** [#139](https://github.com/thearcscode/chartagent/issues/139)
- **Builds on:** ADR-0008 (the eight-slot menu, the closed `Expr` AST, unknown slots are a
  hard error), ADR-0010 (existing bytes are never rewritten; `spec_version` signals without
  guaranteeing), ADR-0013 Decision 6 (mean planner calls per chart), ADR-0019 (step 1's
  retry budget; the Decision 6 erratum making the extra ask a repair,
  [#140](https://github.com/thearcscode/chartagent/issues/140)), ADR-0022 (the generated
  vocabulary; the static, cached system prompt; the vendor-agnostic client)
- **Amends:** ADR-0008 Decisions 4 and 13, ADR-0022 Decision 7 — dated errata in place
- **Leaves open:** the build tickets that implement this; the Studio scan of persisted
  frames, which is Studio's

## Context

At the P1-exit recording, 48 of 150 runs ended `planner_failure` / `invalid_emit`. 43 of
them are `step1_calls=2, step2_calls=0`: the recorder counts a step-1 call only after it
decodes, so each is two decoded fragments that `assemble` rejected. `assemble`'s step-1 check
is `check_transform_shape` plus one encoding-`type` rule, so these are overwhelmingly
transform-shaped misses. What the journal lacks is the rejected emit and the checker message,
not the diagnosis.

The gap is structural. `Fragment.transform` and `XChartagent.transform` are both
`dict[str, Any]`. The prompt lists slot names and `Expr` kind names; the real rules live in
hand-written dict walkers that run after the model returns. ADR-0008's Consequences obliged
*"the `Expr` AST as a Pydantic discriminated union"*. It was never built.

Reading the 82 recorded envelopes against a prototype typed model surfaced a second, worse
fact: **19 runs across 9 requests carry sort items shaped `{field, order}`**, not ADR-0008's
`{field, dir, nulls}`. The compiler reads `item.get("dir", "asc")` and never refuses an
unknown item key, so all 19 bound, painted and counted as hits — and the 5 `descending` items
were drawn ascending. ADR-0008 Decision 13 closed the **slot** vocabulary; nothing closed the
keys **inside** a slot's items. That is the silently-dropped-`filter` failure Decision 13
exists to prevent, one level down.

## Decision

### 1. One typed menu, in `transform/`, used by the fragment and the stored frame

A single Pydantic model of the eight slots, `raw_sql`, and the `Expr` tree lives in
`transform/`. `Fragment.transform` and `XChartagent.transform` are both typed by it. The
data-free shape rules `check_transform_shape` and `check_expr_shape` enforce today move onto
that model: closed slots and item keys, `count` takes no `field`, `count_distinct` requires
one, `case` requires `else` and non-empty `whens`, arity, `in`'s literal-only right-hand side,
`raw_sql` exclusive-or with every slot, and a present-but-empty `group_by` plus `aggregate`.

What needs the source stays in `bind`: column existence and scope per stage, and
literal-versus-column bucket compatibility (ADR-0008 Decision 4).

**This does not reopen ADR-0008's rejected full static type checker.** The model states
shape; it resolves no column, infers no result type beyond what shape alone decides, and
cannot disagree with DuckDB's binder about anything the binder decides.

A step-1-only schema beside the dict checkers was rejected: it is the "narrower hand-written
schema" ADR-0019 refused — a third grammar.

### 2. `Expr` is arity-grouped, with callable discriminators

Eight shapes, each carrying a `kind` enum: `col`, `lit`, unary (`is_null`, `is_not_null`,
`not`, `neg`), binary (six comparisons, four arithmetic, three string tests), n-ary (`and`,
`or`, `concat`, `coalesce`), `between`, `in`, `case`. A callable discriminator maps `kind` to
its shape, and `Menu` versus `RawSql` is decided by the presence of a `raw_sql` key — so a
decode failure names **one** path, which is what a repair turn feeds back.

Measured with prototypes: one class per kind is about **53.7 KB** of JSON schema; the
arity-grouped transform is about **7.9 KB**; today's whole `Step1Result` is about **3.9 KB**.
The tool schema pydantic-ai emits for a callable discriminator was checked to be the arity form
— a `oneOf` of `$ref`s to the group definitions — not an expansion per kind.

Arity bounds stay in the schema as `minItems` / `maxItems`. They are guidance to the model and
enforced by Pydantic on decode.

### 3. Non-strict, vendor-agnostic: first-ask legality is prompted, not enforced

Anthropic's strict tool use and JSON outputs do not support recursive schemas, nor
`minItems` other than 0 or 1. `Expr` is recursive. So step 1 stays **non-strict on every
vendor**, as pydantic-ai already sends it, and the typed menu reaches the model as a tool
schema that guides generation and rejects an illegal emit at decode.

**`Expr` is not unrolled to a fixed depth** to fit one vendor's strict mode — that adds a
nesting cap ADR-0008 never had. **OpenAI is not special-cased** into strict mode; ADR-0022
Decision 9's vendor-agnostic client holds.

Consequently, first-ask legality is an observed rate and never a guarantee, which is why it is
measured (Decision 8).

### 4. Item keys are closed, and the silent drop is fixed before the typed model

ADR-0008 Decision 13's "unknown is a hard error" extends from slots to the objects inside
them: an unrecognised key in a `sort`, `aggregate`, `bin`, `derive` or `limit` item, **or on
any `Expr` node** (an `alias` on a `col`, say), is `SpecShapeError`. `check_expr_shape` ignores
extra node keys today, which is the same trap as `{field, order}`: left open, a baseline would
count the shape as legal and charge its refusal to the typed menu. It ships **first, in the
existing checker**, as its own bug fix — a silent wrong chart does not wait for a refactor.

A `sort.field` naming a column **not in output scope** is silently skipped by the compiler
today, against ADR-0008 Decision 2's *"must be an output column"*. It needs the rows' scope, so
it is a bind-time refusal that the typed model cannot make; it is its own later ticket and
blocks neither the measurement nor the typed menu.

The frozen score is **not** re-scored. The runs whose sort direction was ignored are disclosed
in `corpus/report-notes.md` beside `corpus/report.md`, whose bytes are not touched.

### 5. No `spec_version` bump; enforcement moves to parse

The grammar is ADR-0008's, unchanged. Only **where** a data-free shape fault is caught moves:
a malformed stored transform now fails when the input frame is parsed, not only when `bind`
runs. A bump would claim the grammar moved (ADR-0010 Decision 10). A lenient read of older
frames is rejected — it would keep the silent drop alive for exactly the frames that have it.

A parse failure reaches the caller as **`SpecShapeError` with a field path**, never a raw
pydantic `ValidationError`. **No new public name is added**: `InputFrame` is already in
`__all__`, and `InputFrame.model_validate` already maps `ValidationError` through
`_map_validation_error`; that mapping is extended so a transform shape fault carries its field
path. Studio runs `InputFrame.model_validate` over every persisted `spec_revisions.content`
**before** the typed menu
rolls out, lists failures by path, and **rewrites no bytes** (ADR-0010 Decision 1). Whether
Studio has persisted frames is unknown and treated as yes. The scan is Studio's, not a job in
the library.

### 6. Prompt prose states only what a JSON schema cannot, and each line is tested

A rule the schema can state lives on the model and reaches the model through the schema; its
prose line in `step1.system.md` is **deleted** — `transform.aggregate items are {name, op,
field?}` is the first. A rule no JSON schema can state may stay as a prose line **only with a
test** that the checker or model actually enforces it. Two such lines are licensed:
UNPIVOT, window functions and JSON extraction go to `raw_sql` alone; `having` is the late
filter and may reference derived columns.

The step-1 system prompt stays static and cached (ADR-0022 Decision 6). No loader is added.

### 7. The exhibits, by name

- **A chartagent-owned planner skill** injected into step 1 — **rejected.** Its content is
  Decision 6's lines or Decision 2's schema under another name, plus a loader and a place for
  the grammar to drift.
- **Off-the-shelf backend skills** (e.g. `sentimony/skills@echarts`) — **rejected.** They teach
  backend-native dialects — the habits already leaking into the untyped `transform` — and
  nothing about the menu.
- **Data Formulator** (`microsoft/data-formulator`) — its **error-repair** pattern is
  **accepted** and already shipped as #140; its **LLM-written pandas transforms** are
  **rejected** — the custom rail arriving at P1 when a stored `transform` does the job. Its
  Flint compile is shared compiler, not shared planner grammar.
- **Do nothing more; repair is enough** — **rejected.** Repair does not pay ADR-0008's debt, and
  a first-ask miss still costs a call on every affected chart.

### 8. The measurement: asks, attempts, and a from-scratch set

**The recorder counts every ask**, including one that fails to decode — otherwise typing moves
transform misses from `step1_calls=2` to `step1_calls=0` and the metric changes meaning
mid-series. Each attempt is journalled with `step: 1 | 2`, an outcome
`decode | assemble | refuted | ok`, the rejected emit, and the checker message. The vocabulary
stays four values: a step-2 `chartProperties` failure is `decode`, and the post-step-2 `bind`
wrap is `assemble`. A well-formed inexpressible or unanswerable verdict is `ok`, with `emit`
recording which of `fragment | inexpressible | unanswerable` it was.

**First-ask legality** is measured on a from-scratch instruction set of 20–30 instructions over
the existing `tests/data/` fixtures plus one new, from-scratch fixture carrying a `DATE`, a
`TIMESTAMP`, a nullable numeric and a string category. The instruction texts are authored by a
human, or by a session that never opens `corpus-prereg-v1`; not by the implementer of the
recorder or the typed menu. Nothing is adapted from `corpus/`. Each instruction is tagged with
the slots it intends to exercise and carries no expected chart.

The rate reads **only the first step-1 attempt**: runs whose first step-1 attempt is `ok`,
over instructions × 3 runs, at temperature 0, on the P1-exit model string
(`anthropic:claude-sonnet-4-6`). It is published twice — verdicts included and verdicts
excluded — with the attempt-outcome breakdown and repair success beside it and never folded in.
The report lives in `docs/research/`.

**Order matters.** The baseline runs on the untyped planner **after** Decision 4's item-key fix
and **before** the typed menu; the after-measurement runs on the same committed set. A baseline
taken before the fix would count `{field, order}` as first-ask `ok` and charge its correction to
the typed menu. The typed menu may move remaining misses from `assemble` to `decode`; the
breakdown makes that shift visible.

**There is no gate.** The typed menu is owed. An after-rate below the baseline opens a follow-up
grilling on Decision 6's prose lines; it never reverts the typed model.

## Consequences

- **A malformed stored frame fails at parse.** Code that parsed a frame and bound later now sees
  `SpecShapeError` earlier. `refresh` on a saved frame carrying `{field, order}` raises rather
  than drawing the wrong order.
- **Step 1's tool schema roughly triples** — an estimate from the two measured parts (about
  3.9 KB today plus about 7.9 KB of typed transform), not a measured combined schema. It rides
  the tool definition, not the per-request user turn.
- **Two sources of shape truth collapse to one**: the data-free halves of `menu.py` and
  `expr.py` become model validation; the compilers keep only what needs the source.
- **`step1_calls` changes definition** from decoded emits to asks. Series recorded before the
  recorder change are not comparable on that column, and the report says so.
- **`oneOf` in a non-strict tool schema** is accepted per the vendor-agnostic client's contract
  but was not verified by a live call here; the typed-menu build smoke-tests each shipped vendor
  extra.

## Alternatives rejected

- **A step-1-only transform schema** beside the dict checkers — a third grammar (Decision 1).
- **One `Expr` class per kind** — about 7× the schema for the same grammar (Decision 2).
- **Depth-unrolled `Expr` for Anthropic strict mode**, or **strict on OpenAI only** — a nesting
  cap or a vendor special case the grammar never had (Decision 3).
- **A MINOR bump to 1.3**, or **lenient reads below it** — the grammar did not move, and
  leniency preserves the silent drop (Decision 5).
- **Hand-written grammar prose the schema could state** — typed twice (Decision 6).
- **A chartagent-owned skill; third-party backend skills; LLM-written pandas; doing nothing** —
  Decision 7.
- **Measuring on `corpus-prereg-v1`, or on a set adapted from it** — the freeze (ADR-0014
  Decision 13; ADR-0022 Decision 8).

## Evidence

- `corpus/outputs.json` (P1-exit, 150 runs): 48 `invalid_emit` — 43 at `step1_calls=2,
  step2_calls=0`, 3 at `1, 1`, 2 at `0, 0` (both `r09`, decode failures).
- `tools/record_corpus.py` `RecordingClient.run`: the step counter increments only after
  `client.run` returns.
- `build/corpus/journal.jsonl`: 19 runs with `{field, order}` sort items — `r03` ×3, `r06` ×3,
  `r09` ×1, `r20` ×3, `r21` ×1, `r22` ×1, `r30` ×3, `r37` ×3, `r43` ×1; 5 `descending` items
  (`r20` ×3, `r21`, `r22`). All rail hits.
- `transform/menu.py` `_apply_sort_limit`: `item.get("dir", "asc")`, no unknown-key refusal.
- Prototype schemas, 2026-09-13, pydantic 2.13.5 / pydantic-ai 2.40.0: 53,658 bytes per-kind;
  7,862 bytes arity-grouped; `Step1Result` 3,856 bytes; callable-discriminator tool schema is a
  `oneOf` of group `$ref`s.
- Anthropic structured-outputs documentation, retrieved 2026-09-13: recursive schemas not
  supported, `minItems` 0 or 1 only, in both JSON outputs and strict tool use.

## Related

- [#139](https://github.com/thearcscode/chartagent/issues/139) — the grilling this settles.
- [#140](https://github.com/thearcscode/chartagent/issues/140) — repair, the other half of
  the step-1 lever.
- [#16](https://github.com/thearcscode/chartagent/issues/16) — the map.
