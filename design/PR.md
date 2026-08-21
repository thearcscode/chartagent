# Add UI mockups for chartagents (`design/`)

## What this is

The library ships no UI, but the PRD implies several: an embedding app, a
developer run inspector, a playground, a spec/review viewer, and a lifecycle
console. This PR adds interactive mockups for all of them, plus a design system
and a public landing page, so that UI decisions — color semantics, type,
structure, flow — are settled before implementation starts rather than during it.

Nothing here is production code. No existing files are touched; everything lands
under `design/`.

## How to view

Open any of the `.dc.html` files in `design/` directly in a browser. No install,
no build step. `support.js` must stay alongside them. Charts render live via
ECharts from a CDN.

Start with `design/Chartagents UI.dc.html` — it holds the design system and every
product screen. `design/README.md` indexes the screens and documents the tokens.

## Contents

- `design/Chartagents UI.dc.html` — design system plus 11 product screens, grouped
  into numbered turns with stable ids (`1a`, `3b`, `5c`) for review comments.
- `design/Chartagents Landing.dc.html` — landing page with an interactive hero,
  three product-argument sections, and two auth screens.
- `design/Chartagents Landing Ideas.dc.html` — the three landing sections in
  isolation, kept for reference.
- `design/README.md` — screen index, token tables, type rationale.

## Design decisions worth reviewing

**Rail color is load-bearing, and confined to chrome.** Teal means the
deterministic rail ran with zero generated code; violet means the sandbox did.
The two hues appear on chips, logs, rail diagrams and overview panels — never
inside or around a chart frame. Charts draw from a separate data palette
(`--series-1` … `--series-5` — published Okabe-Ito, less its bluish-green and its
yellow, with its neutral in the fifth slot) that contains no cyan-teal and no
violet, so a series can't be misread as a routing claim. `design/palette-check.py`
enforces that, and the thresholds it enforces are calibrated against published
palettes rather than invented. The single exception is a chart whose
measured quantity *is* the rail, such as custom-rail share by release. If a
reviewer disagrees with this split, most of the visual system follows from it.

**Escape reasons get their own surface.** `5c` treats escape-reason telemetry as a
first-class screen — reason histogram, drill-down, proposed grammar change with
estimated rail shift. The PRD makes escape logging a P0 and grammar growth the
standing roadmap input, but no screen owned it.

**Drift refuses to draw.** `5b` has no partial-render state on purpose. Step 1 is a
hard stop naming both changed fields; recovery is a spec remap with no model call.
Additive drift is ignored so harmless migrations don't trip it.

**Patch mode is shown as an economic argument.** `5a` puts the token and cost delta
(1.1k / $0.004 versus 9.1k / $0.031) next to the two-hunk diff and the 7-of-9
skipped review checks.

**Every screen states cost and latency**, and the `$0.00` refresh claim appears
wherever a saved spec is re-rendered.

## Fonts and licensing

Instrument Serif, IBM Plex Sans, IBM Plex Mono — all SIL OFL 1.1. Free for
commercial use, embedding, and modification, with no attribution required in the
product. Loaded from Google Fonts; self-host before shipping if you'd rather not
depend on the CDN.

## Open questions for reviewers

1. Should `5c` be a fourth tab inside the run inspector, or its own console view?
2. Light theme currently darkens the accents to hold contrast on paper-white
   surfaces. Worth checking against any brand direction you have in mind.
3. `Chartagents Landing Ideas.dc.html` is scratch — happy to drop it if you'd
   rather the folder stayed minimal.
