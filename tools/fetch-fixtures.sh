#!/usr/bin/env bash
# Fetch the 705-fixture corpus at the pinned tag. Never skip. Never || true.
# Does not read expected.json.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/prototypes/flint-embed/FLINT_VERSION")"
COMMIT="$(tr -d '[:space:]' < "$ROOT/prototypes/flint-embed/FIXTURE_COMMIT")"
DEST="${1:-$ROOT/build/fixtures}"
REPO="${DEST}.repo"

rm -rf "$DEST" "$REPO"
mkdir -p "$(dirname "$DEST")"

echo "==> fetching flint-chart@${VERSION} fixtures (never cached)"
git clone --depth 1 --branch "$VERSION" --filter=blob:none --sparse \
  https://github.com/microsoft/flint-chart.git "$REPO"
git -C "$REPO" sparse-checkout set shared/test-data

HEAD="$(git -C "$REPO" rev-parse HEAD)"
HEAD_LC="$(printf '%s' "$HEAD" | tr '[:upper:]' '[:lower:]')"
COMMIT_LC="$(printf '%s' "$COMMIT" | tr '[:upper:]' '[:lower:]')"
if [[ "$HEAD_LC" != "$COMMIT_LC"* ]]; then
  echo "FIXTURE_COMMIT ${COMMIT} is not tag ${VERSION} (${HEAD})" >&2
  exit 1
fi

if [[ ! -d "$REPO/shared/test-data" ]]; then
  echo "sparse checkout did not produce shared/test-data" >&2
  exit 1
fi

mv "$REPO/shared/test-data" "$DEST"
rm -rf "$REPO"

COUNT="$(find "$DEST" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
if [[ "$COUNT" != "705" ]]; then
  echo "expected 705 fixtures, found ${COUNT}" >&2
  exit 1
fi
echo "    ${COUNT} fixtures at ${VERSION} (${HEAD})"
