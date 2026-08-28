# 17. The custom rail produces an interactive web document, and web is phase P2

- **Status:** Accepted
- **Date:** 2026-08-28
- **Settled on:** [#57](https://github.com/thearcscode/chartagent/issues/57)
- **Builds on:** ADR-0003 (rasterise in a browser), ADR-0005 (`bind` is the public seam;
  `Rasteriser` and `ReviewReport`), ADR-0006 (the server binds, the browser compiles; the
  house palette applied by us), ADR-0008 (serialisation rules), ADR-0011 (the
  untrusted-subtree manifest), ADR-0013 (the escape-reason vocabulary),
  ADR-0015 (the sandbox runs programs we did not write), ADR-0016 (the custom rail)
- **Amends:** ADR-0016 Decisions 1, 2, 5, 6, 7, 9, 10, 11 and 16; ADR-0015 Decision 7
  (reversed) and the scope of Decisions 9 and 10; ADR-0005 Decisions 9 and 12; ADR-0003's
  harness clause and its blank-canvas hazard; ADR-0006 (which gains an origin boundary).
  Errata also on PRD §7.3, §7.5, §7.7, §9 P0.5 and P0.8, and on `CONTEXT.md`.

## Context

**ADR-0016 Decision 1 was a product error.** It closed the custom rail on a
`matplotlib.figure.Figure` return type, which makes the escape hatch produce a *worse*
artifact than the rail it escapes from: the deterministic rail gives the user an interactive
chart in the browser, and D1 would have answered the request Flint *could not serve* with a
static PNG.

The intent is the opposite. The deterministic rail stays Flint. The custom rail is the escape
when Flint cannot serve the request, and it must not be a downgrade — so the agent writes an
**interactive web document**, Studio's browser runs it with the bound rows in the same place
Flint compiles, and review rasterises that same document to PNG for the VLM tier.

Reopening D1 pulled four things with it that D1 had hidden.

### `Rasteriser` was frozen on a type the custom rail cannot produce

ADR-0005 Decision 9 fixed `rasterise(self, envelope: Envelope, *, format="png") -> bytes`, and
`Envelope`'s wire format is frozen at three keys. A generated document has no
`flint_version`, no `backend`, and no input frame. ADR-0003 compounds it: the reference
implementation is *"a browser running our pinned client harness"* which *"loads the vendored
IIFE at the pin the envelope declares"*, and it states plainly that **"the browser here runs
the gate's harness and nothing else."**

### Studio had no origin boundary, and this is the first thing that needs one

ADR-0006 contains **no** mention of iframe, origin, CSP or sandbox attributes. It pinned npm
renderers and forbade CDN fetches, but it never contemplated *generated* JavaScript. Running
the document in Studio's page would put code we did not write on Studio's own origin, beside
the user's Clerk session — the boundary ADR-0015 Decision 1 exists to hold, relocated into a
browser tab, which is not a boundary until it is made one.

### On the web rail, nothing runs in a Python sandbox

Authoring writes text; the user's render is a browser; review's render is a browser; refresh
is the stored document plus new rows in a browser again. `SandboxBackend` was built for
`make_chart`, and `make_chart` has moved to the later python widening.

### Open library choice collides with two rules we already hold

ADR-0006 requires that nothing is fetched that cannot be pinned, and network is unavailable on
ADR-0015's isolated boundaries. Measured, minified, from jsDelivr: **Chart.js 4 ≈ 203 KB,
D3 7 ≈ 273 KB, ECharts 5 ≈ 1,009 KB, Plotly 2 ≈ 4,451 KB** — a 22× spread that rules out any
uniform "inline the library into the stored document" answer.

## Decision

### 1. The artifact is an interactive web document plus a review PNG

The agent writes HTML/JS/CSS. Studio's browser runs it with the bound rows; review rasterises
it. **Not** a `matplotlib.figure.Figure`, and not a sandbox picture as the thing the user sees.
The escape hatch must not be a downgrade from the rail it escapes.

### 2. Web is phase P2; python is a later widening

**ADR-0015 Decision 7 is reversed.** It made `python` the phase-P2 runtime and `web` a §9 P1
Fast follow; the phase-P2 custom rail **is** the web profile, and python — matplotlib, or
plotly-as-Python — is the later widening.

**Two custom-rail profiles do not ship in one phase.**

### 3. Phase P2 does not implement `SandboxBackend`

ADR-0015 stands **accepted, as the contract for the python widening**. Untrusted JavaScript on
this rail runs in Decision 5's iframe (for the user) and in the `Rasteriser`'s browser (for
review) — two client-side boundaries, neither of them a `SandboxBackend`.

So ADR-0015 Decision 1's rule is unchanged and its *implementation* is not built in this
phase: **no python extra, no bwrap probe, no `[docker]` work at P2**. [#6](https://github.com/thearcscode/chartagent/issues/6)
is not reopened.

### 4. Library choice is open, and there is no allowlist

The agent picks a library from the request, or writes the document from scratch with no
library at all. Not "D3 and ECharts only". We do not close on an import name, on a return
type, or on PandasPlotBench — that evidence was about *Python* codegen and it does not
license an allowlist here.

`libraries=()` — from scratch — is a first-class outcome, not a fallback.

### 5. The document runs in a sandboxed iframe at an opaque origin

`sandbox="allow-scripts"` **without** `allow-same-origin`. MDN is explicit that the two
together let the embedded document *"remove the `sandbox` attribute, making it no more secure
than not using it at all."*

Two facts that decide the implementation, and that are easy to get wrong:

- **The `sandbox` attribute does not cut network.** No sandbox token gates `fetch`/XHR. The
  **CSP does**, and it is what makes "the iframe never fetches" true rather than hoped.
- **`event.origin` is useless here.** The HTML standard: an opaque origin *"is serialized as
  `null`… for which the only meaningful operation is testing for equality."* Every opaque
  iframe reports the same `"null"`, so the receiver must check
  **`event.source === iframe.contentWindow`**.

Rows and theme arrive by `postMessage` at paint time. The document reads no cookie, no
`localStorage`, no Clerk token, and reaches no network.

**ADR-0015 Decision 1's boundary now has two implementations** — a server-side
`SandboxBackend` and this client-side iframe — and only the second is on the P2 path.

### 6. `Rasteriser` widens to `Envelope | BoundDocument`, and the parameter is renamed

```python
class Rasteriser(Protocol):
    def rasterise(self, target: Envelope | BoundDocument, *, format: Literal["png"] = "png") -> bytes: ...
```

An **implementer-breaking** amendment of ADR-0005 Decision 9. `envelope` becomes a lie the
moment the union lands, so the rename is paid inside the same break rather than deferred into a
second one.

**Not `ChartDocument`.** The stored triple cannot paint — it has no rows, no theme and no
library bytes. `Envelope` is self-sufficient; `ChartDocument` is not. Union on the *paintable*
type.

**Review uses the same inner sandboxed iframe as Studio.** Playwright must **not** navigate to
the generated HTML as the top-level page — that would hand the document the harness's own
origin and make the review render a different thing from the user's. Restating ADR-0003 for
this path: our harness page on the outside, the untrusted document in the iframe inside, **no
Flint IIFE on this path at all**. ADR-0003's *"the gate's harness and nothing else"* was
written to stop the review browser drifting onto the **compile** path; that intent is intact.

### 7. The source is a module against a host-owned shell

The host owns the shell: the HTML, the container element, the CSP, the hashed `<script>` tags,
the `postMessage` handshake and its `event.source` check, and a bootstrap that calls the
agent's symbols. **The agent never writes the handshake** — under any design where it did,
the `event.source` check is exactly the line that gets omitted, and one omission lets any
opaque iframe on the page drive that chart.

The agent writes a module defining two symbols we call:

```js
render(data, el)        // draws into the host's element
getPlottedSeries()      // declares what it drew
```

- **Re-read without redraw is the last draw.** The host empties `el`, calls `render`, then
  calls `getPlottedSeries`.
- The module **may** keep a chart instance on `el`. It must register **no `window` or
  `document` listeners**.
- Agent CSS is **scoped to `el`** and must not restyle the shell.
- A one-symbol `render`-returns-series variant is refused: it couples the truthfulness read to
  the draw and makes a re-read impossible.

### 8. Three named types, and the stored/paintable split

```python
@dataclass(frozen=True)
class LibraryPin:     name: str; version: str; sha256: str
@dataclass(frozen=True)
class ChartDocument:  module: str; styles: str | None
                      libraries: tuple[LibraryPin, ...]; contract_version: int = 1
@dataclass(frozen=True)
class BoundDocument:  document: ChartDocument; rows: pyarrow.Table
                      theme: Mapping[str, str]; libraries: Mapping[str, bytes]
```

**`ChartDocument` is what you store; `BoundDocument` is what you paint** — the same
distinction `Envelope` embodies for the deterministic rail, which is why the name uses the
house's central verb. `LibraryPin` carries **no bytes**: the pin is identity, so one stored
document can be rasterised anywhere the bytes can be produced.

`ChartDocument.libraries` **tuple order is script load order**. Pins are **JavaScript only**;
CSS is `styles`. From scratch is `libraries=()`.

Off `BoundDocument` deliberately: **container dimensions**, which arrive on the channel at
paint time because they are Studio's layout and the `Rasteriser`'s constructor setting; and
`contract_version`, which belongs to the stored document.

`theme` is **data-palette tokens only**. State accents stay off the module.

### 9. Rows are Arrow on the type and JSON on the channel

`BoundDocument.rows` is a `pyarrow.Table`, consistent with Arrow as internal interchange. The
bootstrap hands the module a **plain JSON array of objects** — requiring the module to decode
Arrow IPC would force an Arrow JS dependency into every document, including the from-scratch
case.

**ADR-0008 Decision 9's three serialisation rules apply to this JSON**: typed temporal columns
as ISO-8601, UTC as `Z`, non-finite as `null`. This is a **second browser wire, not an
`Envelope` exception** — one library serialiser, and both paint hosts call it.

### 10. Where library bytes come from

- The agent **names a package and version, or goes from scratch**. A free URL is **refused** —
  it is SSRF surface and it pins nothing.
- **Studio's server** resolves the name through **one pinned registry**, at authoring time, and
  stores the bytes **by sha256**. Blobs are **globally content-addressed**, not owner-scoped
  uploads.
- **The host assembles** into `srcdoc` or a blob URL. **The iframe never fetches.** Otherwise
  Decision 5's CSP and "assemble at render" fight each other.
- **Authoring fetch is the server; render stays offline.**

### 11. `build_shell` is public, in the base wheel

```python
def build_shell(document: ChartDocument, *, libraries: Mapping[str, bytes]) -> Shell
```

Public because **Studio and the `Rasteriser` are two callers of one builder**, and Studio is a
separate repo consuming the public API only. In the **base wheel**, not the raster extra, for
the same reason. The precedent is exact: ADR-0005 kept `_bundle/` private behind the public
`flint_bundle()` accessor because the app must not reimplement something whose correctness we
assert — and here what is emitted *is* the security boundary.

It returns a **frozen object**, not a string: the HTML **and the iframe sandbox tokens the
caller must apply**. `sandbox="allow-scripts"` lives on the **parent's** `<iframe>` element,
not inside the HTML, so a builder that returned only markup would leave its own boundary to
the caller's memory. The CSP and the `event.source` check stay in the HTML.

The shell is **rows-free and theme-free**, so the same assembled HTML serves the user's render
and the review render — which is what makes the review picture the thing the user actually
sees. Avoid `assemble` in the name: that is Flint's word throughout.

### 12. The caller hands bytes in; `build_shell` verifies and never fetches

`libraries` is a `Mapping[str, bytes]` keyed by sha256. `build_shell` **verifies every pin**
and raises on missing or mismatched bytes. An **empty map is legal** — that is the
from-scratch document.

The library **never fetches**, inside the wheel or the raster extra. All SSRF surface stays in
Studio, where Decision 10 put it deliberately. Verification belongs to whoever assembles,
because that is the last moment before untrusted bytes become executable: a compromised blob
store cannot inject, since the pin travels with the document and the document is what was
reviewed.

A `LibraryStore` protocol that fills the mapping lazily is a **later migration**, named and not
built.

### 13. Truthfulness: we call a symbol we named, and the guarantee narrows

`figure_json`-as-matplotlib-artists dies with ADR-0016 Decision 1. Extraction cannot be general
here — **ECharts and Chart.js render to `<canvas>`**, so there is no DOM to read, and D3's SVG
structure is per-author.

So the document **declares** what it drew through `getPlottedSeries()`, and the comparison
happens **outside the document**, against transform output we already have.

**Write the narrowing plainly: this catches an honest bug, not a determined lie.** The
deterministic rail's truthfulness is structurally strong because Flint compiles a frame we
validated; a self-report is not that. **P0.8's guarantee is now rail-dependent.** The Tier-2
VLM still looks at the picture.

### 14. Theme is guaranteed for chrome and best effort for the chart

The host guarantees the iframe page's **chrome** — card background, padding, borders, DOM
text — because the host writes it. **Anything the library paints — series, axes, ticks,
legend — is best effort.**

ADR-0006 can apply the palette *after* `assemble*` because we control the compile; here the
agent writes the drawing code and nothing can recolour it afterwards. **CSS custom properties
do not recolour canvas libraries** — say so rather than implying a fallback exists.

**A custom-rail chart can come back off-brand in the picture, and no deterministic check will
catch it.** The Tier-2 VLM is the only look. Org brand palette rides the channel as tokens;
**skills do not carry hex** (ADR-0016 Decision 14's collision, restated).

### 15. Failures have three owners, split by where they are detectable

**Assembly — a library error**, and the only one:

```python
class DocumentAssemblyError(ChartAgentError):
    kind: Literal["pin_missing", "pin_mismatch", "contract_unsupported",
                  "source_too_large", "library_too_large", "assembled_too_large"]
```

Raised **only** at `build_shell`. Caps are configuration like `bind`'s timeout, never literals.
The shipped per-blob default **admits Plotly-class payloads (~5 MB)**; a tighter cap is caller
policy, and must be, because a default that excluded Plotly would be an allowlist enforced by
a number.

**Paint time — `RasterisationError` plus `CheckResult`**, never `DocumentAssemblyError`:
missing symbols, a throw, a hang, or a false paint signal.

**The bootstrap reports a boolean paint signal on the channel, and the `Rasteriser` raises if
it is false. An empty-container PNG is never success.** ADR-0003 warned that *"a rasteriser
that returns bytes without raising has not necessarily rendered anything"* and left it as a
caution; here a document that throws inside `render` still yields a valid screenshot of an
empty container — but we call a symbol we named, so the hazard becomes checkable. **Closed for
this rail only**; the Flint path keeps ADR-0003's caution as written.

**Studio owns the user-facing equivalent.** It is not specified here, and no existing screen
vocabulary is claimed to cover it.

### 16. The document contract is versioned

`ChartDocument.contract_version: int`, **1** at P2. `build_shell` refuses a version it cannot
serve, as `kind="contract_unsupported"`.

The stored artifact outlives the code that reads it — the same reason `x_chartagent` carries
`spec_version` (ADR-0002 D7, bumped by ADR-0010). **Dropping support for version 1 is a
library major.** It is **not** inferred from `chartagent`'s SemVer: a document can be older
than any installed version of the library that reads it.

### 17. Skills do not ship at P2; the guidance is inline

Phase-P2 guidance is **inline principles in the prompt** — how to choose a library, and when
writing from scratch beats reaching for a dependency, where size may be a principle. **No
`SKILL.md` loader at P2, and no per-library catalogue**, because a catalogue is an allowlist by
another name.

ADR-0016 Decision 14's sequencing argument stands: P0.10's benchmark measures this prompt.
Skills remain the **§9 P1 user-extensible** mechanism, and the learning moves into them when
that lands.

### 18. What `__all__` gains

`LibraryPin`, `ChartDocument`, `BoundDocument`, `build_shell`, `DocumentAssemblyError`, the
JSON channel serialiser, and `build_shell`'s frozen return (HTML plus the required iframe
sandbox tokens).

**ADR-0016 Decision 16 — *"`__all__` is unchanged by this ADR"* — is dead**, and ADR-0005
Decision 12's contract widens accordingly.

**Erratum — 2026-08-28 ([#60](https://github.com/thearcscode/chartagent/issues/60),
ADR-0018).** Three more names, and they are what makes the seven above reachable from storage:
**`ChartRecipe`**, **`BoundRecipe`** and **`bind_recipe`** (with `EscapeReason` as a field type
exported alongside). ADR-0018 places the custom rail's stored artifact — this ADR's
`ChartDocument` **contained** in a recipe that also carries `transform`, `source_schema`,
`escape_reason` and `theme_spec` — and supplies the rows that Decision 8's `BoundDocument` had
no producer for.

`bind_recipe` does **not** return a `BoundDocument`: `theme` and library **bytes** are
paint-time inputs, and forcing them into a verb that binds rows would make a refresh writing
only a bind cache fetch a Plotly-sized blob to do it. `BoundRecipe` is rows-only, **cannot
paint**, and has **no wire format** — nothing compiles it. Decision 16's `contract_unsupported`
stays here at `build_shell`, because `bind_recipe` never reads `module`, `styles` or
`libraries`.

## What this amends

- **ADR-0016 Decision 1** — replaced by Decision 1 here. **Decisions 2, 5, 6, 7, 9, 10, 11 and
  16** fall with it: the prompt states a *contract*, not a library (D2 → D7/D17); house style is
  **not** `rcParams` (D5 → D14); the payload is a JS module, not a Python module (D6 → D7);
  network is cut by **CSP**, not by a sandbox tier (D7 → D5); `figure_json` per-artist is
  replaced by `getPlottedSeries()` (D9/D10 → D13); the seeded runner is gone with the runner
  (D11 — see *Consequences*); and `__all__` grows (D16 → D18).
  **ADR-0016 Decisions 3, 4, 8, 13 and 15's idea stand unchanged.**
- **ADR-0015 Decision 7** — **reversed**: web is phase P2, python is the later widening.
  **Decisions 9 and 10 and their 2026-08-28 errata are re-scoped**: they describe the **python
  widening**, not phase P2. ADR-0015 remains **Accepted** as that contract.
- **ADR-0005 Decision 9** — `Rasteriser` widens to `Envelope | BoundDocument` and the parameter
  is renamed to `target`. Implementer-breaking. **Decision 12** — `__all__` widens by Decision
  18's list.
- **ADR-0003** — the harness clause is restated for this path (our harness outside, the
  untrusted document in an inner iframe, no Flint IIFE), and the blank-canvas hazard is
  **closed on this rail** by the paint signal.
- **ADR-0006** — gains an **origin boundary** it did not have: generated JS runs only in an
  opaque-origin sandboxed iframe with a network-cutting CSP. Its palette rule holds for Flint
  and does not reach this rail (Decision 14).
- **PRD §7.3** — the 2026-08-28 erratum closing the rail to `matplotlib.figure.Figure` is
  **withdrawn**; library choice is open (Decision 4).
- **PRD §7.5 and §9 P0.5** — the phase-P2 custom-rail profile is **web**, not python.
- **PRD §7.7** — refresh is the stored document plus new rows on the channel, in a browser.
- **PRD §9 P0.8** — truthfulness is a **declaration** read through `getPlottedSeries()`, and
  the guarantee is rail-dependent (Decision 13).

## Consequences

- **The escape hatch is no longer a downgrade.** A request Flint cannot serve gets an
  interactive chart, not a PNG.
- **Two boundaries, not one.** ADR-0015's rule holds with a client-side implementation on the
  P2 path; the server-side one waits for the python widening it was written for.
- **Determinism is not carried over, and is not decided here.** ADR-0016 Decision 11 seeded
  `random` and `numpy.random` in a runner that no longer exists. The browser analogue —
  overriding `Math.random` from the bootstrap — is available and **deliberately not decided**,
  because refresh and the truthfulness comparison both have a stake and neither was grilled.
  Named so it is not mistaken for settled.
- **The library never fetches, at any layer.** Compile path (ADR-0001), sandbox (ADR-0015) and
  now document assembly all hold the same line.
- **Off-brand custom-rail charts are possible and undetectable.** Priced in Decision 14.
- **`__all__` grows by seven names**, the largest single widening since ADR-0005.

## Alternatives rejected

- **A `matplotlib.figure.Figure` return** — ADR-0016 D1, the error this ADR exists to correct.
- **Shipping both custom-rail profiles in phase P2** — Decision 2.
- **A curated library allowlist, or a per-library skill catalogue** — Decisions 4 and 17. A
  catalogue is an allowlist by another name.
- **Same-origin iframe, or rendering in the page** — Decision 5. Same-origin reaches
  `localStorage`, the Clerk token, and Studio's API with the user's credentials.
- **Unioning `ChartDocument` into `Rasteriser`** — Decision 6. A category error: the stored
  triple cannot paint.
- **Wrapping the document in an `Envelope`-shaped carrier** — a lie in a type; the wire format
  is frozen at three keys and `flint_version`/`backend` are meaningless here.
- **A document that writes its own `postMessage` listener** — Decision 7.
- **Inlining libraries into the stored document** — Decision 10. Plotly is 4,451 KB against
  Chart.js's 203 KB; ADR-0007 keeps revisions in Postgres.
- **A CDN reference at render** — Decision 10. Breaks ADR-0006's pinning rule and fails on
  exactly the isolated boundaries we recommend.
- **A `LibraryStore` pull protocol now** — Decision 12, named as a later migration.
- **DOM extraction for truthfulness** — Decision 13. Fails on canvas.
- **CSS custom properties as a theming guarantee** — Decision 14.

## What this feeds

- **Review-gate tier design** (fog) inherits: `getPlottedSeries()` as the truthfulness input and
  its **self-reported** weakness; the **paint signal** as a required check; `CheckResult` still
  its to define; and ADR-0016 Decision 3's fourth escape bucket unchanged.
- **`escape` placement** (fog) is unchanged and still carries two payloads — the reason and the
  code, which is now a `ChartDocument` rather than a Python module. **Not minted here.**
- **The python widening** inherits ADR-0015 whole, plus ADR-0016's D9/D10/D11 re-scoped to it.
- **Determinism on the web rail** is open (see *Consequences*).
- **Studio** inherits the registry resolution, the content-addressed blob store, the iframe
  sandbox tokens, and the user-facing failure vocabulary.

## Related

- HTML Standard — an opaque origin *"is serialized as `null`… the only meaningful operation is
  testing for equality"*
- MDN `<iframe>` — `allow-scripts` with `allow-same-origin` *"lets the embedded document remove
  the `sandbox` attribute"*; no sandbox token gates `fetch`
- Measured 2026-08-28, minified via jsDelivr: Chart.js 4 ≈ 203 KB, D3 7 ≈ 273 KB,
  ECharts 5 ≈ 1,009 KB, Plotly 2 ≈ 4,451 KB
- PRD §7.3, §7.5, §7.7, §9 P0.5 / P0.8 / P0.10, §11
