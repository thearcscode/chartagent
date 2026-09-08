from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_PREDICATES = _REPO / "tools" / "flint-predicates.mjs"
_LIB = _REPO / "tools" / "flint-lib.mjs"

# Files that legitimately define their own strip/canon copy rather than
# importing flint-predicates.mjs (ADR-0004 Decision 7: the probe is
# measurement-only and reuses nothing).
_DUPLICATE_ALLOWED = {_REPO / "prototypes" / "flint-frame" / "probe.mjs"}

_NODE_IMPORT = re.compile(r"""\bfrom\s+["']node:|require\(\s*["']node:""")
_BUILTIN_BARE_IMPORT = re.compile(
    r"""\bfrom\s+["'](fs|path|vm|os|child_process|url|crypto)["']"""
)


_VENDORED_DIR_NAMES = {"node_modules", "build", "dist"}


def _mjs_files() -> list[Path]:
    # Excludes vendored/built third-party output (e.g.
    # prototypes/rasterisation-probe/build/.../dist/echarts.esm.mjs) — the
    # single-definition guarantee is about our own source, not bundled deps.
    return [
        p
        for p in _REPO.rglob("*.mjs")
        if ".git" not in p.parts and _VENDORED_DIR_NAMES.isdisjoint(p.parts)
    ]


def _run_node(*args: str) -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH")
    return subprocess.run([node, *args], capture_output=True, text=True)


def test_predicates_module_has_no_node_imports_or_fs_access() -> None:
    source = _PREDICATES.read_text(encoding="utf-8")
    code_lines = [
        line for line in source.splitlines() if not line.strip().startswith("//")
    ]
    code = "\n".join(code_lines)
    assert not _NODE_IMPORT.search(code), "must not import node: builtins"
    assert not _BUILTIN_BARE_IMPORT.search(code), "must not import fs/path/vm/os/etc."


def test_predicates_module_runs_under_node_permission_model_with_no_fs_grant() -> None:
    script = f"""
import('{_PREDICATES.as_uri()}').then((m) => {{
  const pinned = m.pinSize({{ chart_spec: {{ baseSize: {{ w: 4, h: 3 }} }} }});
  if (pinned.chart_spec.canvasSize.w !== 4) throw new Error('pinSize broken');
  if (m.rowCount({{ _dataLength: 7 }}) !== 7) throw new Error('rowCount broken');
  const stripped = m.canon({{ b: 1, a: 2, _x: 9 }});
  if (stripped !== '{{"a":2,"b":1}}') throw new Error('canon/strip broken');
  const cloned = m.clone({{ a: [1, 2, 3] }});
  if (cloned.a.length !== 3) throw new Error('clone broken');
  console.log('OK');
}});
"""
    result = _run_node("--permission", f"--allow-fs-read={_PREDICATES}", "-e", script)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_flint_lib_reexports_the_same_functions_by_identity() -> None:
    script = f"""
const predicates = await import('{_PREDICATES.as_uri()}');
const lib = await import('{_LIB.as_uri()}');
for (const name of ['rowCount', 'pinSize', 'strip', 'canon', 'clone']) {{
  if (lib[name] !== predicates[name]) throw new Error(name + ' not re-exported');
}}
console.log('OK');
"""
    result = _run_node("--input-type=module", "-e", script)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_row_count_and_pin_size_have_exactly_one_definition_in_the_repo() -> None:
    # clone has no ADR-sanctioned duplicate anywhere (unlike strip/canon,
    # which probe.mjs is allowed to keep per ADR-0004 Decision 7), so it gets
    # the same single-definition guarantee the acceptance criteria name.
    definition = re.compile(
        r"^(export\s+)?function\s+(rowCount|pinSize|clone)\s*\(", re.MULTILINE
    )
    hits: dict[str, list[Path]] = {"rowCount": [], "pinSize": [], "clone": []}
    for path in _mjs_files():
        if path in _DUPLICATE_ALLOWED:
            continue
        text = path.read_text(encoding="utf-8")
        for match in definition.finditer(text):
            hits[match.group(2)].append(path)
    assert hits["rowCount"] == [_PREDICATES], hits["rowCount"]
    assert hits["pinSize"] == [_PREDICATES], hits["pinSize"]
    assert hits["clone"] == [_PREDICATES], hits["clone"]


def test_moved_predicates_do_not_enter_the_python_facade() -> None:
    import chartagent

    names = set(chartagent.__all__)
    assert names.isdisjoint({"rowCount", "pinSize", "strip", "canon", "clone"})
