from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_CHECK_BUMP = _REPO / "tools" / "check_bump.py"
_VOCAB = _REPO / "src" / "chartagent" / "frame" / "vocab.json"


def _vocab(
    *,
    backends: dict[str, dict[str, object]] | None = None,
    channels: list[str] | None = None,
    semantic_types: list[str] | None = None,
    theme_presets: dict[str, object] | None = None,
    missing_exports: list[str] | None = None,
) -> dict[str, object]:
    types = semantic_types if semantic_types is not None else ["Quantity"]
    themes = theme_presets if theme_presets is not None else {"nyt": {"id": "nyt"}}
    return {
        "flint_version": "0.5.1",
        "bundle_sha256": "abc",
        "missing_exports": missing_exports or [],
        "channels": channels if channels is not None else ["x", "y"],
        "semantic_types": types,
        "theme_presets": themes,
        "backends": backends
        if backends is not None
        else {
            "vegalite": {
                "Rose Chart": {
                    "channels": ["x", "y"],
                    "properties": [
                        {
                            "key": "innerRadius",
                            "type": "continuous",
                            "options": None,
                            "min": 0,
                            "max": 100,
                            "step": 1,
                            "dependencies": [],
                        }
                    ],
                }
            }
        },
    }


def _run(
    old: dict[str, object], new: dict[str, object]
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as tmp:
        old_path = Path(tmp) / "old.json"
        new_path = Path(tmp) / "new.json"
        old_path.write_text(json.dumps(old), encoding="utf-8")
        new_path.write_text(json.dumps(new), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(_CHECK_BUMP), str(old_path), str(new_path)],
            check=False,
            capture_output=True,
            text=True,
        )


def test_property_removed_exits_nonzero() -> None:
    old = _vocab()
    new = _vocab(
        backends={
            "vegalite": {
                "Rose Chart": {
                    "channels": ["x", "y"],
                    "properties": [],
                }
            }
        }
    )
    result = _run(old, new)
    assert result.returncode == 1
    assert "PROPERTY REMOVED" in result.stdout
    assert "innerRadius" in result.stdout


def test_chart_type_removed_from_a_backend_exits_nonzero() -> None:
    old = _vocab()
    new = _vocab(backends={"vegalite": {}})
    result = _run(old, new)
    assert result.returncode == 1
    assert "CHART REMOVED" in result.stdout
    assert "vegalite|Rose Chart" in result.stdout
    assert "PROPERTY REMOVED" not in result.stdout


def test_property_retyped_exits_nonzero() -> None:
    new = _vocab()
    backends = new["backends"]
    assert isinstance(backends, dict)
    rose = backends["vegalite"]["Rose Chart"]
    assert isinstance(rose, dict)
    props = rose["properties"]
    assert isinstance(props, list)
    first = props[0]
    assert isinstance(first, dict)
    first["type"] = "binary"
    result = _run(_vocab(), new)
    assert result.returncode == 1
    assert "PROPERTY RETYPED" in result.stdout
    assert "continuous -> binary" in result.stdout


def test_enum_option_removed_exits_nonzero() -> None:
    def stacked(options: list[dict[str, str]]) -> dict[str, object]:
        return _vocab(
            backends={
                "vegalite": {
                    "Stacked Bar Chart": {
                        "channels": ["x", "y"],
                        "properties": [
                            {
                                "key": "stackMode",
                                "type": "discrete",
                                "options": options,
                                "min": None,
                                "max": None,
                                "step": None,
                                "dependencies": [],
                            }
                        ],
                    }
                }
            }
        )

    old = stacked(
        [
            {"value": "normalize", "label": "Normalize"},
            {"value": "layered", "label": "Layered"},
        ]
    )
    new = stacked([{"value": "normalize", "label": "Normalize"}])
    result = _run(old, new)
    assert result.returncode == 1
    assert "OPTION REMOVED" in result.stdout
    assert "layered" in result.stdout


def test_backend_export_missing_exits_nonzero() -> None:
    old = _vocab()
    new = _vocab(missing_exports=["excelAllTemplateDefs"])
    result = _run(old, new)
    assert result.returncode == 1
    assert "BACKEND MISSING" in result.stdout
    assert "excelAllTemplateDefs" in result.stdout


def test_global_channel_removed_exits_nonzero() -> None:
    result = _run(_vocab(channels=["x", "y", "column"]), _vocab(channels=["x", "y"]))
    assert result.returncode == 1
    assert "CHANNEL REMOVED" in result.stdout
    assert "column" in result.stdout


def test_theme_preset_removed_exits_nonzero() -> None:
    result = _run(
        _vocab(theme_presets={"nyt": {"id": "nyt"}, "economist": {"id": "economist"}}),
        _vocab(theme_presets={"nyt": {"id": "nyt"}}),
    )
    assert result.returncode == 1
    assert "THEME REMOVED" in result.stdout
    assert "economist" in result.stdout


def test_semantic_type_removed_exits_nonzero() -> None:
    result = _run(
        _vocab(semantic_types=["Quantity", "Count"]),
        _vocab(semantic_types=["Quantity"]),
    )
    assert result.returncode == 1
    assert "SEMANTIC TYPE REMOVED" in result.stdout
    assert "Count" in result.stdout


def test_widening_only_exits_zero() -> None:
    old = _vocab(channels=["x", "y"])
    new = _vocab(channels=["x", "y", "column"], semantic_types=["Quantity", "Count"])
    result = _run(old, new)
    assert result.returncode == 0
    assert "OK" in result.stdout
    assert "FAIL" not in result.stdout


def _rose_with(
    *, channels: list[str], min_value: int, deps: list[str]
) -> dict[str, object]:
    return _vocab(
        backends={
            "vegalite": {
                "Rose Chart": {
                    "channels": channels,
                    "properties": [
                        {
                            "key": "innerRadius",
                            "type": "continuous",
                            "options": None,
                            "min": min_value,
                            "max": 100,
                            "step": 1,
                            "dependencies": deps,
                        }
                    ],
                }
            }
        }
    )


def test_per_type_channels_change_is_reported_not_fatal() -> None:
    old = _rose_with(channels=["x", "y"], min_value=0, deps=[])
    new = _rose_with(channels=["x", "y", "detail"], min_value=0, deps=[])
    result = _run(old, new)
    assert result.returncode == 0
    assert "REPORT" in result.stdout
    assert "CHANNELS" in result.stdout
    assert "FAIL" not in result.stdout


def test_slider_bounds_change_is_reported_not_fatal() -> None:
    old = _rose_with(channels=["x", "y"], min_value=0, deps=[])
    new = _rose_with(channels=["x", "y"], min_value=5, deps=[])
    result = _run(old, new)
    assert result.returncode == 0
    assert "REPORT" in result.stdout
    assert "BOUNDS" in result.stdout
    assert "FAIL" not in result.stdout


def test_dependencies_change_is_reported_not_fatal() -> None:
    result = _run(
        _rose_with(channels=["x", "y"], min_value=0, deps=[]),
        _rose_with(channels=["x", "y"], min_value=0, deps=["color"]),
    )
    assert result.returncode == 0
    assert "REPORT" in result.stdout
    assert "DEPENDENCIES" in result.stdout
    assert "FAIL" not in result.stdout


def test_array_option_values_are_not_flattened_to_strings() -> None:
    def mapped(options: list[object]) -> dict[str, object]:
        return _vocab(
            backends={
                "vegalite": {
                    "Map": {
                        "channels": ["latitude"],
                        "properties": [
                            {
                                "key": "projectionCenter",
                                "type": "discrete",
                                "options": options,
                                "min": None,
                                "max": None,
                                "step": None,
                                "dependencies": [],
                            }
                        ],
                    }
                }
            }
        )

    old = mapped(
        [
            {"value": [0, 0], "label": "origin"},
            {"value": "0,0", "label": "as-string"},
        ]
    )
    new = mapped([{"value": "0,0", "label": "as-string"}])
    result = _run(old, new)
    assert result.returncode == 1
    assert "OPTION REMOVED" in result.stdout
    assert "[0, 0]" in result.stdout or "[0,0]" in result.stdout


def test_committed_vocab_against_itself_is_widening_only() -> None:
    vocab = json.loads(_VOCAB.read_text(encoding="utf-8"))
    result = _run(vocab, vocab)
    assert result.returncode == 0
    assert "FAIL" not in result.stdout
