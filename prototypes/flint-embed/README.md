# flint-embed — evidence harness for ADR-0001

Reproduces every measurement quoted in `docs/adr/0001-embed-pinned-flint-compiler.md`:
that Flint's compiler runs inside CPython with no Node, how faithful it is against
Microsoft's own fixtures, and how the two candidate JavaScript engines compare.

**This is a measurement harness, not the integration.** The real thing needs a context
pool, a typed Python surface and error mapping. None of that is here.

## Setup

Requires Node (to build the bundle only, never at runtime) and Python 3.11+.

```bash
cd prototypes/flint-embed
./setup.sh            # packs flint-chart, bundles it, clones the 705 fixtures
python -m venv .venv && .venv/bin/pip install quickjs pythonmonkey
```

`setup.sh` writes two things into `build/`:

- `flint.iife.js` — the pinned compiler as one self-contained file (~1.6 MB)
- `fixtures/` — a sparse checkout of `shared/test-data` (705 cases, ~39 MB)

Both are gitignored. The pinned version lives in `FLINT_VERSION`.

## Run

```bash
.venv/bin/python harness.py smoke      # all 5 backends compile in-process
.venv/bin/python harness.py parity     # 705 fixtures, per-engine, vs Node
.venv/bin/python harness.py bench      # boot, latency, memory, thread scaling
.venv/bin/python harness.py dates      # the date-parsing divergence and its fix
```

`parity` and `bench` must run the engines in **separate processes** — QuickJS and
PythonMonkey segfault if imported into the same interpreter. `harness.py` re-execs itself
per engine to keep them apart.

## What each check establishes

| Check    | Establishes |
| -------- | --- |
| `smoke`  | Vega-Lite, ECharts, Chart.js, Plotly and Excel all compile embedded; themes and recommenders reachable. `structuredClone` is the only missing global. |
| `parity` | 705/705 execute without error. PythonMonkey agrees with Node on 695, QuickJS on 676; the two engines agree with each other on 686. PythonMonkey's 10 disagreements are all date parsing; QuickJS's 29 also include `gallery_kpi_card`. |
| `bench`  | Boot, p50/p95 latency, memory per context, and that sharing one QuickJS context across threads **crashes the process**. |
| `dates`  | Non-ISO date strings diverge by engine and change the axis *type*; ISO-8601 normalisation upstream removes the divergence. |

## Gotchas found the hard way

- **A shared QuickJS context across threads is a SIGSEGV**, not an exception. `bench`
  demonstrates it in a subprocess on purpose. One context per thread, enforced structurally.
- **Don't import both engines** into one interpreter.
- **Fixture inputs are wrapped:** the assembler argument is `input.json → .input`, not the
  file root. The root also carries `title`, `description` and `chartType`.
- **Ignore `_`-prefixed keys** when comparing specs (`_width`, `_warnings`, `_transform`,
  `_pivot`) — they are compiler metadata, not output.
- **Canonicalise key order in one language.** Comparing a JS-sorted key order against a
  Python-sorted one reports phantom diffs on CJK labels: JS sorts by UTF-16 code unit,
  Python by code point. This produced two false positives before it was caught.
- **`expected.json` is Vega-Lite only.** There is no recorded ECharts output anywhere in
  the repo, so any non-Vega-Lite backend has no upstream oracle.
- **`setup.sh` skips the fixture fetch when `build/fixtures` already exists**, and the fetch
  ends in `|| true`, so a re-run against a *new* `FIXTURE_COMMIT` silently keeps the old
  checkout. Delete `build/fixtures` when changing the pin.
