from __future__ import annotations

import subprocess
import sys

_FORBIDDEN = (
    "langgraph",
    "deepagents",
    "pythonmonkey",
    "quickjs",
    "py_mini_racer",
    "mini_racer",
    "pydantic_ai",
    "anthropic",
    "openai",
)


def test_import_does_not_load_js_engine_or_agent_stack() -> None:
    forbidden = ", ".join(repr(name) for name in _FORBIDDEN)
    script = f"""
import sys
import chartagent  # noqa: F401

forbidden = [{forbidden}]
loaded = [
    name
    for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
]
assert not loaded, loaded
"""
    subprocess.run([sys.executable, "-c", script], check=True)
