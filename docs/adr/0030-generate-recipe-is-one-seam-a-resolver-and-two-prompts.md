# 30. `generate_recipe` is one seam, a private resolver, and two document prompts

- **Status:** Accepted
- **Date:** 2026-09-23
- **Settled on:** [#175](https://github.com/thearcscode/chartagent/issues/175)
- **Builds on:** ADR-0008 (the transform menu; `raw_sql` as the menu's own escape valve),
  ADR-0016 Decisions 12–13 (the rail owns both prompt shapes as one competence; one
  delimited-block renderer, consumed and not built), ADR-0017 (the interactive web document;
  `render`/`getPlottedSeries`; `ChartDocument`/`BoundDocument`; `LibraryPin` carries no bytes;
  library choice is open, no allowlist; the prompt states a constraint rather than discovering
  it by failing), ADR-0018 (`ChartRecipe`; `bind_recipe`; `escape_reason` required and carried
  forward; recipes share one `transform`/`source_schema` grammar with the frame), ADR-0019
  (two planner calls; `InexpressibleRequestError{bucket: 1 | 2}`; the 1/2/5 emit cap scoped to
  step 1/step 2 only; a repair carries the rejected emit and the checker error), ADR-0022 (the
  nonce-fenced prompt renderer; `ModelClient`; no `sample_rows` at step 2), ADR-0023 (the
  `Attempt`/`AttemptObserver` private-seam convention `ChartAgent._attempt_observer`
  establishes), ADR-0024 (`CheckResult`; Tier 1's four checks; `colorblind_safe_palette` and
  `data_truthfulness` as custom-rail-applicable), ADR-0025 (`data_truthfulness`'s failure
  detail — the mismatched point, column or consumed row), ADR-0026 Decision 6 (a Tier-2 fail is
  repairable input; on custom rail *every failing item* may repair through the rail's own patch
  prompt; the payload is failing names plus a host-authored static hint, never critic free
  text, no PNG to the planner), ADR-0027 (the host-owned review loop; bucket 4 fires only on a
  Flint `marks_present` fail at `balanced`/`best`; review-repair is `fast=0`/`balanced=1`/
  `best=2`, separate from the emit cap; `generate_recipe` named as an internal seam; carry-over
  of `transform`/`source_schema`/`theme_spec`; no second hop; `ChartResult` XOR `envelope`/
  `recipe`), ADR-0028 (the `$0.05` per-request cost accounting every model call feeds),
  ADR-0029 Decision 8 (cell-1's era-conditional reading — pre-`#175` a raise, post-`#175` an
  expected custom-rail executable hit)
- **Amends:** ADR-0026 Decision 6 (custom-rail `marks_present` carries no Flint-style
  unrepairable/round-suppressing carve-out; one patch-prompt call per round names every
  repairable failure in that round); ADR-0027 Decisions 2, 5, 6 and *Leaves open* (`#175` is
  discharged; `budget_exhausted`'s Flint-only scoping for `marks_present` is made explicit);
  `CONTEXT.md`'s **Escalation**, **Escape reason** and **Review repair** entries. Dated errata
  in place, listed under *What this amends*.
- **Leaves open:** the exact prose of the prompt templates beyond what Decision 3 and Decision
  4 fix as content rules (wording is an implementation choice, not an architectural one); how an
  embedder installs `ChartAgent._library_resolver` and whether it caches across requests
  (implementation detail, not this ADR's); Studio's own save-time library handling, which is a
  separate repo and was never this library's to decide; the python widening
  ([#176](https://github.com/thearcscode/chartagent/issues/176)); the harness, `history=`/VFS,
  skills and light-mode patch review
  ([#177](https://github.com/thearcscode/chartagent/issues/177)).

## Context

ADR-0027 named `generate_recipe(...)` as the seam bucket 4's hop calls and left it
unbuildable — "the fail-closed stand-in keeps `create_chart` returning a Flint `ChartResult`
until the seam exists" — and explicitly refused to also switch planner buckets 1–3 off
`InexpressibleRequestError`, leaving that wiring to this ticket too. Both callers, the
first-generation prompt, the patch prompt, and the first `ChartDocument`'s shape were minted
here as [#175](https://github.com/thearcscode/chartagent/issues/175).

Three things were found by reading rather than argued, and each shaped a decision.

**`LibraryPin` needs a hash chartagent cannot compute.** ADR-0017 Decision 8 freezes
`LibraryPin(name, version, sha256)` with `sha256` required, and Decision 10 assigns resolving
a name to a hash-and-bytes pair to "Studio's server," through "one pinned registry," because
Decision 12 forbids the library from ever fetching. But `generate_recipe` runs in-process, and
under ADR-0027 Decision 6 the hopped recipe "re-enters this same review loop" *before*
`create_chart` returns — so painting it for Tier 1/Tier 2 needs resolved library bytes before
any external caller (Studio or otherwise) has had a chance to resolve anything. Nothing in
ADR-0017 or ADR-0018 says who does that resolving when the caller is chartagent's own review
loop, not Studio's save flow.

**Bucket 2 needs a transform the 8-slot menu was just declared unable to express.** A recipe
requires `transform` (ADR-0018 Decision 2). For the bucket-4 hop this is free — the failed
Flint frame already had one. For a planner-miss recipe, step 1 returned `Inexpressible`, not a
`Fragment`: no transform was ever decided, and bucket 2's own definition is "the transform menu
cannot express the shape" (ADR-0016 Decision 3). Asking the model to fill the same closed
8-slot grammar that just failed would be circular for exactly the requests bucket 2 names.

**ADR-0026 Decision 6 already answered a question this ticket almost re-litigated.** A first
read of `CONTEXT.md`'s *Review repair* entry — "`colorblind_safe_palette` and
`data_truthfulness` spend this budget" — suggests the patch prompt's job is those two Tier-1
checks alone. But that sentence never mentions Tier 2, and ADR-0026 Decision 6 says plainly,
for the custom rail: "every failing item may repair, through the rail's own patch prompt...
under the same payload rule." The patch prompt's scope is therefore every repairable
`CheckResult` name on that rail, not two.

## Decision

### 1. One seam, two calling shapes; the caller decides whether `transform` is asked for

```python
def generate_recipe(
    profile: Profile,
    instruction: str,
    escape_reason: EscapeReason,
    *,
    transform: Transform | None,
    resolver: LibraryResolver | None,
    invoke: Any,
) -> ChartDocument: ...
```

`transform=None` means *author it* — the miss path. A supplied `transform` means *carry it
over, do not re-ask* — the hop path, matching ADR-0027 Decision 6's "do not re-run step 1"
exactly, one layer down: `generate_recipe` does not re-derive what it was handed.
`escape_reason` is already in the caller's hand before the call (`4` for the hop; the raised
`bucket` for a miss) and is threaded through only to shape the prompt (Decision 3) — it is
never returned or re-derived here. `generate_recipe` returns a `ChartDocument` only, per
ADR-0027 Decision 6 ("codegen writes only `ChartDocument`"); the caller assembles the
`ChartRecipe` from `escape_reason`, `transform` (supplied or freshly authored),
`source_schema` (Decision 2), and `theme_spec` (carried on the hop; on a miss, whatever the
caller passed to `create_chart`, or absent — the same "caller, or omitted" rule the frame path
already has). Internal, not `__all__`, not a factory kwarg — unchanged from ADR-0027 Decision
6.

### 2. `source_schema` stays code's, not a third model field

Exactly ADR-0019 Decision 2's existing rule: `source_schema` is computed from the transform's
source columns against the profile, by code, whether `transform` was supplied or just authored
in this call. A model that fills the baseline it will later be checked against can paper over
the mismatch it exists to catch — the same argument, unweakened by moving rails.

### 3. Bucket 2 leans on `raw_sql` — the menu's own escape valve, not a new one

When `generate_recipe` authors `transform` for a bucket-2 miss, the prompt's framing states
plainly that the request already failed the 8-slot menu and that `raw_sql` (ADR-0008 —
"eight slots... or `raw_sql` alone") is available precisely for a shape the slots cannot state.
Nothing new is minted: `raw_sql`'s three locks (ADR-0008) apply unchanged, and a bucket-2
recipe's transform is expected to *use* raw_sql more often than a Flint frame's, not to strain
the same eight slots a second time. Bucket 1 ("no chart type in the 48") carries no such
expectation — the menu may already be sufficient there; only the chart type was the problem.

### 4. Prompt context: column names and `semantic_types`, never literal row values

The first-generation and patch prompts render through ADR-0022's existing nonce-fenced,
delimited-block machinery — the same renderer, not a second one (ADR-0016 Decision 13) — and
carry the profile's column names and `semantic_types` (real, from the carried-over `Fragment`
on a hop; model-authored fresh on a miss, per the existing rule that `semantic_types` is never
copied from the profile, ADR-0019 Decision 2). **They never carry `sample_rows` or any other
literal cell value.** Step 2 already withholds `sample_rows` from a prompt that emits typed
`chartProperties`; a prompt that emits *executable JavaScript text* is a strictly sharper case
for the same restraint — an attacker-influenced cell value landing in a codegen prompt is a
narrower injection surface to close than the one ADR-0022 already closed for step 2. The module
reads `data[i].column_name` at paint time; it never needed a sample value to write that
reference, only the name.

The hop's prompt additionally states why the chart is being escaped — chrome painted, marks did
not — as host-authored context, the same trust class as the rest of the system prompt; a
miss's prompt states the bucket. Neither is untrusted content and neither goes through the
delimited-block fence.

### 5. Two structured-output types, not one, and the patch prompt always uses the narrower one

```python
class LibraryRequest:      # internal, not __all__ — the model's decode target
    name: str
    version: str

class DocumentDraft:       # internal — first emit on the hop; every patch, either caller
    module: str
    styles: str | None
    libraries: tuple[LibraryRequest, ...]

class RecipeDraft:         # internal — first emit on a miss only
    transform: Transform
    document: DocumentDraft
```

The model never decodes into `LibraryPin` — it does not know a hash. `DocumentDraft` is the
shared shape both prompts resend in full: the hop's first-generation call and *both* callers'
patch calls all use it. Only the miss path's first-generation call widens to `RecipeDraft`,
because only there is `transform` still undecided (Decision 1). This is the same "one seam, two
calling shapes" idea from Decision 1, expressed at the type level rather than invented twice.

**Full resend, never a diff, on both prompts.** PRD language about "targeted code edits, not
rewrite" describes how ADR-0018 Decision 9's review UI diffs two *stored* versions as text
after the fact — it is not a promise about what the model emits. A model-authored line/hunk
diff against code it did not itself just re-derive is an unreliable format; a full string field
is what structured output validates cleanly, and the readable-diff promise is kept by computing
one from two full versions, never by asking for one.

### 6. Library identity: a private resolver, called synchronously, bytes never on the wire types

```python
LibraryResolver = Callable[[str, str], tuple[str, bytes]]  # (name, version) -> (sha256, bytes)
```

`ChartAgent._library_resolver: LibraryResolver | None`, unset by default — the exact
private-seam convention `ChartAgent._attempt_observer` already establishes (ADR-0023 Decision
8): not `__all__`, not a `create_chart_agent` factory kwarg (ADR-0027 Decision 8's "keep the
three names" stands unweakened — this is not a fourth public kwarg, it is a private attribute
an embedder that owns both ends, like Studio, may set), and left unset behaviour is unchanged
from before this ADR.

`generate_recipe` resolves every `LibraryRequest` the model emitted **synchronously, before
returning**, and constructs real `LibraryPin`s from the result. Nothing that leaves
`generate_recipe` — either caller, `ChartResult`, a later repair round — is ever an unresolved
pin. `libraries=()` (from scratch) makes zero resolver calls, unchanged as a first-class
outcome (ADR-0017 Decision 4). Chartagent still never fetches: it calls a function it was
handed, exactly as `rasteriser=` and `critique_model=` are caller-supplied clients that reach
a network chartagent itself does not touch.

**The resolver returns bytes, but bytes never appear on `ChartDocument`, `ChartRecipe` or
`ChartResult`.** `LibraryPin` stays exactly as ADR-0017 Decision 8 froze it — identity only,
no bytes — because painting *inside this request's own review loop* needs the bytes now: a
hopped recipe re-enters Tier 1/Tier 2 before `create_chart` returns (ADR-0027 Decision 6), and
that requires composing a `BoundDocument` and calling `build_shell(document, libraries=<bytes
map>)` (ADR-0017 Decisions 6, 11–12) to rasterise it. The orchestrator therefore keeps the
resolved `Mapping[sha256, bytes]` as an in-request, internal hand-off alongside the
`ChartDocument` it painted from — never serialised onto a public type, never returned to the
caller. A persisted recipe's library bytes are resolved again, later, by whoever paints it next
(Studio, at its own authoring or render time, per ADR-0017 Decision 10) — this ADR does not
change that a stored `LibraryPin` carries identity only and nothing here widens what crosses
into `spec_revisions`.

**Best-so-far keeps its bytes.** ADR-0027 Decision 7's best-so-far snapshot is a `(ChartRecipe,
bytes-map)` pair internally, not a bare recipe, so a later patch that fails — on decode (Decision
13) or on resolution (Decision 8, Decision 14) — can still fall back to *rasterising* the prior
good recipe, not only returning it unpainted.

### 7. Resolver unset: the prompt says so; the model is never left to discover it by failing

ADR-0016 Decision 2's rule for this exact shape of problem already applies: "the prompt states
the constraint; it is not discovered by failing." When `ChartAgent._library_resolver` is unset,
both prompts — first-generation and patch — omit the "name a package" option and state flatly
that only `libraries=()` is legal this run. This is the primary mechanism. As a backstop, a
model that names a library anyway is a decode failure: on first-generation it consumes the one
retry Decision 9 grants; on a patch it has no retry to consume (Decision 13) and simply fails
that repair round, the same as any other malformed patch response. Neither is a new failure
class, and neither is evidence the constraint should have been discovered through it.

### 8. Two different terminal endings for resolver failure — first-generation versus patch

Resolution failing (registry error, unknown version, timeout) is not something a second model
call fixes — the model has no visibility into *why* a lookup failed and cannot meaningfully
choose differently, the same reasoning Decision 7 already applies to a discoverable-in-advance
constraint, one layer later.

- **First-generation call**: resolver failure terminates the whole `generate_recipe` call —
  the same terminal fallback as an exhausted decode (Decision 9): on the hop, the Flint
  `ChartResult` returns with `passed=False` and no recipe; on a miss,
  `InexpressibleRequestError(bucket=...)` raises, as before this ADR.
- **Patch call**: resolver failure discards *only that patch*. Best-so-far — the last
  `passed=True` snapshot, else the first emit of the current rail (ADR-0027 Decision 7) — is
  kept, paintable, via Decision 6's retained bytes. The round's outcome is budget spent,
  `passed=False`, exactly like any other failed repair (Decision 12). These two endings are
  not the same shape and must not be collapsed into one.

### 9. Call-budget: a third, small line, disjoint from the emit cap and the review-repair dial

`generate_recipe`'s own decode-retry budget is **1**, matching step 1's count rather than step
2's — a malformed first emit here is a re-judgement, the same character as a bad step-1
fragment, not a narrow key fix. This budget is its own line: it is charged to neither
ADR-0019's 1/2/5 emit cap (scoped there to step 1/step 2 only) nor ADR-0027's `fast=0`/
`balanced=1`/`best=2` review-repair dial (scoped to *post-review* patches). Every call
`generate_recipe` makes — the first ask, its one retry, and any later patch call — still counts
on ADR-0028's `$0.05` per-request invoice regardless of which budget line it belongs to.

**The hop's first call is free of review-repair budget**, unchanged from ADR-0027 Decision 3
("a Flint `marks_present` fail consumes zero review repairs") — only a *subsequent* patch, once
the recipe has re-entered the loop and failed something there, spends the dial.

**The miss path's first call is uncounted against ADR-0019's 5-call cap.** It replaces a raise
rather than extending step 1/step 2's judgement loop — the same treatment the hop's free first
call already gets, restated for the other caller.

### 10. `quality="fast"` never reaches `generate_recipe`, from either caller

`CONTEXT.md`'s `Quality` entry already states this rail-agnostically: "`fast`... never buys
codegen." ADR-0027 Decision 2 only spelled it out for the hop, because the miss path's wiring
didn't exist yet. `quality` is available on `create_chart` from the start of the call (ADR-0027
Decision 8), so the miss path's check is the same shape: at `fast`, a well-formed inexpressible
verdict still raises `InexpressibleRequestError` exactly as it did before this ADR;
`generate_recipe` is reachable from either caller only at `balanced`/`best`. One rule, not two
rules that happen to agree.

### 11. The patch prompt's triggers are every repairable custom-rail name, not two

ADR-0026 Decision 6 already settled this for the custom rail: "every failing item may repair."
Read narrowly against `CONTEXT.md`'s *Review repair* entry, which only names
`colorblind_safe_palette` and `data_truthfulness` because that sentence was scoped to Tier 1,
this looks smaller than it is. It is not. On custom rail the patch prompt's possible triggers
are:

| check | tier | repairable on custom rail |
| --- | --- | --- |
| `injection_pattern` | 1 | never — fail-closed, taint is in the data |
| `colorblind_safe_palette` | 1 | yes |
| `data_truthfulness` | 1 | yes |
| `marks_present` | 2 | yes — **no Flint-style carve-out** (Decision 12) |
| `axis_labels_present`, `legend_presence`, `label_overlap`, `bar_chart_y_axis_baseline` | 2 | yes |

**One patch-prompt call per repair round, carrying every failing name from that round**, not
one call per name — this is what keeps ADR-0027 Decision 3's "one review repair is one...
patch-prompt call" literally true when several items fail together, mirroring how a single
Flint step-2 repair already handles several presentational items in one re-ask. The payload
stays exactly ADR-0026 Decision 6's rule: the failing check names plus a host-authored static
hint per name, in the trust class of the system prompt — never the critic's free-text `note`,
never a PNG.

### 12. Custom-rail `marks_present` is a repairable name like the rest — this amends ADR-0026

ADR-0026 Decision 6 gives Flint's `marks_present` a specific carve-out: unrepairable, and it
"suppresses all repair that round." It does not restate that carve-out for custom rail, and
this ADR does not import it there. A code patch is a plausible fix for a rendering bug in a way
a `chartProperties` edit never was for Flint's chrome-without-marks — the whole reason the hop
exists is that Flint's failure mode has no code to patch. On custom rail, `marks_present` is
simply one more name in "every failing item may repair" (Decision 11); it does not suppress
repair of any other failing name in the same round, and the hop still cannot fire a second
time regardless (ADR-0027 Decision 6, untouched).

**`budget_exhausted`'s Flint-only scoping, made explicit.** ADR-0027 Decision 5 and ADR-0026
Decision 6 both say `budget_exhausted` stays false for `marks_present`. That was written for
Flint, where the check is categorically unrepairable and "not attempted" is the right reading.
On custom rail, `marks_present` is repairable (this Decision) — so a custom-rail `marks_present`
fail with remaining budget `0` is a repairable fail with no budget left, and
`budget_exhausted=true`, `passed=False`, no patch attempted, exactly as any other exhausted
custom-rail repair. `CONTEXT.md`'s *Review repair* entry — "a Flint `marks_present` fail
consumes none" — is corrected to name Flint explicitly; on custom rail `marks_present` spends
like any other repairable name.

### 13. The patch prompt is a single ask — no internal retry

ADR-0027 Decision 3's "one patch-prompt call" is literal: zero internal decode-retry. A
malformed patch response simply fails that repair round outright — consumes the budget,
contributes to `passed=False` via Decision 12's `budget_exhausted` rule — the same posture a
`marks_present` fail on Flint already has (consumes nothing further, buys nothing further).
Giving the patch call its own retry ladder would reopen the "different budget for different
faults" reasoning ADR-0019 Decision 6 used to size step 1 and step 2 differently, for a call
ADR-0027 explicitly sized as one shot.

### 14. Library resolution on a patch is the same step, applied again, under the same terminal rule

A patch resend's `libraries` field is resolved by the identical mechanism as a first
generation's (Decision 6) — no second code path, because both prompts decode into the same
`DocumentDraft` (Decision 5). A patch that changes, repeats, or drops the library list
re-resolves whatever it names. Resolver failure on a patch does not get a second ask (Decision
13); it takes Decision 8's *patch* ending — discard the patch, keep best-so-far — never
Decision 8's *first-generation* ending. In-request resolver caching across repeated
(name, version) pairs within one call is an implementation choice, not decided here.

### 15. The first emit is always a fully resolved, storable `ChartDocument`

Nothing `generate_recipe` hands back — to either caller, on either prompt — is a draft with
unresolved pins or a placeholder `sha256`. `contract_version` is `1` (ADR-0017 Decision 16,
unchanged); `styles` is `None` when the model wrote none; `libraries=()` is legal and makes no
resolver calls (Decision 6). The two-symbol contract (`render(data, el)` /
`getPlottedSeries()`, CSS scoped to `el`, no `window`/`document` listeners) is stated by the
prompt exactly as ADR-0017 Decision 7 froze it — restated here, not reinvented.

## What this amends

- **ADR-0026 Decision 6** — custom-rail `marks_present` carries no Flint-style
  unrepairable/round-suppressing carve-out (Decision 12); one patch-prompt call per round names
  every failing check from that round, not one call per name (Decision 11).
- **ADR-0027 Decision 2** — "`fast` never buys codegen" is confirmed rail-agnostic:
  `generate_recipe` is unreachable from either caller at `fast` (Decision 10).
- **ADR-0027 Decision 5** — `budget_exhausted`'s "false for `marks_present`" is Flint-scoped;
  custom-rail `marks_present` follows the general repairable-fail rule (Decision 12).
- **ADR-0027 Decision 6 and *Leaves open*** — `generate_recipe` is implemented; both callers are
  wired. `#175` is **discharged**.
- **`CONTEXT.md`** — **Escalation** drops the "until `generate_recipe` exists" stand-in language
  now that it exists; **Escape reason** gains the P2 era, where a well-formed bucket 1/2/4 does
  construct a `ChartRecipe`; **Review repair** is corrected to scope "a... `marks_present` fail
  consumes none" to Flint (Decision 12).

## Consequences

- **The miss path finally produces charts instead of exceptions**, at `balanced`/`best`. `fast`
  is unchanged — a well-formed inexpressible request still raises there, on purpose.
- **A stored recipe never carries an unresolved library pin.** Resolution happens once, inside
  `generate_recipe`, before anything crosses a boundary — not deferred, not partial.
- **Custom-rail review repair is more capable than a narrow reading suggested.** Five Tier-2
  defects plus two Tier-1 checks can all spend the one patch-prompt call a round buys, which
  makes the custom rail's repair ceiling closer to Flint's than `CONTEXT.md`'s prior wording
  implied.
- **Three independent budget lines now exist per request**: the planner's 1/2/5 emit cap, the
  review-repair dial (`fast=0`/`balanced=1`/`best=2`), and `generate_recipe`'s own 1-retry decode
  budget — disjoint on purpose, each sized for a different kind of fault.
- **A private, unset-by-default resolver is now load-bearing for any embedder that wants
  library choice to actually work.** Left unset, the custom rail is honestly narrower — from
  scratch only — and says so in the prompt rather than failing silently.

## Alternatives rejected

- **A public `library_resolver=` factory kwarg on `create_chart_agent`** — Decision 6. ADR-0027
  Decision 8 fixed the factory at three names; a private seam on the established
  `_attempt_observer` convention needs no new public surface.
- **Relaxing `LibraryPin.sha256` to `str | None`** — Decision 6. Reopens a frozen ADR-0017 type
  for a problem a private resolver already solves without touching it.
- **`libraries=()` as the only legal P2 emit** — Decision 6. Contradicts ADR-0017 Decision 4's
  "a first-class outcome, not a fallback" read as a permanent ceiling rather than a default.
- **A separate preliminary call to decide `transform` before codegen, on the miss path** —
  Decision 1. Doubles the ask count for context the codegen call already needs.
- **A narrower, hand-authored transform schema for bucket-2 misses** — Decision 3. `raw_sql`
  already is that escape valve; a second one duplicates ADR-0008.
- **Sending sample rows to ground column names** — Decision 4. The module only ever needs keys,
  not values, and step 2's precedent already treats literal cell values as unnecessary risk for
  a much narrower prompt than this one.
- **A model-authored diff/patch format** — Decision 5. Unreliable against code the model did not
  itself just re-derive; the "targeted edit" promise is a display-time computation, not an
  emission format.
- **Retrying the patch prompt internally, or giving resolver failure a second model ask** —
  Decisions 8, 13. Neither fault is one the model can meaningfully improve by trying again.
- **Importing Flint's `marks_present` carve-out onto custom rail** — Decision 12. A code patch
  is a plausible fix for the exact failure the carve-out exists to say is not fixable on Flint.
- **One patch-prompt call per failing name** — Decision 11. Breaks "one review repair is one...
  patch-prompt call" the moment two items fail together.

## What this feeds

- **Studio** inherits the boundary at Decision 6: a persisted recipe's `LibraryPin`s carry
  identity only, and resolving them to bytes for its own save/render flow is unchanged from
  ADR-0017 Decision 10 — this ADR only settles resolution *inside chartagent's own review
  loop*.
- **The python widening** ([#176](https://github.com/thearcscode/chartagent/issues/176))
  inherits `generate_recipe`'s call-budget pattern (Decision 9) as a precedent for sizing its
  own codegen retries, unchanged in shape.
- **The harness / `history=` / skills / light-mode patch review**
  ([#177](https://github.com/thearcscode/chartagent/issues/177)) inherits the two-prompt split
  (Decision 5) as what a light-mode changed-checks-only review would diff.

## Related

- [#175](https://github.com/thearcscode/chartagent/issues/175) — the ticket this ADR settles.
- ADR-0016, ADR-0017, ADR-0018 — the custom rail, the interactive web document, the recipe.
- ADR-0019, ADR-0022 — the planner's two calls; the prompt renderer.
- ADR-0023 — the private-seam convention this ADR reuses for the library resolver.
- ADR-0024, ADR-0025, ADR-0026 — Tier 1; `data_truthfulness`; Tier 2 and its repair rule.
- ADR-0027, ADR-0028, ADR-0029 — the review loop; cost accounting; the eval benchmark's
  era-conditional reading of cell 1.
- `CONTEXT.md` amends **Escalation**, **Escape reason**, **Review repair**; gains
  **`generate_recipe`**.
