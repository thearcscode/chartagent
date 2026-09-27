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

import pytest

from chartagent.envelope import Envelope
from chartagent.errors import RasterisationError, RasteriserUnavailableError
from chartagent.rasterise import (
    BrowserRasteriser,
    Rasteriser,
    RendererAsset,
    load_vendored_renderers,
)

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
