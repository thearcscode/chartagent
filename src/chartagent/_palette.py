"""Colour-vision-deficiency scoring for ``colorblind_safe_palette`` (ADR-0024
erratum, #255).

Takes the saturated, non-background hues of a rasterised chart, simulates
protan, deutan and tritan vision (Machado et al. 2009, severity 1.0, applied
in linear RGB) and fails when two distinct hues land closer than
``MIN_SIMULATED_DELTA_E`` (CIE76) under any simulation. Every threshold lives
here, named, so ``pass`` means the same on every deployment."""

from __future__ import annotations

import colorsys
from dataclasses import dataclass

from chartagent._pixels import Raster

# A mark colour is "saturated" at or above this HSV saturation. Greys and
# near-greys (axes, gridlines, text, antialiasing against white) fall below.
SATURATION_FLOOR = 0.35
# Hues closer than this many degrees are one hue: a lighter and a darker red
# are one series colour, not two.
HUE_MERGE_DEGREES = 20.0
# A hue must cover at least this share of the saturated pixels to count, so
# antialiasing fringes between two marks never register as a third hue.
HUE_MIN_SHARE = 0.05
# Two distinct hues fail when, under any simulated deficiency, their CIE76
# distance falls below this. ~10 is a clearly-noticeable difference.
MIN_SIMULATED_DELTA_E = 10.0

_MACHADO = {
    "protan": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
    "deutan": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.011820, 0.042940, 0.968881),
    ),
    "tritan": (
        (1.255528, -0.076749, -0.178779),
        (-0.078411, 0.930809, 0.147602),
        (0.004733, 0.691367, 0.303900),
    ),
}

Rgb = tuple[int, int, int]
Vec = tuple[float, float, float]


@dataclass(frozen=True)
class PaletteVerdict:
    hue_count: int
    collapsed: bool


def score_palette(raster: Raster) -> PaletteVerdict:
    hues = _mark_hues(raster)
    for i, a in enumerate(hues):
        for b in hues[i + 1 :]:
            if _collapses(a, b):
                return PaletteVerdict(len(hues), True)
    return PaletteVerdict(len(hues), False)


def _mark_hues(raster: Raster) -> list[Rgb]:
    counts: dict[Rgb, int] = {}
    for pixel in raster.pixels:
        counts[pixel] = counts.get(pixel, 0) + 1
    if not counts:
        return []
    background = max(counts, key=lambda p: counts[p])
    saturated = {
        pixel: n
        for pixel, n in counts.items()
        if pixel != background and _hsv(pixel)[1] >= SATURATION_FLOOR
    }
    total = sum(saturated.values())
    clusters: list[tuple[float, dict[Rgb, int]]] = []
    for pixel in sorted(saturated, key=lambda p: -saturated[p]):
        hue = _hsv(pixel)[0]
        for anchor, members in clusters:
            if _hue_gap(anchor, hue) <= HUE_MERGE_DEGREES:
                members[pixel] = saturated[pixel]
                break
        else:
            clusters.append((hue, {pixel: saturated[pixel]}))
    return [
        max(members, key=lambda p: members[p])
        for _, members in clusters
        if sum(members.values()) >= HUE_MIN_SHARE * total
    ]


def _hsv(pixel: Rgb) -> Vec:
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in pixel))
    return h * 360, s, v


def _hue_gap(a: float, b: float) -> float:
    gap = abs(a - b) % 360
    return min(gap, 360 - gap)


def _collapses(a: Rgb, b: Rgb) -> bool:
    return any(
        _delta_e(_simulate(a, matrix), _simulate(b, matrix)) < MIN_SIMULATED_DELTA_E
        for matrix in _MACHADO.values()
    )


def _linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _simulate(pixel: Rgb, matrix: tuple[Vec, Vec, Vec]) -> Vec:
    lin = [_linear(c) for c in pixel]
    r, g, b = (
        min(max(sum(m * c for m, c in zip(row, lin)), 0.0), 1.0) for row in matrix
    )
    return r, g, b


def _lab(rgb: Vec) -> Vec:
    r, g, b = rgb
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _delta_e(a: Vec, b: Vec) -> float:
    return float(sum((p - q) ** 2 for p, q in zip(_lab(a), _lab(b))) ** 0.5)
