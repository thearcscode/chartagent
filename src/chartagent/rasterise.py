"""``Rasteriser`` — the review gate's picture (ADR-0003, ADR-0005 Decision 9).

A ``typing.Protocol``, not an ABC: the library never hard-depends on a
rasteriser (ADR-0003 Decision 2), and structural typing lets a caller
implement it without importing a base class of ours. No knobs on the
protocol — size, scale and timeout belong on an implementation's
constructor (ADR-0005 Decision 9).

``BrowserRasteriser`` is the reference implementation: a real Chromium tab
running our pinned Flint bundle plus a caller-supplied per-backend renderer
runtime, screenshotting the delivered backend and nothing else (ADR-0003
Decision 3 — no stand-in, ever). Every script it loads is inlined into the
page before the page ever loads, so nothing is fetched over the network at
rasterise time at all — stricter than Decision 5's "never a CDN", which
named only the Flint IIFE.

``load_vendored_renderers`` reads a vendor manifest in the shape
``tools/paint/vendor/vendor.json`` already uses for the corpus recorder's
own paint harness (issues #126/#127) and verifies every file's sha256
before returning its bytes — a tampered or stale pin must never be loaded
silently. The library ships none of these bytes itself yet: packaging a
render stack into the wheel so ``chartagent[review]`` works from a bare
pip install, with no source checkout nearby, is follow-up packaging work,
not this ticket's (#201).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from chartagent._flint import flint_bundle
from chartagent.envelope import Envelope
from chartagent.errors import RasterisationError, RasteriserUnavailableError
from chartagent.frame.input import Backend
from chartagent.recipe import BoundDocument

_EXTRA = "chartagent[review]"

# Render-complete signal timeout for the two canvas backends (ECharts'
# 'finished' event, Chart.js' animation.onComplete hook) — mirrors
# tools/paint/harness.html's CANVAS_RENDER_TIMEOUT_MS. Vega-Lite and Plotly
# drive their own promise instead and are not bounded here.
_CANVAS_RENDER_TIMEOUT_MS = 5000

_RASTERISABLE: tuple[Backend, ...] = ("vegalite", "echarts", "chartjs", "plotly")


@runtime_checkable
class Rasteriser(Protocol):
    """Envelope (or a custom-rail ``BoundDocument``) in, PNG bytes out. The
    implementer owns compile-then-render.

    ``target``'s union is frozen at ADR-0005 Decision 9 as amended by
    ADR-0017 Decision 6 — ``Envelope | BoundDocument`` — even though nothing
    in the library constructs a ``BoundDocument`` yet (the custom-rail
    rendering path is a later ticket's). ``format`` is fixed at ``"png"``
    for v1 (ADR-0003 Decision 2). Raises
    :class:`~chartagent.errors.RasterisationError` on a failed render; never
    returns bytes for a chart it did not actually draw (ADR-0003's stated
    hazard — bytes without an exception is not proof of a render).
    """

    def rasterise(
        self, target: Envelope | BoundDocument, *, format: Literal["png"] = "png"
    ) -> bytes: ...


@dataclass(frozen=True)
class RendererAsset:
    """One backend's vendored rendering runtime.

    ``sources`` is one or more UMD/global browser builds, loaded as
    ``<script>`` tags in order — Vega-Lite needs three (Vega, Vega-Lite,
    Vega-Embed, in that order); ECharts, Chart.js and Plotly need one each.
    """

    sources: tuple[bytes, ...]


def load_vendored_renderers(vendor_dir: Path) -> dict[Backend, RendererAsset]:
    """Read ``vendor_dir/vendor.json`` plus its pinned files.

    Raises :class:`~chartagent.errors.RasterisationError` if a file is
    missing or its sha256 does not match the manifest — the same discipline
    the corpus recorder's ``tools/paint_corpus.py`` already applies to this
    exact vendor layout.
    """
    manifest_path = vendor_dir / "vendor.json"
    try:
        manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RasterisationError(f"no vendor manifest at {manifest_path}") from exc

    def _load(name: str) -> bytes:
        record = manifest.get(name)
        if not isinstance(record, dict):
            raise RasterisationError(f"vendor manifest has no entry for {name!r}")
        path = vendor_dir / str(record["file"])
        try:
            data: bytes = path.read_bytes()
        except OSError as exc:
            raise RasterisationError(
                f"{name}: vendored file missing at {path}"
            ) from exc
        actual = hashlib.sha256(data).hexdigest()
        if actual != record["sha256"]:
            raise RasterisationError(
                f"{name}: sha256 {actual} does not match the manifest "
                f"{record['sha256']!r} — vendored file is tampered or stale"
            )
        return data

    return {
        "vegalite": RendererAsset(
            sources=(_load("vega"), _load("vega-lite"), _load("vega-embed"))
        ),
        "echarts": RendererAsset(sources=(_load("echarts"),)),
        "chartjs": RendererAsset(sources=(_load("chart.js"),)),
        "plotly": RendererAsset(sources=(_load("plotly.js"),)),
    }


def _pin_size_js() -> str:
    # Mirrors tools/flint-predicates.mjs's pinSize: bakes chart_spec.baseSize
    # into canvasSize before compiling, never a size the harness invents.
    return """
    function pinSize(input) {
      var baseSize = input.chart_spec && input.chart_spec.baseSize;
      if (!baseSize) return input;
      var canvasSize = Object.assign({}, baseSize);
      var chartSpec = Object.assign({}, input.chart_spec, { canvasSize: canvasSize });
      return Object.assign({}, input, { chart_spec: chartSpec });
    }
    """


def _render_js(backend: Backend, *, width: int, height: int) -> str:
    return f"""
    {_pin_size_js()}
    window.__render = async function (input) {{
      var pinned = pinSize(input);
      var backend = {json.dumps(backend)};
      var assemble = {{
        vegalite: window.Flint.assembleVegaLite,
        echarts: window.Flint.assembleECharts,
        chartjs: window.Flint.assembleChartjs,
        plotly: window.Flint.assemblePlotly,
      }}[backend];

      var compiled;
      try {{
        compiled = assemble(pinned);
      }} catch (err) {{
        return {{ error: "compile: " + String((err && err.message) || err) }};
      }}

      var container = document.getElementById("container");
      var width = compiled._width || {width};
      var height = compiled._height || {height};
      container.style.width = width + "px";
      container.style.height = height + "px";

      try {{
        if (backend === "vegalite") {{
          var vlOpts = {{ renderer: "svg", actions: false }};
          await window.vegaEmbed(container, compiled, vlOpts);
        }} else if (backend === "plotly") {{
          var d = compiled.data, l = compiled.layout, c = compiled.config;
          await window.Plotly.newPlot(container, d, l, c);
        }} else if (backend === "echarts") {{
          var chart = window.echarts.init(container);
          await new Promise(function (resolve, reject) {{
            var timer = setTimeout(resolve, {_CANVAS_RENDER_TIMEOUT_MS});
            chart.on("finished", function () {{
              clearTimeout(timer);
              resolve();
            }});
            try {{
              chart.setOption(compiled);
            }} catch (err) {{
              clearTimeout(timer);
              reject(err);
            }}
          }});
        }} else if (backend === "chartjs") {{
          var canvas = document.createElement("canvas");
          container.appendChild(canvas);
          var config = Object.assign({{}}, compiled);
          await new Promise(function (resolve, reject) {{
            var timer = setTimeout(resolve, {_CANVAS_RENDER_TIMEOUT_MS});
            var oldAnim = config.options && config.options.animation;
            config.options = Object.assign({{}}, config.options, {{
              animation: Object.assign({{}}, oldAnim, {{
                onComplete: function () {{
                  clearTimeout(timer);
                  resolve();
                }},
              }}),
            }});
            try {{
              new window.Chart(canvas, config);
            }} catch (err) {{
              clearTimeout(timer);
              reject(err);
            }}
          }});
        }}
      }} catch (err) {{
        return {{ error: "render: " + String((err && err.message) || err) }};
      }}
      return {{ error: null }};
    }};
    window.__ready = true;
    """


def _harness_html(
    flint_source: bytes,
    renderer: RendererAsset,
    backend: Backend,
    *,
    width: int,
    height: int,
) -> str:
    scripts = "\n".join(
        f"<script>{source.decode('utf-8')}</script>" for source in renderer.sources
    )
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<script>{flint_source.decode("utf-8")}</script>
{scripts}
</head>
<body>
<div id="container" style="width:{width}px;height:{height}px"></div>
<script>{_render_js(backend, width=width, height=height)}</script>
</body>
</html>"""


class BrowserRasteriser:
    """The ADR-0003 reference ``Rasteriser``.

    ``renderers`` supplies the vendored per-backend rendering runtime
    (:func:`load_vendored_renderers` reads the same manifest layout the
    corpus recorder's paint harness already uses). Excel is never
    rasterisable (ADR-0003 Decision 7) and is never in ``renderers``.

    A context manager — ``close()`` (or ``with``) releases the browser
    process. Raises :class:`~chartagent.errors.RasteriserUnavailableError`
    at construction if the ``playwright`` extra is not installed.
    """

    def __init__(
        self,
        renderers: Mapping[Backend, RendererAsset],
        *,
        width: int = 640,
        height: int = 400,
        timeout: float = 10.0,
    ) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ModuleNotFoundError as exc:
            raise RasteriserUnavailableError(
                f"install {_EXTRA} for the reference Rasteriser", extra=_EXTRA
            ) from exc
        self._renderers = dict(renderers)
        self._width = width
        self._height = height
        self._timeout = timeout
        self._flint_source = flint_bundle().read_bytes()
        self._playwright: Any = sync_playwright().start()
        try:
            self._browser: Any = self._playwright.chromium.launch()
        except Exception:
            self._playwright.stop()
            raise

    def close(self) -> None:
        self._browser.close()
        self._playwright.stop()

    def __enter__(self) -> BrowserRasteriser:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def rasterise(
        self, target: Envelope | BoundDocument, *, format: Literal["png"] = "png"
    ) -> bytes:
        if isinstance(target, BoundDocument):
            # The custom-rail rendering path (build_shell, the sandboxed
            # iframe) is not built yet (ADR-0017 Decisions 10-12) — nothing
            # produces a BoundDocument today, so nothing here can paint one.
            raise RasterisationError(
                "BoundDocument rasterisation is not yet implemented"
            )
        backend = target.backend
        if backend not in _RASTERISABLE:
            raise RasterisationError(
                f"{backend} is not a raster target (ADR-0003 Decision 7)"
            )
        asset = self._renderers.get(backend)
        if asset is None:
            raise RasterisationError(f"no renderer vendored for backend: {backend!r}")

        html = _harness_html(
            self._flint_source, asset, backend, width=self._width, height=self._height
        )
        page = self._browser.new_page(
            viewport={"width": self._width, "height": self._height}
        )
        try:
            # Nothing is ever fetched — every byte is already inlined above —
            # but block network requests anyway as a defence in depth (a
            # Map/Choropleth spec could otherwise have Plotly reach for a
            # tile server).
            page.route("**/*", lambda route: route.abort())
            page.set_default_timeout(self._timeout * 1000)
            page.set_content(html, wait_until="load")
            page.wait_for_function("window.__ready === true")
            result = page.evaluate("(input) => window.__render(input)", target.input)
            error = (
                result.get("error") if isinstance(result, dict) else "render: no result"
            )
            if error:
                raise RasterisationError(error)
            return bytes(page.locator("#container").screenshot(type=format))
        finally:
            page.close()
