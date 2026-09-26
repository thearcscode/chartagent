# 27. Escalation is a Flint `marks_present` hop on a host-owned loop

- **Status:** Accepted
- **Date:** 2026-09-20
- **Errata:** 2026-09-26 ([#189](https://github.com/thearcscode/chartagent/issues/189)) —
  Decision 9 gains `bound`, recorded in place.
- **Settled on:** [#168](https://github.com/thearcscode/chartagent/issues/168)
- **Builds on:** ADR-0013 Decision 6 (a review fail that does not escalate stays
  deterministic; an escalation scores custom), ADR-0015 (python `SandboxBackend` is a later
  widening), ADR-0016 Decisions 3/12 (bucket 4; the gate owns policy), ADR-0017 (P2 custom
  rail is the web document, not a Python sandbox), ADR-0018 Decisions 10–11 (escalation is
  not a revision; `escape_reason` on the recipe), ADR-0019 Decision 6 (emit-repair budgets
  1/2/5; at P1 the library raises rather than constructing a recipe), ADR-0020 (public
  surface; `ChartResult` envelope-only at P1; `quality=` omitted rather than reserved),
  ADR-0022 Decision 9 (pydantic-ai in the vendor extra), ADR-0024 (Tier-1 fail blocks
  Tier 2; `painted` vs `marks_present`), ADR-0025 (`data_truthfulness` as a custom-rail
  trigger candidate), ADR-0026 (repairable critique; `marks_present` unrepairable;
  `critique()` leaf; `critique_model` has no default)
- **Amends:** ADR-0020 Decisions 1, 2 and 5; ADR-0024 *Leaves open* (Tier-1 escalation);
  ADR-0025 *Leaves open* (`data_truthfulness` escalation); ADR-0026 *Leaves open* (repair
  counts, inconclusive retry, `marks_present` hop, critic-as-subagent, `quality=` /
  `rasteriser=` wiring). Dated errata in place, listed under *What this amends*.
- **Leaves open:** the python widening ([#176](https://github.com/thearcscode/chartagent/issues/176));
  harness + `history=` / VFS + skills ([#177](https://github.com/thearcscode/chartagent/issues/177));
  Tier-3; the reference `Rasteriser`’s default size and scale.
  *The eval benchmark was settled by
  [ADR-0029](0029-the-eval-benchmark-is-a-frozen-150.md) on 2026-09-20.
  What `fast`/`balanced`/`best` cost and take in wall-clock was settled by
  [ADR-0028](0028-quality-dials-cost-and-latency-targets.md) on 2026-09-20.
  `generate_recipe`’s prompts and first `ChartDocument`
  ([#175](https://github.com/thearcscode/chartagent/issues/175) — minted with this ADR)
  were settled by [ADR-0030](0030-generate-recipe-is-one-seam-a-resolver-and-two-prompts.md)
  on 2026-09-23, which also scopes `budget_exhausted`’s `marks_present` exemption to Flint
  only — custom rail's is repairable. The repair counts (`fast=0`/`balanced=1`/`best=2`), the
  wiring, and “fast never escalates” stay **closed here** and must not be reopened.*

## Context

ADR-0013 Decision 6 kept a failed deterministic review on its rail, with one exception: a
review failure that *escalates* onto the custom rail scores custom. ADR-0016 Decision 3 gave
that exception **bucket 4**. Neither said **when** the gate writes it. ADR-0026 named a Flint
`marks_present` fail as the signal, set report-only as budget 0, forbade vacuous passes, and
left counts, inconclusive retry, the hop, the critic wrap, and `quality=` / `rasteriser=`
wiring to this ticket.

The map’s 2026-09-15 note directed P2’s agentic work at `deepagents` or a named alternative.
LangChain’s own docs, read 2026-09-19 via the Docs MCP — [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview),
[Multimodal](https://docs.langchain.com/oss/python/deepagents/multimodal),
[Subagents](https://docs.langchain.com/oss/python/deepagents/subagents),
[Runtimes / frameworks / harnesses](https://docs.langchain.com/oss/python/concepts/products)
— describe a **harness** for autonomous, non-deterministic tasks. Summarisation **drops image
blocks** from older turns; subagents are the recommended quarantine for image-heavy work, and
are the wrong tool for a simple single-step call. The loop this ticket owns is the opposite:
host-owned, bounded, typed generate → critique → revise, with the gate owning when to hop.

ADR-0017 already took the python sandbox off the P2 path. Putting `SandboxBackend` under this
orchestrator would re-import it.

## Decision

### 1. The review loop is host-owned Python on the pydantic-ai client

`create_chart` runs profile → planner steps → bind → Tier 1 → optional `critique()` →
bounded review repair → maybe bucket 4. The critic stays the ADR-0026 leaf
`critique(png, context) -> Critique` — a plain call, not a subagent. Deepagents and
`SandboxBackend` are **not** under this orchestrator.

This is **sequencing, not a cut.** The library is not complete without the python widening
(ADR-0015) and a harness for custom-rail codegen, skills, and `history=` / VFS. Those stay
**in-scope P2**, minted as [#175](https://github.com/thearcscode/chartagent/issues/175),
[#176](https://github.com/thearcscode/chartagent/issues/176),
[#177](https://github.com/thearcscode/chartagent/issues/177). They do not block
[#169](https://github.com/thearcscode/chartagent/issues/169)–[#170](https://github.com/thearcscode/chartagent/issues/170).
They are not P3 and not out of scope.

The 2026-09-15 direction survives on **#177**, not on this loop.

### 2. Bucket 4 fires only on a Flint `marks_present` fail, and only at `balanced` / `best`

Chrome-without-marks is the delivery hole a `chartProperties` edit cannot fix. A blank
`painted` fail **stays on-rail** (fail-closed). Do not reopen ADR-0024’s block rule: `painted`
still blocks Tier 2, so a blank canvas never reaches `marks_present`, and that is accepted.

`quality="fast"` **never escalates.** It skips presentational revises; it does not buy
codegen. Return the Flint chart with `passed=False`.

`injection_pattern` **never escalates.** Sending an injection fail onto a rail that writes
JavaScript is a worse boundary.

Exhausted presentational repairs stay on-rail, best-so-far, `passed=False`. Rail share is not
a function of the VLM (ADR-0013 Decision 6’s exception stays the exception).

### 3. Review-repair is a separate budget: `fast=0`, `balanced=1`, `best=2`

Same counts on both rails. One review repair is one extra step-2 call (Flint) or one
patch-prompt call (custom). Do not fold this into ADR-0019’s emit cap (1 / 2 / 5). A Flint
`marks_present` fail consumes **zero** review repairs.

`colorblind_safe_palette` spends this budget (success unblocks Tier 2). `data_truthfulness`
spends it via the custom patch prompt. `injection_pattern` does not — fail-closed, taint is
in the data. Never raise a review fail; return best-so-far.

A `balanced` call that spends its 1 on colourblind, then hits `marks_present`, still hops
(the trigger consumes none) but the recipe inherits **0** leftover patches.

### 4. Inconclusive Tier 2 does not re-call the critic

Fail-closed. `budget_exhausted` stays false. Vacuity is already `passed=False` (ADR-0026
Decision 5). A retry is how an abstaining critic burns the dial.

### 5. `budget_exhausted` is true iff a repairable fail was present and remaining budget was 0

Including every repairable fail at `fast`. False for `marks_present` and for an inconclusive
Tier 2. [#169](https://github.com/thearcscode/chartagent/issues/169) must not redefine this
bit.

**Erratum — 2026-09-24 ([#175](https://github.com/thearcscode/chartagent/issues/175),
[ADR-0030](0030-generate-recipe-is-one-seam-a-resolver-and-two-prompts.md)).** "False for
`marks_present`" is Flint-scoped: a Flint `marks_present` fail is unrepairable (the hop
signal) and does not set `budget_exhausted`. On custom rail `marks_present` is repairable,
so remaining budget 0 sets `budget_exhausted=true`, `passed=False`, no patch attempted —
the general repairable-fail rule. Inconclusive Tier 2 is unchanged (stays false).

### 6. After the trigger: `generate_recipe(...)`, carry-over, remaining budget, no second hop

This ADR **names** the seam; [#175](https://github.com/thearcscode/chartagent/issues/175)
implements it. Internal — not in `__all__`, not a factory kwarg. Callers are this
orchestrator (bucket 4) and, later, the planner-miss path. Embedders do not swap it.

Carry the failed frame’s `transform`, `source_schema`, `theme_spec`. Do not re-run step 1.
Codegen writes only `ChartDocument`. The recipe re-enters **this same** review loop and
**cannot escalate again**. Remaining `quality=` repair budget carries over — no fresh
budget, no unreviewed recipe.

This ADR owns **bucket 4 only.** Planner buckets 1–3 still raise `InexpressibleRequestError`
until #175 implements `generate_recipe` and wires those buckets. Until #175 ships,
`marks_present` at `balanced`/`best` **fail-closes on-rail like `fast`** (`passed=False`, no
hop, no new error).

**Erratum — 2026-09-23 ([#175](https://github.com/thearcscode/chartagent/issues/175),
[ADR-0030](0030-generate-recipe-is-one-seam-a-resolver-and-two-prompts.md)).** `generate_recipe`
is implemented and both callers are wired: the hop above, and a planner miss (bucket 1 or 2)
at `balanced`/`best`, which now calls the same seam instead of raising. The fail-closed
stand-in in this Decision is retired as the default path — it is now only what a *terminal*
`generate_recipe` failure (codegen or library resolution exhausted) falls back to, on either
caller. `fast` is unchanged: a well-formed inexpressible verdict still raises there, and
`generate_recipe` is unreachable from either caller at `fast`.

**Erratum — 2026-09-26 ([#186](https://github.com/thearcscode/chartagent/issues/186),
[ADR-0030](0030-generate-recipe-is-one-seam-a-resolver-and-two-prompts.md)).** "Codegen
writes only `ChartDocument`" means the model does not write a `ChartRecipe`. The seam
returns an internal `GeneratedRecipe` (`document`, `transform`, `semantic_types`,
`source_schema`); the caller still assembles the recipe. ADR-0030 Decision 1's erratum
is the statement.

### 7. Best-so-far is the last `passed=True` snapshot, else the first emit of the current rail

After a hop, “first emit” is the first recipe. Not last-attempt (a repair can worsen the
chart). Not a fail-count scorer.

### 8. Factory vs per-call wiring

```python
def create_chart_agent(
    *,
    model: str,
    rasteriser: Rasteriser | None = None,
    critique_model: str | None = None,
    quality: Literal["fast", "balanced", "best"] = "balanced",
) -> ChartAgent: ...

class ChartAgent:
    def create_chart(
        self,
        data: DataSource,
        instruction: str,
        *,
        quality: Literal["fast", "balanced", "best"] | None = None,
    ) -> ChartResult: ...
```

`rasteriser=` and `critique_model=` are factory-only and construction-checked (ADR-0026
Decision 9 stands: unset critic → Tier 2 `unavailable`; asked but uninstalled → raise).
`quality=` is per request; the factory default is `balanced`; a missing per-call value uses
the factory default. Keep the three names. No `sandbox=`, no `generate_recipe=`.

### 9. One `ChartResult`, XOR payload, `review` from `create_chart` only

```python
class ChartResult:
    review: ReviewReport | None
    envelope: Envelope | None
    recipe: ChartRecipe | None
    def refresh(self, data: DataSource) -> ChartResult: ...
```

Exactly one of `envelope` / `recipe` is set. No `kind` field — the payload is the
discriminator. Do not flatten either type onto `ChartResult`. `review` is the report for
**the returned artifact**, not a log of the abandoned Flint attempt. Tests that constructed
`ChartResult(envelope=…)` grow `review=`.

`create_chart` always sets `review` (Tier 1 always runs). `refresh` re-binds only
(`bind` or `bind_recipe`) and sets `review=None`. Do not copy a stale report, do not fake
Tier 1, do not forbid refresh. Callers who want a gate run `create_chart` again.

**Erratum — 2026-09-26 ([#189](https://github.com/thearcscode/chartagent/issues/189)).**
`ChartResult` gains `bound: BoundRecipe | None`. A `ChartRecipe` stores no rows, so a
recipe refresh has nowhere else to put them; an envelope refresh's rows stay inside the
new envelope, and `bound` is `None` on an envelope result. `bound` set without a `recipe`
is impossible. `BoundRecipe` still has no wire format (ADR-0018 Decision 5). An envelope
result serialises through `.envelope.to_dict()`; a recipe result has no envelope, and
`ChartResult` itself still never goes on the wire.

### 10. Light-mode is not this loop

Gate repairs stay full re-review (ADR-0026 Decision 6: Tier 1, then a fresh critique).
Changed-checks-only patch review is the history/patch surface on
[#177](https://github.com/thearcscode/chartagent/issues/177).

## What this amends

- **ADR-0020 Decisions 1, 2 and 5** — Decision 1’s factory grows `rasteriser=` /
  `critique_model=` / `quality=`; `history=` stays absent until [#177](https://github.com/thearcscode/chartagent/issues/177).
  Decision 2: `ChartResult` is no longer envelope-only — XOR `Envelope` | `ChartRecipe`, plus
  `review` from `create_chart`. Decision 5’s “`quality` does not exist at P1” stands for P1;
  P2 adds it as Decision 8 here, not as a reserved no-op that silently did nothing.
- **ADR-0024 *Leaves open*** — Tier-1 escalation policy is this ADR. `injection_pattern`
  never hops; `painted` fail-closes; `colorblind_safe_palette` spends the review-repair
  budget then fail-closes.
- **ADR-0025 *Leaves open*** — `data_truthfulness: fail` does not hop (already custom rail);
  it spends the review-repair budget via the patch prompt, then fail-closes.
- **ADR-0026 *Leaves open*** — repair counts, inconclusive retry, the `marks_present` hop,
  critic-as-subagent, and `quality=` / `rasteriser=` / `critique_model=` wiring are closed
  here. The critic stays the leaf call (the option ADR-0026 Decision 8 kept open).
- **PRD pillar 4 / §7.8** — `quality=` moves onto `create_chart` with a factory default;
  `fast` is 0 repairs and never codegen. Light mode stays §7.7 patch-mode, not the gate
  loop.

## Consequences

- **Bucket 4 is rare on purpose.** A stricter VLM does not move rail share except on
  chrome-without-marks at `balanced`/`best`.
- **`fast` caps the worst case: one critic call, no hop, no patch. Typical inference cost matches `balanced` on a first-round pass.**

  **Erratum — 2026-09-20 ([#169](https://github.com/thearcscode/chartagent/issues/169),
  [ADR-0028](0028-quality-dials-cost-and-latency-targets.md)).** Replaces “`fast` is
  actually cheap.” True as a cap; false as typical cost.
- **`ChartResult.review` is optional on the type** so `refresh` can say *we did not look*
  without minting a skip report.
- **`generate_recipe` is unbuildable until #175.** The hop is specified; the fail-closed
  stand-in keeps `create_chart` returning a Flint `ChartResult` until the seam exists.

  **Settled — 2026-09-23 ([#175](https://github.com/thearcscode/chartagent/issues/175),
  [ADR-0030](0030-generate-recipe-is-one-seam-a-resolver-and-two-prompts.md)).** Built. The
  stand-in is now the terminal-failure fallback, not the default.
- **Core stays LLM-free.** pydantic-ai remains the vendor extra. No deepagents in the base
  wheel from this ticket.

## Alternatives rejected

- **Escalate every exhausted review** — Decision 2. Makes rail share a function of the VLM
  and of `quality=`.
- **Escalate `painted` / `injection_pattern`** — Decision 2. Blank canvas is usually
  raster/assemble, not “Flint cannot draw this”; injection onto generated JS is a worse
  boundary.
- **`fast` still hops on `marks_present`** — Decision 2. The cheap dial would buy codegen.
- **Fold review repairs into the 1/2/5 emit cap** — Decision 3. Different lever.
- **Raise a review fail** — Decision 3. PRD P0.7 returns best-so-far.
- **Retry an inconclusive critic** — Decision 4.
- **Fresh `quality=` budget after the hop** — Decision 6. `balanced` would become `best`.
- **Unreviewed recipe** — Decision 6. Hides bucket-4 quality from the gate’s own numbers.
- **This ADR also switches planner 1–3 to `generate_recipe`** — Decision 6. Do not erratum
  ADR-0019’s raise from a gate ticket.
- **deepagents (or LangGraph) as this orchestrator** — Decision 1. Wrong abstraction for a
  host-owned loop; image history is a documented footgun.
- **`generate_recipe=` factory callback, or public `__all__`** — Decision 6. Codegen is our
  prompt surface.
- **Two result types, or both envelope and recipe after a hop** — Decision 9. One caller
  story; the abandoned frame is not a revision (ADR-0018 Decision 10).
- **Copy `review` through `refresh`** — Decision 9. A stale pass.
- **Specify light-mode changed-checks here** — Decision 10. That is conversational patch.

## What this feeds

- **[#169](https://github.com/thearcscode/chartagent/issues/169) /
  [ADR-0028](0028-quality-dials-cost-and-latency-targets.md)** — cost and latency
  targets, settled. Counts, wiring, `budget_exhausted`, and “fast never escalates”
  stay closed here.
- **[#170](https://github.com/thearcscode/chartagent/issues/170) /
  [ADR-0029](0029-the-eval-benchmark-is-a-frozen-150.md)** inherits `balanced` as
  0-or-1 review repair plus a possible hop only on Flint `marks_present`.
  **Settled — 2026-09-20.**
- **[#175](https://github.com/thearcscode/chartagent/issues/175)** inherits `generate_recipe`,
  the patch prompt, carry-over fields, and the planner-miss (buckets 1–3) wiring.
  **Settled — 2026-09-23 ([ADR-0030](0030-generate-recipe-is-one-seam-a-resolver-and-two-prompts.md)).**
- **[#176](https://github.com/thearcscode/chartagent/issues/176)** inherits ADR-0015 as the
  contract, still not the P2 web rail.
- **[#177](https://github.com/thearcscode/chartagent/issues/177)** inherits the 2026-09-15
  harness direction, `history=` / VFS, skills, and light-mode patch review.
- **Studio** inherits `ChartResult` as envelope-XOR-recipe plus `review`, and `refresh`
  clearing `review`.

## Evidence

- **LangChain Docs MCP, read 2026-09-19:** deepagents
  [overview](https://docs.langchain.com/oss/python/deepagents/overview) (harness vs
  `create_agent` / LangGraph); [multimodal](https://docs.langchain.com/oss/python/deepagents/multimodal)
  (summarisation drops image blocks; subagents advised for image-heavy inspection;
  references over base64); [subagents](https://docs.langchain.com/oss/python/deepagents/subagents)
  (`response_format` since `>=0.5.3`; do not use subagents for simple single-step tasks);
  [products](https://docs.langchain.com/oss/python/concepts/products) (harness = autonomous /
  non-deterministic; runtime = mixing deterministic and agentic steps).
- **pydantic-ai** remains the planner client (ADR-0022 Decision 9; extras
  `pydantic-ai-slim[anthropic]` / `[openai]`).

## Related

- [#168](https://github.com/thearcscode/chartagent/issues/168) — the grilling this settles.
- ADR-0013, ADR-0016, ADR-0018, ADR-0020, ADR-0024, ADR-0025, ADR-0026,
  [ADR-0028](0028-quality-dials-cost-and-latency-targets.md),
  [ADR-0029](0029-the-eval-benchmark-is-a-frozen-150.md).
- `CONTEXT.md` gains **Escalation**, **Review repair**, **Quality**, and rewrites **Chart
  agent** and **Chart result**.
