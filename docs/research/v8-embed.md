# Was V8-in-process the better embedding route?

- **Status:** Research notes for [issue #29](https://github.com/thearcscode/chartagent/issues/29). **Facts only — no decision.**
- **Date:** 2026-08-21
- **Decision this feeds:** a new engine-choice ticket that would amend ADR-0001 in place, the way Decision 4 was amended. [Context pool](https://github.com/thearcscode/chartagent/issues/21) waits on that, not on these notes.
- **Branch:** `research/v8-embed`
- **Probes:** `prototypes/v8-embed-probe/` and the existing `prototypes/flint-embed/harness.py` (with a `miniracer` engine added). Measured on macOS / arm64 (M-series), CPython 3.13.7. **Not measured on Linux.**

## The gap being researched

ADR-0001 compared exactly two engines and never recorded why those two.
`prototypes/flint-embed/harness.py` hard-coded `ENGINES = ("quickjs", "pythonmonkey")`.
The test oracle is Node/V8. PythonMonkey's ten parity failures exist because it is not
V8: `Date.parse("Jan 2020")` is `NaN` under SpiderMonkey and a timestamp under V8, which
changes the axis type. If the embedded engine *were* V8, that class of divergence
disappears by construction.

This ticket also inherited the co-load question from [#22](https://github.com/thearcscode/chartagent/issues/22):
ADR-0001 asserts that QuickJS and PythonMonkey "segfault if imported into the same
interpreter" (a bare note, no cited probe). That claim is now measured.

Porting to Python and the Node sidecar stay rejected. They were not re-opened.

## Summary of what was established

1. **A viable Python V8 binding exists and covers the PRD wheel matrix: `mini-racer` 0.14.1.**
   `py3-none` wheels for macOS arm64/x86_64, manylinux aarch64/x86_64, musllinux both, Windows
   amd64/arm64. Declares Python ≥3.10, documented 3.10–3.14. ISC licence, last release
   2026-02-01, bundles V8 14.4.
2. **The pinned Flint bundle runs under it.** All five backends compile. Ten theme presets
   and `recommendChartTypes` are reachable. `theme_spec` is still silently ignored by
   ECharts and Chart.js — that is Flint, not the engine.
3. **Hypothesis confirmed: 705/705 agreement with Node, no date normalisation.**
   PythonMonkey was 695/705 on the same corpus; its ten failures are all `dates_year_month`,
   and `Date.parse("Jan 2020")` is `NaN` in that process. MiniRacer's parse of the same
   string is byte-identical to this machine's Node (`1577817000000`).
4. **MiniRacer has real isolates.** A second `MiniRacer()` is a second isolate. Four extra
   isolates cost +22.9 MB (5.7 MB each), in the same band as QuickJS contexts (5.2 MB in
   ADR-0001). Sharing one isolate across four threads **survived**. Thread scaling is weak
   (1.3× serial on four threads vs QuickJS's 2.6×).
5. **STPyV8 is V8, and is not shippable on our matrix.** No Linux aarch64 wheel on 13.1.201.22
   (released 2025-01-09). On this Mac it compiled Flint and matched Node on every fixture
   that ran, but four `gallery_kpi_card` cases died with `Internal error. Icu error.` ICU
   data is a filesystem layout, not a wheel.
6. **ADR-0001's import-co-load claim is false on this machine.** `import quickjs` then
   `import pythonmonkey`, a trivial eval, and 200 Flint compiles each, in either order, all
   survived. The SIGSEGVs we saw were **threads**, and they cluster on PythonMonkey or on
   sharing a QuickJS context — the hazard ADR-0001 already evidenced in `harness.py bench`.
7. **MiniRacer and vl-convert's V8 co-exist, including concurrently.** That pairing is the
   one #23 would actually need if rasterisation stays in-process. QuickJS also co-existed
   with MiniRacer and with vl-convert under one-thread-per-engine compile. PythonMonkey
   did not: every threads cell that included it died SIGSEGV (exit 139).
8. **WASM-hosted QuickJS runs Flint, and is not the oracle.** `quickjs-rs` (quickjs-ng via
   wasmtime) loaded the IIFE, compiled, and agreed with Node on 49/50 sampled fixtures.
   The one disagreement is `dates_date_datetime`. Cost is worse than native QuickJS
   (VL p50 1.09 ms, +81.6 MB, 1,423 compiles/s).

---

## 1. Which Python V8 bindings exist, and which survive the wheel gate

PRD §13 pins CPython 3.11–3.14 on macOS arm64, Linux x86_64, and Linux arm64. The ticket
is explicit: a binding without wheels on that matrix is disqualifying regardless of merit.
Tags below are from the PyPI JSON API for each package's current version, fetched
2026-08-21.

### 1.1 `mini-racer` 0.14.1 — passes

[bpcreech/PyMiniRacer](https://github.com/bpcreech/PyMiniRacer), PyPI
[`mini-racer`](https://pypi.org/project/mini-racer/) (not the abandoned `py-mini-racer`).
ctypes wrapper around a bundled V8. Documented Python 3.10–3.14
([README](https://github.com/bpcreech/PyMiniRacer/blob/v0.14.1/README.md)).
0.14.1 (2026-02-01) upgrades V8 14.3 → 14.4.

Wheels on 0.14.1, all `py3-none` (one wheel per platform, every CPython):

| tag | covers |
| --- | --- |
| `macosx_11_0_arm64` | macOS arm64 |
| `macosx_10_9_x86_64` | macOS x86_64 |
| `manylinux_2_27_aarch64` | Linux arm64 |
| `manylinux_2_27_x86_64` | Linux x86_64 |
| `musllinux_1_2_aarch64` / `_x86_64` | Alpine |
| `win_amd64` / `win_arm64` | Windows |

The required three platforms are present. Installed size on this Mac: ~63.8 MB
(18.5 MB wheel). Licence: ISC
([LICENSE](https://github.com/bpcreech/PyMiniRacer/blob/main/LICENSE)).
V8 itself is BSD-3-Clause and ships inside the wheel.

The original Sqreen package `py-mini-racer` 0.6.0 has no arm64 wheels and is abandoned.

### 1.2 `stpyv8` 13.1.201.22 — fails the matrix

[cloudflare/stpyv8](https://github.com/cloudflare/stpyv8) (current GitHub home
[buffer/stpyv8](https://github.com/buffer/stpyv8)). Apache-2.0. Last release 2025-01-09.
CPython-tagged wheels for 3.9–3.14 on macOS arm64/x86_64, Linux x86_64, Windows amd64.
**Zero Linux aarch64 wheels** on this version or on the GitHub release assets.

That is the disqualifier. It was still measured on this Mac, because "does Flint run
under V8" is a separate question from "can we ship it." See §2.2. Installed size
~61.5 MB (the `_STPyV8` extension alone is 47 MB).

### 1.3 Others, briefly

| package | why it is out |
| --- | --- |
| `iv8` 0.1.4 | PyPI licence **Proprietary**. Browser-API emulation on V8, not a compiler host. |
| `dukpy` 0.6.0 | Duktape, not V8. Wheel matrix is fine; it cannot be the Node oracle. |
| `py-mini-racer` 0.6.0 | Abandoned predecessor. No arm64. |

Nothing else named in the ticket (`dukpy` included) is a maintained V8 embedding with
wheels on the matrix.

---

## 2. Does the pinned Flint bundle run?

Reuse of `prototypes/flint-embed/`: `setup.sh` already built `build/flint.iife.js`
(flint-chart 0.5.1) and the 705 fixtures. The glue is the same `compile` /
`structuredClone` polyfill as ADR-0001. Each engine in its own subprocess.

### 2.1 MiniRacer — yes, all five backends

```
miniracer: engine + 1.6 MB bundle loaded in 60 ms
  vegalite    6.22 ms     2335 bytes
  echarts     1.85 ms     1630 bytes
  chartjs     1.22 ms     1492 bytes
  plotly      1.51 ms     1636 bytes
  excel       0.82 ms      544 bytes
  themes (10): nyt, economist, swiss, nature, mckinsey, datawrapper,
               powerbi, powerbi-light, pop, cartoon
  recommendChartTypes -> ["Bar Chart"]
  theme_spec: vegalite yes; plotly yes; echarts NO; chartjs NO
```

(`harness.py smoke` with `FLINT_ENGINE=miniracer`.) First-compile times above are cold;
see §4 for p50 after warmup. MiniRacer launches a background asyncio loop; if
`Engine.close()` is skipped the process hangs at exit. That is why the first smoke in
this session needed to be killed. Use the `mini_racer()` context manager, as the
upstream README recommends.

Date probe, same process, versus Node on this machine:

| | `Date.parse("Jan 2020")` | `Date.parse("2020-01")` |
| --- | --- | --- |
| Node | `1577817000000` | `1577836800000` |
| MiniRacer | `1577817000000` | `1577836800000` |
| STPyV8 | `1577817000000` | `1577836800000` |
| PythonMonkey | `NaN` (`Invalid Date`) | (not the failing case) |
| `quickjs-rs` (QuickJS-NG / wasm) | `1577836800000` (UTC) | `1577836800000` |

`"Jan 2020"` is a valid Date under every V8 we tried, and `NaN` under SpiderMonkey.
That is the whole PythonMonkey fidelity gap.

### 2.2 STPyV8 — yes, with an ICU hole

Smoke succeeded (bundle eval 17 ms, first compile 5.95 ms). Parity: **701/705
executed**, four errors, zero disagreements among the ones that ran. The four failures
are all `gallery_kpi_card__*` and all the same exception:

```
TypeError: Internal error. Icu error.
```

STPyV8's own README requires copying `icudtl.dat` into
`/Library/Application Support/STPyV8` or `/usr/share/stpyv8`. That is a host layout,
not a wheel. QuickJS in ADR-0001 also diverged on `gallery_kpi_card`; this is the same
family, a different cause.

### 2.3 `quickjs-rs` (WASM) — yes, with a marshal footgun

`quickjs-rs` 0.2.5 is quickjs-ng compiled to `wasm32-wasip1`, driven by wasmtime 48.
Universal `py3-none-any` wheel plus a per-platform wasmtime wheel. MIT + Apache-2.0.
Python ≥3.11, which matches our floor.

Eval of a function-valued statement raises `MarshalError: cannot marshal a JS function
to Python`. The polyfill and the Flint IIFE both do that. Appending `;0` makes eval
return a number and the bundle loads. After that, `compile(...)` returning a JSON
string works. This is an API constraint, not a Flint incompatibility.

Flint ran: cold boot 49 ms, bundle eval 69 ms, first compile 1.14 ms.

---

## 3. Parity against `specs_node.json`

Same comparison as ADR-0001: both sides canonicalised in Python, `_`-prefixed keys
stripped, SHA-256 of sorted JSON. Node specs were already on disk from the ADR-0001
run (`build/specs_node.json`).

| engine | executed | errors | agrees with Node |
| --- | --- | --- | --- |
| MiniRacer 0.14.1 | 705/705 | 0 | **705/705** |
| STPyV8 13.1.201.22 | 701/705 | 4 (ICU) | 701/701 of those that ran |
| PythonMonkey (ADR-0001) | 705/705 | 0 | 695/705, 705/705 after ISO-8601 |
| QuickJS (ADR-0001) | 705/705 | 0 | 676/705 |
| `quickjs-rs` | 50 sampled | 0 | 49/50; the miss is `dates_date_datetime` |

The MiniRacer dump is `prototypes/flint-embed/build/specs_miniracer.json` (gitignored,
reproducible via `harness.py _dump miniracer`).

So the ISO-8601 rule in ADR-0001 Decision 3 remains good *hygiene* — locale date
strings are still a bad idea — but it is no longer a *correctness dependency* if the
compiler engine is V8.

WASM was a 50-fixture sample (15 date cases + 35 others), not the full corpus. The
single disagreement being a date fixture is consistent with QuickJS-NG not being V8.
A 705-fixture WASM run was not done.

---

## 4. Cost, isolation, threads

MiniRacer numbers from `harness.py _bench1 miniracer` on this machine, next to the
ADR-0001 table (QuickJS / PythonMonkey measured the same day, same host, same bundle):

| | QuickJS | PythonMonkey | MiniRacer | `quickjs-rs` |
| --- | --- | --- | --- | --- |
| Cold boot | 64 ms | 185 ms | **63 ms** | 49 ms + 69 ms bundle |
| Resident | +22 MB | +58 MB | **+61.6 MB** | +81.6 MB |
| Vega-Lite p50 | 0.63 ms | 0.12 ms | **0.24 ms** | 1.09 ms |
| ECharts p50 | 0.37 ms | 0.06 ms | **0.18 ms** | — |
| Serial throughput | 2,619/s | 19,055/s | **5,348/s** | 1,423/s |
| 4 extra realms | 5.2 MB each | n/a (one realm) | **5.7 MB each** | (not measured) |
| 4-thread scaling | 2.6× serial | n/a | **1.3× serial** | (not measured) |
| Shared realm × 4 threads | SIGSEGV | n/a | **survived** | (not measured) |
| Wheel / installed | ~2.2 MB | ~43 MB | ~19 MB wheel / ~64 MB | 0.8 MB + 8.3 MB wasmtime / ~29 MB |

MiniRacer is slower than PythonMonkey per compile (~2× Vega-Lite, ~3× ECharts) and
faster than QuickJS. Memory sits with PythonMonkey, not with QuickJS. Boot sits with
QuickJS, not with PythonMonkey.

**Isolates.** Upstream documents MiniRacer as "Thread safe" and "Re-usable contexts"
and "evaluates JavaScript code using a V8 isolate"
([API](https://bpcreech.com/PyMiniRacer/api/),
[README](https://github.com/bpcreech/PyMiniRacer/blob/v0.14.1/README.md)).
Two `MiniRacer()` instances both compiled Flint. Four extra isolates were 5.7 MB
each. Sharing one isolate across four threads survived (`harness.py _crash_miniracer`).
That combination — per-tenant isolate *and* no SIGSEGV on accidental sharing — is
exactly what ADR-0001's QuickJS fallback was paying for, minus the crash.

**GIL / scaling.** 1.3× on four threads is not "the binding releases the GIL" in the
QuickJS sense (2.6×). MiniRacer services V8 through a background asyncio loop per
instance; the Python call waits on `Future.result()`. Concurrent isolates work; they
do not scale linearly. The pool design can still be one isolate per tenant/thread.
It should not assume QuickJS-like throughput multiplication.

**Operational.** MiniRacer without `close()` hangs the interpreter. That is a pool
lifecycle constraint, not a crash.

---

## 5. Co-load

Two different claims live in ADR-0001. Only one had evidence coming in.

### 5.1 The evidenced one, unchanged

Sharing a QuickJS context across threads is a SIGSEGV. `harness.py bench` still
demonstrates it. Nothing here contradicts that. **One QuickJS context per thread,
structurally.**

### 5.2 The unevidenced note, now measured

> "The two engines segfault if imported into the same interpreter."
> (ADR-0001, after the engine table)

`prototypes/v8-embed-probe/coload_probe.py` runs each pairing in a subprocess.
Intensities: `import`, `eval` (6×7), `compile` (Flint ×200 each), `threads`
(one thread per engine, 80 compiles each — *not* sharing a context).

The #22 probe's missing `quickjs-then-pythonmonkey` control is also in
`prototypes/rasterisation-probe/coload_probe.py` now (still the light eval only).

**Import, eval, compile — every pairing survived**, including both orders of
QuickJS × PythonMonkey, and every crossing of MiniRacer / STPyV8 / vl-convert
with those two. On this Mac, at these workloads, the import-co-load claim is
**false**. A 6×7 eval surviving is no longer uncalibrated: 200 Flint compiles
survived too.

**Threads (one context each, two threads) — the split is clean:**

| pairing | threads |
| --- | --- |
| MiniRacer × vl-convert, either order | survived |
| MiniRacer × QuickJS, either order | survived |
| QuickJS × vl-convert, either order | survived |
| any pairing that includes PythonMonkey | SIGSEGV, exit 139 |
| any pairing that includes STPyV8 (except we did not finish STPyV8 × MiniRacer) | SIGSEGV, exit 139 |
| QuickJS × PythonMonkey | SIGSEGV, exit 139 |

An earlier threads design shared one QuickJS handle across two threads and crashed
almost everything that touched QuickJS. That was the known hazard, not co-load.
Those cells were re-run with one thread per engine; the table above is the re-run.

PythonMonkey's single global realm is not safe to drive from two threads, with or
without a second engine. That is a PythonMonkey constraint. It is not evidence that
"two engines cannot be imported."

**STPyV8 × MiniRacer is hostile in a different way.** `miniracer-then-stpyv8 / eval`
and `/ compile` survived; `/ threads` SIGSEGV. The reverse order hung: macOS logged
`[mutex.cc : 452] RAW: Lock blocking` and the eval cell timed out at 30 s. STPyV8
takes a `JSLocker` in `JSContext.__init__`; MiniRacer talks to V8 on a background
thread. That is a lock-order hazard, not a "V8 cannot live with V8" result — MiniRacer
× vl-convert (also V8, via deno) was fine.

**What this means for #23.** If rasterisation is `vl-convert` in the same process as
the compiler, the combination that was actually green under concurrent compile is
**MiniRacer + vl-convert**. QuickJS + vl-convert was also green. PythonMonkey +
vl-convert compiled serially and died as soon as two threads compiled at once.

**Linux is untested.** Same caveat #22 left. These SIGSEGV / survive results are one
macOS host.

The threaded cells raise macOS "Python quit unexpectedly" dialogs. That is Crash
Reporter observing a child SIGSEGV, not a host compromise. The matrix was stopped
once the split above was visible; STPyV8 × MiniRacer reverse-order eval/compile were
not re-tried, on purpose.

---

## 6. Licences, for anything shippable in Apache-2.0

| component | licence | source |
| --- | --- | --- |
| `mini-racer` | ISC | [LICENSE](https://github.com/bpcreech/PyMiniRacer/blob/main/LICENSE) |
| V8 (bundled in that wheel) | BSD-3-Clause | V8's own licence; ISC + BSD-3 are Apache-2.0-compatible |
| `stpyv8` | Apache-2.0 | PyPI / GitHub |
| `quickjs-rs` | MIT | [PyPI](https://pypi.org/project/quickjs-rs/) |
| wasmtime | Apache-2.0 | [wasmtime](https://github.com/bytecodealliance/wasmtime) |
| `iv8` | Proprietary | PyPI. Out. |
| `vl-convert-python` | BSD-3-Clause | already recorded in the rasterisation notes |

Nothing that passed the wheel gate is a licence problem for an Apache-2.0 library.
`iv8` would have been, and is out on that alone.

---

## 7. What the facts recommend the next ticket decide

Not decided here. The shape of the decision, given the measurements:

- MiniRacer is the only V8 binding that clears the wheel gate, runs Flint, and matches
  Node 705/705 with no date fix. It also supplies the isolate model ADR-0001 was using
  QuickJS as a fallback to get.
- PythonMonkey remains the throughput champion and the isolation dummy (one realm,
  and unsafe on threads next to anything).
- QuickJS remains the small, GIL-releasing fallback, further from V8, with a
  cross-thread SIGSEGV.
- If the compiler engine becomes MiniRacer, the QuickJS fallback may be unnecessary
  rather than complementary — isolates are already there — which would *simplify*
  ADR-0001 Decision 2's pool, not complicate it.
- In-process `vl-convert` next to MiniRacer is the co-load pairing that actually
  survived concurrent compile. That is an input to #23, not a rasterisation decision.

Amend-in-place, with a date, is what the ticket asked for if the facts recommend a
change. They do recommend putting that question on the map. They do not answer it.

---

## Open questions I could not settle

1. **Linux.** Every number is one macOS arm64 host. Wheel tags say Linux aarch64 and
   x86_64 exist for MiniRacer; behaviour, ICU, and co-load on Linux are unmeasured.
2. **Full WASM corpus.** 50 fixtures, not 705. Enough to know Flint runs and dates
   diverge; not enough to quote a 705/N.
3. **STPyV8 × MiniRacer reverse-order eval.** Hung once; not re-tried after we stopped
   the crash matrix. Irrelevant to shipping (STPyV8 fails the wheel gate) and useful
   only as a warning against two C++ V8 lockers in one process.
4. **Whether MiniRacer's 1.3× thread scaling is a GIL hold or a V8 isolate lock.**
   Distinguishing those does not change the pool shape (one isolate per tenant).
5. **Highcharts / no-fork.** Untouched. Out of scope, as on the map.
