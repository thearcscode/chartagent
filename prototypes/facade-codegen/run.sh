#!/usr/bin/env bash
# PROTOTYPE — one command, no thinking required. See README.md.
set -euo pipefail
cd "$(dirname "$0")"

EMBED=../flint-embed/build
[ -f "$EMBED/flint.iife.js" ] || { echo "run ../flint-embed/setup.sh first" >&2; exit 1; }
mkdir -p build

# The old bundle exists only to prove the fail-loud gate catches a real removal.
if [ ! -f "$EMBED/old/flint-0.2.1.iife.js" ]; then
  echo "==> building the 0.2.1 bundle (comparison only)"
  mkdir -p "$EMBED/old" && ( cd "$EMBED/old" \
    && npm pack flint-chart@0.2.1 >/dev/null 2>&1 && tar xzf flint-chart-*.tgz \
    && npx -y esbuild package/dist/index.js --bundle --format=iife --global-name=Flint \
         --platform=neutral --target=es2020 --outfile=flint-0.2.1.iife.js >/dev/null 2>&1 )
fi

[ -d .venv ] || { python3 -m venv .venv && ./.venv/bin/pip install -q pydantic pytest; }

echo "==> extracting the vocabulary from each pinned bundle"
node extract.mjs "$EMBED/flint.iife.js"        build/vocab-0.5.1.json 0.5.1
node extract.mjs "$EMBED/old/flint-0.2.1.iife.js" build/vocab-0.2.1.json 0.2.1

echo "==> generating all three facade modes"
./.venv/bin/python generate.py build/vocab-0.5.1.json build/facade_keys.py     keys
./.venv/bin/python generate.py build/vocab-0.5.1.json build/facade_strict.py   strict
./.venv/bin/python generate.py build/vocab-0.5.1.json build/facade_advisory.py advisory

echo "==> the assertion: the facade admits what the bundle admits"
./.venv/bin/pytest test_facade.py -q

echo "==> the fail-loud gate on a version bump (expected to FAIL: 0.2.1 -> 0.5.1 removed keys)"
./.venv/bin/python check_bump.py build/vocab-0.2.1.json build/vocab-0.5.1.json || true
