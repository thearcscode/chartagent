# chartagent — UI mockups

Interactive UI mockups for chartagent, built from `chartagent-prd.md` and
`prototypes/chartspec-v1/README.md`. The library ships no UI, so these define the
surface layer around it: a design system, the five places a chart lifecycle
becomes visible, a public landing page, and the hosted product’s v0 editor.

Each file is a self-contained HTML document. Open it directly in a browser — no
build step, no install. `support.js` must sit alongside them. Charts render live
via ECharts (CDN), the PRD's default web target.

## Files

| File | Contents |
| --- | --- |
| `Chartagent UI.dc.html` | The mockup canvas — design system plus every product screen, grouped into numbered turns |
| `Chartagent Landing.dc.html` | Marketing landing page with interactive hero, plus sign-in and create-account screens |
| `Chartagent Landing Ideas.dc.html` | Scratch file: the three landing sections in isolation before they were folded into the page |
| `Chartagent Studio.dc.html` | Chartagent Studio v0 — the spec editor and renderer, the surface the planner-era canvas does not have |
| `support.js` | Runtime required by the four documents |

Every screen supports a light and dark theme, toggled by the moon icon at the top
right of each turn header (or the app chrome, where a host app would put it).

## Screen index — `Chartagent Studio.dc.html`

Studio v0 is the hosted product with **no planner**: open a Flint frame, bind it,
render it, save it, refresh it at `$0.00`. Every screen in the UI canvas assumes
an instruction goes in and a chart comes out, so none of them is this surface.
Settled by [ADR-0005](../docs/adr/0005-bind-is-the-public-seam.md) and
[ADR-0006](../docs/adr/0006-the-server-binds-the-browser-compiles.md).

**Turn 6 — the spec editor, three ways, plus the states they share**

**Locked on `6b`** (2026-08-24, [#27](https://github.com/thearcscode/chartagent/issues/27)): the
generated form is the editor and the JSON is a drawer over the same document. `6c`'s
answer is taken for *data only* — the source is bound at request time, never stored in
the frame — and the pipeline is not the home screen. `6a` and `6c` remain as the record
of what was rejected; `6d` and `6e` are locked as drawn.

- `6a` Document first. The frame is the surface, the chart is a preview, and the
  outline rail is the only concession to not hand-writing JSON.
- `6b` Chart first. The inspector is generated from `vocabulary()` — option
  labels from the pin, `min`/`max` shown as *slider bounds, not limits*, a
  dependency-disabled control, and a `data_dependent` control marked "checked at
  compile". The document is a drawer. Backend switcher is live.
- `6c` Pipeline first. Source → transform → bound rows → encodings → compile, with
  the transform output as a table and per-backend support read from the pin. The
  seam is visible as a place.
- `6d` The three states, four steps: *won't render here* (valid document, wrong
  dataset), the row-drop refusal, `SpecVocabularyError` after a pin bump, and
  `BackendCapabilityError` on a backend switch. Advance with the button.
- `6e` Refresh. One `bind` against a new source, an empty document diff, and a
  saved-spec index where all six cards re-render live.

## Screen index — `Chartagent UI.dc.html`

Screens are grouped by turn, newest first. Ids are stable and referenced in
review comments.

**Turn 5 — lifecycle detail screens**

- `5a` Patch mode edit review. Before/after charts, the two-hunk spec diff, and
  the light-mode review showing which 2 of 9 checks re-ran.
- `5b` Schema drift recovery, three steps: detected (spec-vs-snapshot field
  table) → remapping (`plan_tier` → `tier_name`, plus a cast for the retype) →
  refreshed (app revision 1 → 2, `spec_version` unchanged at 1.0, $0.00,
  mapping recorded). Advance with the button.
- `5c` Escape-reason telemetry. Reason histogram, drill-down showing `pie + line`
  as 311 of 438 `E_LAYER_COMBO` runs, a proposed grammar change with estimated
  rail shift, and custom-rail share by release. Intended as a fourth tab in `1c`.

**Turn 3 — merged inspector, light mode in situ**

- `3a` Run inspector combining the rail diagram and the event log. The diagram is
  the default view; each stage's "details ›", the tier rows, and the
  Overview/Log switch open the log. Interactive.
- `3b` The embedding app pinned to light tokens, ignoring the global flip, so
  both palettes can be judged side by side.

**Turn 2 — streaming UX alternatives**

- `2a` Split-path diagram: the two-rail architecture is the picture, with the
  untaken rail dashed and the routing reason called out.
- `2b` Event log: every emitted event, nested critique findings, live caret.

**Turn 1 — foundations and the five surfaces**

- `1a` Foundations. Surfaces, ink, the state accents, the separate data palette,
  type scale, atoms.
- `1b` Embedding app — the "describe the chart you want" feature a SaaS product
  ships, with a "How this was made" panel.
- `1c` Developer run inspector — profile → plan → rail → review, streaming.
- `1d` Playground — instruction in, spec/artifacts/review/code out.
- `1e` Spec and review report — ChartSpec JSON, capability match, T1 lints, T2
  critique rubric, repair history.
- `1f` Lifecycle console — saved specs, scheduled refreshes, `SchemaDriftError`
  row and recovery panel.

## Design system

Dark-first, neutral ink, and two colour systems held strictly apart: state hues
for chrome, a data palette for chart series. All values are CSS custom properties on
`:root`, with a `body[data-theme="light"]` override; nothing else needs to change
to reskin.

**Surfaces** (dark → light)

| Token | Dark | Light |
| --- | --- | --- |
| `--bg` | `#0a0a0c` | `#e9e7e2` |
| `--app` | `#121216` | `#ffffff` |
| `--panel` | `#17171c` | `#faf9f7` |
| `--raised` | `#1d1d23` | `#f1efea` |
| `--rail` | `#0f0f13` | `#f6f5f2` |

**Ink and borders**

| Token | Dark | Light |
| --- | --- | --- |
| `--ink` | `#ecebf0` | `#191817` |
| `--muted` | `#8b8a97` | `#6b6862` |
| `--faint` | `#6a6975` | `#8f8b83` |
| `--border` | `#2a2a32` | `#dcd8d0` |
| `--border-strong` | `#3d3d47` | `#bfb9ae` |

**State accents — chrome only.** These carry the core product idea: which rail
ran, and whether the result needs attention. They appear on chips, status text,
log lines, rail diagrams, tier rows, and error banners.

| Token | Meaning | Dark | Light |
| --- | --- | --- | --- |
| `--teal` | deterministic rail | `#57d3cb` | `#0d8f86` |
| `--violet` | custom code rail | `#a78bfa` | `#6b4de0` |
| `--amber` | needs review | `#e8b568` | `#a8730c` |
| `--red` | drift / error | `#e8737d` | `#c33f4b` |

`--blue` (`#7aa2f7` / `#3a6fd8`) survives as a brand gradient stop in the app
mark. It carries no state meaning and is not a series color.

**Data palette — chart frame only.** A separate five-hue set, used for series
color and for nothing else. It is deliberately disjoint from the state accents:
no cyan-teal, no violet, so a series can never be read as a claim about the
rail.

This is published Okabe-Ito with two of its eight entries declined and its
neutral promoted. The bluish-green (`#009e73`) is out because it lands inside the
band the rail reserves for teal. The yellow (`#f0e442`) is out because no yellow
can be both yellow and legible on a near-white panel — it measures 1.26:1 against
`--panel` in light mode, and darkening it far enough to read stops it being
yellow. Okabe-Ito's own eighth entry, a neutral, takes the fifth slot instead: a
neutral has no hue for a dichromacy to collapse, and one mid grey reads on both a
near-black and a near-white panel.

| Token | Both themes | Okabe-Ito name |
| --- | --- | --- |
| `--series-1` | `#0072b2` | blue |
| `--series-2` | `#e69f00` | orange |
| `--series-3` | `#56b4e9` | sky blue |
| `--series-4` | `#d55e00` | vermillion |
| `--series-5` | `#7f7f7f` | (neutral) |

One palette serves both themes, which is only possible because the fifth slot is
neutral; `body[data-theme="light"]` deliberately does not override these. Series
are assigned `--series-1` through `--series-5` in order, which the Tier-1
colorblind-safe palette lint enforces. A theme may override the whole palette;
nothing may override a single series.

`design/palette-check.py` is the check. It simulates protanopia, deuteranopia and
tritanopia with the Viénot–Brettel–Mollon matrices and scores the closest pair in
CIEDE2000. Run `calibrate` to see the thresholds justified against published
palettes rather than chosen: the floors are what Okabe-Ito and Tol actually
achieve, since nothing in print meets a naive ΔE00 ≥ 10 under tritanopia.

Two honest limits, recorded rather than hidden. Orange and sky blue sit near
2.2:1 against `--panel` in light mode — softer than the rest, and the same trade
every published palette makes, because contrast against the paper is not what
distinguishes one series from another. And a five-series chart is the ceiling;
past that, the design asks for small multiples instead of a sixth hue.

**The one sanctioned crossover.** A chart whose *measured quantity is the rail
itself* — custom-rail share by release (`5c`), grammar coverage on the landing
page — uses the state hue as its series color, because there the hue is what the
data means. Such a chart always carries a title that names the rail, so the
reading is never ambiguous. Every chart of user data stays on the data palette.

## Type

Three families, each with one job. Never more than one in a single line.

- **Instrument Serif** — display and moments of authorship (page titles, chart
  titles, large figures). Tracking tightens as size grows.
- **IBM Plex Sans** — all chrome, labels, body copy. 400/500/600.
- **IBM Plex Mono** — anything the machine produced: specs, field names, event
  logs, metrics, error codes, section eyebrows.

All three are SIL OFL 1.1 — free for commercial use, embedding, and modification,
with no attribution required in the product.

## Notes for implementation

- Rail color is load-bearing, not decoration. Teal means no generated code ran;
  violet means the sandbox did. Don't reuse either hue for anything else — and in
  particular, keep both out of the chart frame. The chart block is styled from the
  data palette and the neutral surfaces only: no rail-tinted borders, fills, or
  captions on or around it. A reader should be able to judge the chart without
  reading a routing decision into it, and should have to look at the chrome to
  learn which rail produced it.
- Every screen states cost and latency. The `$0.00` refresh claim appears
  wherever a saved spec is re-rendered.
- Errors name the drift and refuse to draw. There is no partial-render state in
  these designs on purpose — `5b` step 1 is the pattern.
- Type scale floors: chart labels 10px mono, body 12.5px sans. Nothing smaller.
