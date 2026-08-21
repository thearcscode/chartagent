#!/usr/bin/env bash
# PROTOTYPE — THROWAWAY. Fetches the ECharts bundle the SSR probes load.
#
# Unlike flint-chart, ECharts is not dependency-free (it needs zrender and tslib), so
# re-bundling `index.js` with esbuild from the npm tarball alone fails to resolve. The
# published `dist/echarts.js` is already a self-contained UMD build, and that is what
# echarts_ssr_probe.py loads into the embedded engine.
set -euo pipefail
cd "$(dirname "$0")"

ECHARTS_VERSION="${ECHARTS_VERSION:-5.6.0}"
mkdir -p build/npm
cd build/npm
npm pack "echarts@${ECHARTS_VERSION}" >/dev/null
tar xzf "echarts-${ECHARTS_VERSION}.tgz"
cd ../..

echo "==> $(du -h build/npm/package/dist/echarts.js | cut -f1)  build/npm/package/dist/echarts.js"
echo "    next: python dump_echarts.py && python echarts_ssr_probe.py quickjs"
