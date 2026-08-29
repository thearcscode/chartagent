"""Serve the pinned Flint IIFE. Callers never read `_bundle/` themselves."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

_PACKAGE_DIR = Path(__file__).resolve().parent
_IIFE_PATH = _PACKAGE_DIR / "_bundle" / "flint.iife.js"
_PIN_PATH = _PACKAGE_DIR / "frame" / "vocab.json"


class _PinRecord(TypedDict):
    flint_version: str
    bundle_sha256: str


@dataclass(frozen=True)
class FlintBundle:
    """The pinned Flint IIFE this install serves.

    The directory stays private; `flint_bundle()` is the seam (ADR-0005
    Decision 8). A CDN fetch at the same version string is not equivalent —
    the IIFE carries no version string, and compiled output moves between
    builds at one version number.
    """

    path: Path
    version: str
    sha256: str

    def read_bytes(self) -> bytes:
        return self.path.read_bytes()


def flint_bundle() -> FlintBundle:
    """Return the vendored Flint pin this wheel was built against."""
    pin = cast(_PinRecord, json.loads(_PIN_PATH.read_text(encoding="utf-8")))
    return FlintBundle(
        path=_IIFE_PATH,
        version=pin["flint_version"],
        sha256=pin["bundle_sha256"],
    )
