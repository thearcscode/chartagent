#!/usr/bin/env bash
# Prove the narrowing gate fails on a real removal (0.2.1 → current).
# Uses the 0.2.1 IIFE the embed prototype already builds (facade-codegen/run.sh).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EMBED="$ROOT/prototypes/flint-embed/build"
OLD_IIFE="$EMBED/old/flint-0.2.1.iife.js"
OLD_VOCAB="${1:-$ROOT/build/vocab-0.2.1.json}"
NEW_VOCAB="${2:-$ROOT/src/chartagent/frame/vocab.json}"

if [[ ! -f "$OLD_IIFE" ]]; then
  echo "==> building the 0.2.1 bundle (comparison only)"
  mkdir -p "$EMBED/old"
  ( cd "$EMBED/old" \
    && npm pack flint-chart@0.2.1 >/dev/null \
    && tar xzf flint-chart-*.tgz \
    && npx -y esbuild package/dist/index.js \
         --bundle --format=iife --global-name=Flint \
         --platform=neutral --target=es2020 \
         --outfile=flint-0.2.1.iife.js )
fi

mkdir -p "$(dirname "$OLD_VOCAB")"
node "$ROOT/tools/extract.mjs" "$OLD_IIFE" "$OLD_VOCAB" 0.2.1

set +e
if command -v uv >/dev/null 2>&1; then
  uv run python "$ROOT/tools/check_bump.py" "$OLD_VOCAB" "$NEW_VOCAB"
else
  python3 "$ROOT/tools/check_bump.py" "$OLD_VOCAB" "$NEW_VOCAB"
fi
status=$?
set -e

if [[ "$status" -eq 0 ]]; then
  echo "FAIL: check_bump exited 0 on 0.2.1 → current; a real removal must fail" >&2
  exit 1
fi
if [[ "$status" -ne 1 ]]; then
  echo "FAIL: check_bump exited ${status}" >&2
  exit 1
fi
echo "OK: check_bump failed on 0.2.1 → current (gate is proven to fail)"
