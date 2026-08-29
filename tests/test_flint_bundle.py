from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import chartagent
from chartagent import FlintBundle, flint_bundle

_REPO = Path(__file__).resolve().parents[1]
_PIN_DIR = _REPO / "prototypes" / "flint-embed"
_FLINT_VERSION = (_PIN_DIR / "FLINT_VERSION").read_text().strip()
_FIXTURE_COMMIT = (_PIN_DIR / "FIXTURE_COMMIT").read_text().strip()
_FLINT_REPO = "https://github.com/microsoft/flint-chart.git"


def test_sha256_matches_bytes_on_disk() -> None:
    bundle = flint_bundle()
    assert bundle.sha256 == hashlib.sha256(bundle.read_bytes()).hexdigest()


def test_version_matches_prototype_pin() -> None:
    assert flint_bundle().version == _FLINT_VERSION


def test_bundle_fields() -> None:
    bundle = flint_bundle()
    assert isinstance(bundle, FlintBundle)
    assert bundle.path.is_file()
    assert bundle.read_bytes() == bundle.path.read_bytes()


def test_fixture_commit_resolves_to_flint_version_tag() -> None:
    result = subprocess.run(
        [
            "git",
            "ls-remote",
            "--tags",
            _FLINT_REPO,
            f"refs/tags/{_FLINT_VERSION}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, f"no git tag {_FLINT_VERSION!r} on {_FLINT_REPO}"
    peeled: str | None = None
    direct: str | None = None
    for line in lines:
        sha, ref = line.split()
        if ref.endswith("^{}"):
            peeled = sha.lower()
        else:
            direct = sha.lower()
    remote_sha = peeled or direct
    assert remote_sha is not None
    recorded = _FIXTURE_COMMIT.lower()
    assert remote_sha.startswith(recorded), (
        f"FIXTURE_COMMIT {recorded!r} is not tag {_FLINT_VERSION!r} ({remote_sha})"
    )


def test_public_all() -> None:
    assert chartagent.__all__ == ["flint_bundle", "FlintBundle", "ChartAgentError"]
    for name in ("bind", "Envelope", "InputFrame", "vocabulary"):
        assert not hasattr(chartagent, name)
