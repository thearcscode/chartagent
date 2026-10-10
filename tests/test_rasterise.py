"""``Rasteriser`` — the protocol, vendor-asset loading, and a real end-to-end
render through the reference ``BrowserRasteriser`` (ADR-0003, ADR-0005
Decision 9, #201).

The end-to-end tests reuse the exact vendored, hash-pinned renderer stack
the corpus recorder's own paint harness already ships at
``tools/paint/vendor`` (issues #126/#127) — real Chromium, real Flint, real
per-backend renderers, no CDN, no stand-in backend. They are skipped when
``playwright``'s browsers are not installed, the same posture
``test_plan_live.py`` takes for a missing API key.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pyarrow as pa
import pytest

from chartagent.envelope import Envelope
from chartagent.errors import RasterisationError, RasteriserUnavailableError
from chartagent.rasterise import (
    BrowserRasteriser,
    Rasteriser,
    RendererAsset,
    load_vendored_renderers,
)
from chartagent.recipe import BoundDocument, ChartDocument

_REPO = Path(__file__).resolve().parents[1]
_VENDOR_DIR = _REPO / "tools" / "paint" / "vendor"


def _playwright_chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            browser.close()
    except Exception:
        return False
    return True


pytestmark_live = pytest.mark.skipif(
    not _VENDOR_DIR.is_dir() or not _playwright_chromium_available(),
    reason="tools/paint/vendor or a Chromium install is unavailable",
)


class _FakeRasteriser:
    def rasterise(self, target: Envelope, *, format: str = "png") -> bytes:
        return b"png-bytes"


def test_fake_rasteriser_satisfies_the_protocol() -> None:
    assert isinstance(_FakeRasteriser(), Rasteriser)


def test_renderer_asset_is_an_ordered_tuple_of_sources() -> None:
    asset = RendererAsset(sources=(b"a", b"b"))
    assert asset.sources == (b"a", b"b")


@pytest.mark.skipif(not _VENDOR_DIR.is_dir(), reason="tools/paint/vendor is missing")
def test_load_vendored_renderers_reads_all_four_backends() -> None:
    renderers = load_vendored_renderers(_VENDOR_DIR)
    assert set(renderers) == {"vegalite", "echarts", "chartjs", "plotly"}
    assert len(renderers["vegalite"].sources) == 3  # vega, vega-lite, vega-embed
    assert len(renderers["echarts"].sources) == 1
    for asset in renderers.values():
        assert all(len(source) > 0 for source in asset.sources)


@pytest.mark.skipif(not _VENDOR_DIR.is_dir(), reason="tools/paint/vendor is missing")
def test_load_vendored_renderers_rejects_a_tampered_file(tmp_path: Path) -> None:
    copy_dir = tmp_path / "vendor"
    shutil.copytree(_VENDOR_DIR, copy_dir)
    target = copy_dir / "echarts.min.js"
    target.write_bytes(target.read_bytes() + b"tampered")
    with pytest.raises(RasterisationError, match="sha256"):
        load_vendored_renderers(copy_dir)


def test_load_vendored_renderers_reports_a_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(RasterisationError, match="manifest"):
        load_vendored_renderers(tmp_path)


def test_rasteriser_protocol_admits_a_bound_document_target() -> None:
    doc = ChartDocument(module="function render(){}", styles=None, libraries=())
    bound = BoundDocument(
        document=doc, rows=pa.table({"x": [1]}), theme={}, libraries={}
    )

    class _StubRasteriser:
        def rasterise(self, target: object, *, format: str = "png") -> bytes:
            return b"x"

    assert isinstance(_StubRasteriser(), Rasteriser)
    # BoundDocument itself is constructible and typed as the protocol's
    # second union member (ADR-0005 Decision 9's frozen erratum) even though
    # nothing can rasterise one yet.
    assert bound.document is doc


def test_browser_rasteriser_raises_when_playwright_is_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "playwright", None)
    for name in list(sys.modules):
        if name.startswith("playwright."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    with pytest.raises(RasteriserUnavailableError) as caught:
        BrowserRasteriser({})
    assert caught.value.extra == "chartagent[review]"


# ---------------------------------------------------------------------------
# Real end-to-end: an actual browser, the actual pinned Flint bundle, the
# actual vendored renderers.
# ---------------------------------------------------------------------------


def _envelope(backend: str) -> Envelope:
    return Envelope(
        flint_version="0.5.1",
        backend=backend,  # type: ignore[arg-type]
        input={
            "data": {
                "values": [
                    {"quarter": "Q1", "revenue": 1200},
                    {"quarter": "Q2", "revenue": 1450},
                    {"quarter": "Q3", "revenue": 980},
                    {"quarter": "Q4", "revenue": 1800},
                ]
            },
            "semantic_types": {"quarter": "Quarter", "revenue": "Revenue"},
            "chart_spec": {
                "chartType": "Bar Chart",
                "title": "Revenue by quarter",
                "encodings": {"x": {"field": "quarter"}, "y": {"field": "revenue"}},
                "baseSize": {"width": 480, "height": 320},
            },
        },
        row_count=4,
        elapsed=0.0,
        warnings=(),
        source_schema=None,
    )


_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytestmark_live
@pytest.mark.parametrize("backend", ["vegalite", "echarts", "chartjs", "plotly"])
def test_browser_rasteriser_returns_a_real_png_for_every_rasterisable_backend(
    backend: str,
) -> None:
    renderers = load_vendored_renderers(_VENDOR_DIR)
    with BrowserRasteriser(renderers, width=480, height=320) as rasteriser:
        png = rasteriser.rasterise(_envelope(backend))
    assert png.startswith(_PNG_MAGIC)
    # A blank canvas at this size compresses far smaller than an actual bar
    # chart with axes, ticks and four bars drawn on it.
    assert len(png) > 2000


@pytestmark_live
def test_browser_rasteriser_raises_on_excel() -> None:
    renderers = load_vendored_renderers(_VENDOR_DIR)
    with BrowserRasteriser(renderers) as rasteriser:
        with pytest.raises(RasterisationError, match="excel"):
            rasteriser.rasterise(_envelope("excel"))


_PAINTING_MODULE = """
function render(data, el) {
  el.style.background = "#fff";
  var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", "100%");
  svg.setAttribute("height", "100%");
  data.forEach(function (row, i) {
    var r = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    r.setAttribute("x", String(10 + i * 40));
    r.setAttribute("y", String(120 - row.v));
    r.setAttribute("width", "30");
    r.setAttribute("height", String(row.v));
    r.setAttribute("fill", "#d62728");
    svg.appendChild(r);
  });
  el.appendChild(svg);
  window.__rows = data;
}
function getPlottedSeries() {
  return window.__rows.map(function (row) {
    return { series: "s", x: row.k, y: row.v };
  });
}
"""


def _bound(module: str = _PAINTING_MODULE, **kwargs: object) -> BoundDocument:
    doc = ChartDocument(module=module, styles=None, libraries=())
    return BoundDocument(
        document=doc,
        rows=pa.table({"k": ["a", "b", "c"], "v": [30, 60, 90]}),
        theme={},
        libraries={},
        **kwargs,  # type: ignore[arg-type]
    )


@pytestmark_live
def test_paint_document_returns_one_paints_png_and_declaration() -> None:
    with BrowserRasteriser({}, width=480, height=320) as rasteriser:
        painted = rasteriser.paint_document(_bound())
    assert painted.png.startswith(_PNG_MAGIC)
    assert len(painted.png) > 1000
    assert painted.declaration == [
        {"series": "s", "x": "a", "y": 30},
        {"series": "s", "x": "b", "y": 60},
        {"series": "s", "x": "c", "y": 90},
    ]


@pytestmark_live
def test_rasterise_bound_document_returns_png_bytes() -> None:
    with BrowserRasteriser({}, width=480, height=320) as rasteriser:
        png = rasteriser.rasterise(_bound())
    assert png.startswith(_PNG_MAGIC)


@pytestmark_live
def test_paint_uses_the_rasterisers_own_width_and_height() -> None:
    import struct

    with BrowserRasteriser({}, width=480, height=320) as rasteriser:
        png = rasteriser.paint_document(_bound()).png
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (480, 320)


@pytestmark_live
@pytest.mark.parametrize(
    "module",
    [
        "function render(d, el) { throw new Error('boom'); }\n"
        "function getPlottedSeries() { return []; }",
        "function getPlottedSeries() { return []; }",
        "function render(d, el) { el.textContent = 'x'; }",
        "function render(d, el) {}\nfunction getPlottedSeries() { return []; }",
    ],
    ids=["throwing-render", "missing-render", "missing-symbol", "empty-container"],
)
def test_a_broken_document_raises_rasterisation_error(module: str) -> None:
    with BrowserRasteriser({}) as rasteriser:
        with pytest.raises(RasterisationError):
            rasteriser.paint_document(_bound(module))


@pytestmark_live
def test_a_hanging_render_raises_rasterisation_error() -> None:
    module = (
        "function render(d, el) { while (true) {} }\n"
        "function getPlottedSeries() { return []; }"
    )
    with BrowserRasteriser({}, timeout=1.0) as rasteriser:
        with pytest.raises(RasterisationError):
            rasteriser.paint_document(_bound(module))


@pytestmark_live
def test_a_bad_library_pin_is_an_assembly_error_not_a_rasterisation_error() -> None:
    from chartagent.errors import DocumentAssemblyError
    from chartagent.recipe import LibraryPin

    pin = LibraryPin(name="lib", version="1", sha256="0" * 64)
    doc = ChartDocument(module=_PAINTING_MODULE, styles=None, libraries=(pin,))
    bound = BoundDocument(
        document=doc, rows=pa.table({"k": ["a"], "v": [1]}), theme={}, libraries={}
    )
    with BrowserRasteriser({}) as rasteriser:
        with pytest.raises(DocumentAssemblyError):
            rasteriser.paint_document(bound)


@pytestmark_live
def test_paint_makes_no_network_request() -> None:
    module = (
        "function render(d, el) { el.textContent = 'x'; "
        "fetch('http://example.invalid/'); "
        "var i = new Image(); i.src = 'http://example.invalid/a.png'; "
        "el.appendChild(i); }\n"
        "function getPlottedSeries() { return [{series:'s', x:'a', y:1}]; }"
    )
    with BrowserRasteriser({}) as rasteriser:
        seen: list[str] = []
        original = rasteriser._browser.new_page

        def spy(**kw: object) -> object:
            page = original(**kw)
            page.on("response", lambda r: seen.append(r.url))
            return page

        rasteriser._browser.new_page = spy
        rasteriser.paint_document(_bound(module))
    assert not [u for u in seen if u.startswith("http")]


@pytestmark_live
def test_browser_rasteriser_raises_when_no_renderer_is_vendored_for_the_backend() -> (
    None
):
    renderers = load_vendored_renderers(_VENDOR_DIR)
    del renderers["echarts"]
    with BrowserRasteriser(renderers) as rasteriser:
        with pytest.raises(RasterisationError, match="echarts"):
            rasteriser.rasterise(_envelope("echarts"))


@pytestmark_live
def test_browser_rasteriser_raises_on_an_unparseable_spec() -> None:
    renderers = load_vendored_renderers(_VENDOR_DIR)
    envelope = _envelope("vegalite")
    envelope.input["chart_spec"]["chartType"] = "Not A Real Chart Type"
    with BrowserRasteriser(renderers) as rasteriser:
        with pytest.raises(RasterisationError, match="compile"):
            rasteriser.rasterise(envelope)
