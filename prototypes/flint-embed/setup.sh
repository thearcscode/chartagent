#!/usr/bin/env bash
# Builds the pinned Flint bundle and fetches the fixture corpus. See README.md.
set -euo pipefail
cd "$(dirname "$0")"

FLINT_VERSION="$(tr -d '[:space:]' < FLINT_VERSION)"
FIXTURE_COMMIT="$(tr -d '[:space:]' < FIXTURE_COMMIT)"
BUILD="build"
mkdir -p "$BUILD"

echo "==> packing flint-chart@${FLINT_VERSION}"
rm -rf "$BUILD/npm" && mkdir -p "$BUILD/npm"
( cd "$BUILD/npm" && npm pack "flint-chart@${FLINT_VERSION}" >/dev/null && tar xzf flint-chart-*.tgz )

echo "==> bundling to a single platform-neutral file"
npx -y esbuild "$BUILD/npm/package/dist/index.js" \
  --bundle --format=iife --global-name=Flint \
  --platform=neutral --target=es2020 \
  --outfile="$BUILD/flint.iife.js"

# The compiler must not reach for a host runtime. If this trips, the embedding
# premise is broken and the ADR needs revisiting.
if grep -qE 'process\.|Buffer\.|__dirname|require\(' "$BUILD/flint.iife.js"; then
  echo "!! bundle references a Node global — investigate before trusting the embed" >&2
  exit 1
fi
echo "    $(du -h "$BUILD/flint.iife.js" | cut -f1), no Node globals"

echo "==> fetching fixtures at ${FIXTURE_COMMIT}"
if [ ! -d "$BUILD/fixtures" ]; then
  rm -rf "$BUILD/repo"
  git clone --depth 1 --filter=blob:none --sparse \
      https://github.com/microsoft/flint-chart.git "$BUILD/repo" >/dev/null 2>&1
  ( cd "$BUILD/repo" \
    && git sparse-checkout set shared/test-data >/dev/null \
    && git fetch --depth 1 origin "${FIXTURE_COMMIT}" >/dev/null 2>&1 \
    && git checkout -q "${FIXTURE_COMMIT}" 2>/dev/null || true )
  mv "$BUILD/repo/shared/test-data" "$BUILD/fixtures"
  rm -rf "$BUILD/repo"
fi
echo "    $(find "$BUILD/fixtures" -maxdepth 1 -type d | tail -n +2 | wc -l | tr -d ' ') fixture cases"

echo "==> done. next: .venv/bin/python harness.py smoke"
