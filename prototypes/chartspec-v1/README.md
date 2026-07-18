# PROTOTYPE — ChartSpec v1 core grammar (issue #3)

**Throwaway.** Answers one question: *what is the concrete Pydantic shape of ChartSpec v1's core
grammar?* Nothing here is meant to be merged as-is — the validated decisions graduate into PRD §8
and the real package; this directory stays a primary source.

```
uv run prototypes/chartspec-v1/explore.py        # interactive menu
uv run prototypes/chartspec-v1/explore.py --all  # run all 14 cases
```

No install step — PEP 723 inline metadata, `uv` fetches pydantic.

Scope is the core grammar only. The transform block (#4) is an opaque `dict` stub, CapabilityProfile
(#9) appears only as the version-compat helper, and `profile.json` (#5) is a hand-written fake.

---

## Decisions to react to

| # | Decision | Rationale |
|---|---|---|
| **D1** | `mark` is a **discriminated union of objects**, not a bare enum. `pie` + `inner_radius_ratio > 0` **is** donut. | Marks have params that belong nowhere else (stacking, bin count, whisker rule, donut hole). A bare enum pushes them into `style`, which is how library-specific junk drawers start. |
| **D2** | **No `aggregate` on the channel** (unlike Vega-Lite). Encodings reference *output columns of the transform*. | Pushdown compiles the transform to the source's SQL and can't reach into encodings; zero-cost refresh (§7.7) re-runs the transform alone. Encoding-level aggregate forks that boundary. **Cost:** the planner must name derived columns (`revenue_sum`) explicitly. |
| **D3** | `tooltip` is a **list** of channels; every other channel is singular. | It's the only genuinely many-valued channel. Modelling it as one `Channel` forces an artificial side-list of extra fields. |
| **D4** | Per-mark channel contract as **data** (`MARK_RULES`), not branching code: required / allowed / type constraints. `pie` reuses `color`=category + `y`=value rather than adding a `theta` channel. | Keeps the channel vocabulary at the six §8 names; the table is directly readable as adapter documentation and as planner prompt material. |
| **D5** | `layers` are **overlays on a base mark**, not a list the base lives inside. Bounded three ways: budget (2), an explicit combo allowlist, one shared transform. | The single-mark case — the overwhelming majority — stays flat; composition is opt-in. The allowlist is what keeps "bounded composition" (§8) actually bounded. |
| **D6** | A reference line's `value` may be a literal **or** a named statistic (`mean`, `p95`, …) computed from transform output. | Baking a number into the spec would make zero-cost refresh silently falsify the annotation on new data. |
| **D7** | `spec_version` is **MAJOR.MINOR only**. Compat = same MAJOR and `spec.MINOR <= adapter.MINOR`. | A patch release cannot change grammar, so a patch component is a number nothing may ever depend on. Additive growth bumps MINOR; breaking change bumps MAJOR and orphans stale adapters loudly. |
| **D8** | Every `style` field is Optional, `None` means **inherit**, never "off". Precedence: spec > org skill > theme > adapter default. | Org-convention skills (§7.3) then need **no separate slot in the spec** — they're one layer of the resolver, and a spec that sets nothing inherits the whole house style. |
| **D9** | Canonical JSON **excludes `None`**. | `None` means inherit/absent everywhere, so absent and `null` are the same statement. Emitting both gives two encodings of one spec and breaks spec-diffing for patch mode (§7.7). Round-trip verified lossless on every accepted case. |

## Findings from running it

**1. Validation is two-phase, and only phase 1 is a grammar concern.**
The §8 "deterministic encoding rules (e.g. cardinality caps on `color`)" **cannot** run at spec
construction — cardinality is a property of `profile.json`, which the spec never carries. So:

- *Phase 1* — `ChartSpec.model_validate()`: mark/channel contract, types, layer bounds, annotation
  coherence. Pure grammar, no data.
- *Phase 2* — `validate_against_profile(spec, profile)`: field existence, cardinality caps.
  Needs #5's output.

That split has a consequence worth ratifying: **a spec can be valid and still unrenderable against a
given dataset.** The typed-error taxonomy needs both families, and the planner needs the phase-2
errors as repair feedback, not as hard failures.

**2. Overlay layers must be validated against their own mark even when they override nothing.**
The first draft only checked layers that carried explicit encodings, so an overlay silently
inherited channels its mark can't draw. Fixed — an inheriting overlay is now validated on the merged
channel set. This is a "spec says one thing, picture shows another" hole, exactly the class the
review gate exists to catch, and it's cheaper to close in the grammar.

**3. That fix immediately rejected line + point markers** — the commonest layered chart there is —
because the scatter rule demanded a quantitative `x`. The rule was wrong: a scatter over dates is
legitimate standalone and mandatory for the overlay. Relaxed to `{quantitative, temporal}`;
categorical stays excluded, since catching "scatter of region vs revenue" is the rule's whole value.
**The per-mark type table needs a review pass against the pressure-test corpus (#7) — one wrong cell
silently outlaws a common chart.**

## Open questions this draft did NOT settle

- **Cardinality caps are placeholders** (`color` 12, `facet` 16). Real values need the corpus (#7).
  Should exceeding a cap be an error, or a *degradation* (top-N + "other") that the planner applies?
  Erroring on a 830-way color is right; erroring on 14 is probably not.
- **`MAX_OVERLAY_LAYERS = 2` and the combo allowlist are guesses** — they're the deterministic rail's
  ceiling on composition, so they directly move the ~80% rail-share number (#10).
- **Strict vs. lenient overlay inheritance.** This draft errors when an overlay inherits a channel it
  can't draw. The alternative is silently dropping it (Vega-Lite-ish). Strict fits the project's
  never-silently-wrong ethos, but costs planner round-trips.
- **`sort: str`** is currently an untyped escape ("sort by this other field") — needs a real shape.
- **Does `escape` belong on ChartSpec at all**, or is it a sibling result type? Current draft makes an
  escape spec carry encodings that nothing reads, which the `E_ESCAPE_CONFLICT` rule half-admits.
