# PROTOTYPE — THROWAWAY

Measurement harness behind `docs/research/v8-embed.md`, which is research for
[issue #29](https://github.com/thearcscode/chartagent/issues/29). **Measurement
only — not the integration, and not a decision.** If the facts recommend a
change, an engine-decision ticket graduates from this one.

The question: ADR-0001 compared QuickJS and PythonMonkey and never recorded why
those two. The test oracle is Node/V8. Does a Python V8 binding exist that
covers the PRD's wheel matrix, runs the pinned Flint bundle, and matches Node
without date normalisation?

## What each probe answers

| script | question |
| --- | --- |
| `smoke.py` | Does the pinned Flint IIFE load and compile under mini-racer, STPyV8, and wasm-hosted QuickJS (`quickjs-rs`)? Date-parse behaviour vs Node? |
| `coload_probe.py` | Is ADR-0001's "the two engines segfault if imported into the same interpreter" claim true, and under what workload? Includes the missing `quickjs`↔`pythonmonkey` control, plus mini-racer, STPyV8, and vl-convert's V8. Each pairing × each intensity runs in its own subprocess. |
| `../flint-embed/harness.py` | Parity and bench, with `miniracer` added as an engine. Reuses the existing comparison logic. |

**Crash Reporter.** The `threads` intensity of `coload_probe.py` will SIGSEGV some
child processes (PythonMonkey under concurrent compile, STPyV8 lockers). That is
the measurement. macOS then shows "Python quit unexpectedly". Dismiss the dialogs;
do not run that intensity casually on a machine where the pop-ups matter.

## Setup

Depends on `../flint-embed` having been built (`./setup.sh` there). Install
candidates into that venv:

```
../flint-embed/.venv/bin/pip install mini-racer==0.14.1 stpyv8==13.1.201.22 quickjs-rs==0.2.5
```

`vl-convert-python`, `quickjs`, and `pythonmonkey` are already in that venv
from ADR-0001 / #22.

Then:

```
../flint-embed/.venv/bin/python smoke.py
../flint-embed/.venv/bin/python coload_probe.py
../flint-embed/.venv/bin/python ../flint-embed/harness.py smoke   # FLINT_ENGINE=miniracer
../flint-embed/.venv/bin/python ../flint-embed/harness.py parity
../flint-embed/.venv/bin/python ../flint-embed/harness.py bench
```
