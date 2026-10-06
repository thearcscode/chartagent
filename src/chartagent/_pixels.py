"""Stdlib-only PNG decoding for the Tier-1 pixel checks (ADR-0024 erratum).

Reads the 8-bit, non-interlaced PNGs a browser screenshot produces. Anything
else is a rasteriser defect, so it raises ``RasterisationError`` rather than
becoming a fact about the chart. No dependency beyond ``zlib`` and ``struct``,
so the base wheel does not grow."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from chartagent.errors import RasterisationError

_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}


@dataclass(frozen=True)
class Raster:
    """``width * height`` pixels as one flat tuple of RGB triples; alpha is
    composited onto white."""

    width: int
    height: int
    pixels: tuple[tuple[int, int, int], ...]


def decode_png(data: bytes) -> Raster:
    try:
        return _decode(data)
    except (struct.error, zlib.error, IndexError, ValueError) as exc:
        raise RasterisationError(
            f"rasteriser returned an undecodable PNG: {exc}"
        ) from exc


def _decode(data: bytes) -> Raster:
    if not data.startswith(_SIGNATURE):
        raise ValueError("not a PNG")
    pos = len(_SIGNATURE)
    header: tuple[int, ...] | None = None
    idat = bytearray()
    while pos < len(data):
        (length,) = struct.unpack_from(">I", data, pos)
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    if header is None:
        raise ValueError("missing IHDR")
    width, height, depth, color_type, _, _, interlace = header
    if depth != 8 or interlace != 0 or color_type not in _CHANNELS:
        raise ValueError("only 8-bit non-interlaced greyscale/RGB(A) PNGs")
    channels = _CHANNELS[color_type]
    stride = width * channels
    raw = zlib.decompress(bytes(idat))
    if len(raw) != height * (stride + 1):
        raise ValueError("wrong decompressed size")

    pixels: list[tuple[int, int, int]] = []
    prior = bytearray(stride)
    for row in range(height):
        start = row * (stride + 1)
        line = bytearray(raw[start + 1 : start + 1 + stride])
        _unfilter(raw[start], line, prior, channels)
        for i in range(0, stride, channels):
            pixels.append(_rgb(line, i, color_type))
        prior = line
    return Raster(width, height, tuple(pixels))


def _unfilter(kind: int, line: bytearray, prior: bytearray, bpp: int) -> None:
    if kind == 0:
        return
    for i in range(len(line)):
        left = line[i - bpp] if i >= bpp else 0
        up = prior[i]
        up_left = prior[i - bpp] if i >= bpp else 0
        if kind == 1:
            add = left
        elif kind == 2:
            add = up
        elif kind == 3:
            add = (left + up) // 2
        elif kind == 4:
            add = _paeth(left, up, up_left)
        else:
            raise ValueError("bad filter type")
        line[i] = (line[i] + add) & 0xFF


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _rgb(line: bytearray, i: int, color_type: int) -> tuple[int, int, int]:
    if color_type == 0:
        g = line[i]
        return g, g, g
    if color_type == 4:
        g = _over_white(line[i], line[i + 1])
        return g, g, g
    r, g, b = line[i], line[i + 1], line[i + 2]
    if color_type == 6:
        a = line[i + 3]
        return _over_white(r, a), _over_white(g, a), _over_white(b, a)
    return r, g, b


def _over_white(value: int, alpha: int) -> int:
    return (value * alpha + 255 * (255 - alpha)) // 255
