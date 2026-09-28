"""``build_shell`` — the from-scratch iframe shell (ADR-0017, #208).

Pure-Python tests cover the return value: determinism, the frozen
``Shell``, its sandbox tokens, and every ``DocumentAssemblyError`` kind
this slice raises. The real-browser tests mount the shell in a sandboxed
iframe exactly as Studio will — real Chromium via Playwright, no CDN, no
stand-in — and are skipped when no Chromium is installed, the same posture
``test_rasterise.py`` takes (#201).

Paint-failure recovery (#209), iframe isolation beyond the CSP's script
policy (#210), CSS-scoping adversarial cases (#211), pinned-library load
order at scale (#212), size caps (#213) and safe embedding of adversarial
``</script>``/``<!--`` text (#214) are later tickets'.
"""

from __future__ import annotations

import dataclasses
import hashlib
import html
import inspect
from collections.abc import Iterator

import pyarrow as pa
import pytest

from chartagent import BoundDocument, DocumentAssemblyError, Shell, build_shell
from chartagent.errors import ChartAgentError
from chartagent.recipe import ChartDocument, LibraryPin
from chartagent.transform.serialize import serialize_rows


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
    not _playwright_chromium_available(), reason="no Chromium install available"
)

_RENDER_MODULE = """
window.__paintCount = 0;
function render(data, el) {
  window.__paintCount = (window.__paintCount || 0) + 1;
  el.textContent = JSON.stringify(data);
}
function getPlottedSeries() {
  return [{ series: "s", x: "a", y: 1 }];
}
"""


def _from_scratch_document(
    module: str = _RENDER_MODULE, styles: str | None = None
) -> ChartDocument:
    return ChartDocument(module=module, styles=styles, libraries=())


# --- Pure-Python: the return value --------------------------------------


def test_build_shell_takes_no_rows() -> None:
    params = list(inspect.signature(build_shell).parameters)
    assert params == ["document", "libraries"]


def test_shell_is_frozen() -> None:
    shell = build_shell(_from_scratch_document(), libraries={})
    assert isinstance(shell, Shell)
    with pytest.raises(dataclasses.FrozenInstanceError):
        shell.html = "tampered"  # type: ignore[misc]


def test_sandbox_tokens_are_exactly_allow_scripts() -> None:
    shell = build_shell(_from_scratch_document(), libraries={})
    assert shell.sandbox == ("allow-scripts",)
    assert "allow-same-origin" not in shell.sandbox


def test_build_shell_is_deterministic() -> None:
    document = _from_scratch_document()
    first = build_shell(document, libraries={})
    second = build_shell(document, libraries={})
    assert first == second


def test_empty_libraries_map_is_legal_for_a_from_scratch_document() -> None:
    shell = build_shell(_from_scratch_document(), libraries={})
    assert "function render" in shell.html


def test_contract_version_other_than_one_raises_contract_unsupported() -> None:
    document = _from_scratch_document()
    document = dataclasses.replace(document, contract_version=2)
    with pytest.raises(DocumentAssemblyError) as caught:
        build_shell(document, libraries={})
    assert caught.value.kind == "contract_unsupported"
    assert isinstance(caught.value, ChartAgentError)


def test_document_assembly_error_is_raised_only_here() -> None:
    # BoundDocument, the paintable counterpart, is untouched by this slice.
    doc = ChartDocument(module="x", styles=None, libraries=())
    bound = BoundDocument(
        document=doc, rows=pa.table({"x": [1]}), theme={}, libraries={}
    )
    assert bound.document is doc


def test_missing_pin_bytes_raise_pin_missing() -> None:
    pin = LibraryPin(name="chartjs", version="4.0.0", sha256="a" * 64)
    document = ChartDocument(module=_RENDER_MODULE, styles=None, libraries=(pin,))
    with pytest.raises(DocumentAssemblyError) as caught:
        build_shell(document, libraries={})
    assert caught.value.kind == "pin_missing"


def test_mismatched_pin_bytes_raise_pin_mismatch() -> None:
    blob = b"window.ChartLib = {};"
    wrong_sha = hashlib.sha256(b"not the real bytes").hexdigest()
    pin = LibraryPin(name="chartjs", version="4.0.0", sha256=wrong_sha)
    document = ChartDocument(module=_RENDER_MODULE, styles=None, libraries=(pin,))
    with pytest.raises(DocumentAssemblyError) as caught:
        build_shell(document, libraries={wrong_sha: blob})
    assert caught.value.kind == "pin_mismatch"


def test_a_blob_the_document_does_not_pin_is_ignored() -> None:
    document = _from_scratch_document()
    unrelated_sha = hashlib.sha256(b"unrelated").hexdigest()
    shell = build_shell(document, libraries={unrelated_sha: b"window.Unused = 1;"})
    assert "Unused" not in shell.html


def test_csp_allows_scripts_by_hash_only_with_no_unsafe_inline_or_eval() -> None:
    shell = build_shell(_from_scratch_document(), libraries={})
    csp_line = next(
        line for line in shell.html.splitlines() if "Content-Security-Policy" in line
    )
    assert "'unsafe-inline'" not in csp_line.split("script-src", 1)[1].split(";", 1)[0]
    assert "'unsafe-eval'" not in csp_line
    assert "script-src 'sha256-" in csp_line


# --- Real browser: mounting the shell exactly as Studio will -------------


def _iframe_harness(main_shell: Shell) -> str:
    sibling_html = "<!doctype html><html><body>sibling</body></html>"
    return f"""<!doctype html>
<html><body>
<iframe id="main" name="main" sandbox="{" ".join(main_shell.sandbox)}"
  srcdoc="{html.escape(main_shell.html)}"></iframe>
<iframe id="sibling" name="sibling" sandbox="allow-scripts"
  srcdoc="{html.escape(sibling_html)}"></iframe>
<script>
window.__acks = [];
window.addEventListener("message", function (e) {{ window.__acks.push(e.data); }});
</script>
</body></html>"""


@pytest.fixture()
def page() -> Iterator[object]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        pw_page = browser.new_page()
        yield pw_page
        browser.close()


@pytestmark_live
def test_from_scratch_document_paints_and_reports_true_with_declaration(
    page: object,
) -> None:
    shell = build_shell(_from_scratch_document(), libraries={})
    page.set_content(_iframe_harness(shell))  # type: ignore[attr-defined]
    page.wait_for_timeout(100)  # type: ignore[attr-defined]

    # The channel carries the JSON serialiser's output, not a hand-built
    # JSON string (ADR-0017 Decision 9; #208 AC1) — this is the seam's
    # first caller, and Studio is the second.
    rows, _ = serialize_rows(pa.table({"a": [1]}), {"a": "BIGINT"})
    page.evaluate(  # type: ignore[attr-defined]
        """(rows) => {
          window.frames["main"].postMessage(
            { type: "chartagent/paint", contractVersion: 1, rows: rows },
            "*"
          );
        }""",
        rows,
    )
    page.wait_for_function("() => window.__acks.length > 0")  # type: ignore[attr-defined]
    acks = page.evaluate("() => window.__acks")  # type: ignore[attr-defined]

    assert len(acks) == 1
    assert acks[0]["ok"] is True
    assert acks[0]["plottedSeries"] == [{"series": "s", "x": "a", "y": 1}]

    main = page.frame(name="main")  # type: ignore[attr-defined]
    assert main.evaluate("() => window.__paintCount") == 1
    container_text = main.evaluate(
        "() => document.getElementById('chartagent-container').textContent"
    )
    assert container_text == '[{"a":1}]'


@pytestmark_live
def test_a_re_read_without_a_redraw_returns_the_last_declaration(page: object) -> None:
    shell = build_shell(_from_scratch_document(), libraries={})
    page.set_content(_iframe_harness(shell))  # type: ignore[attr-defined]
    page.wait_for_timeout(100)  # type: ignore[attr-defined]

    rows, _ = serialize_rows(pa.table({"a": [1]}), {"a": "BIGINT"})
    page.evaluate(  # type: ignore[attr-defined]
        """(rows) => {
          window.frames["main"].postMessage(
            { type: "chartagent/paint", contractVersion: 1, rows: rows },
            "*"
          );
        }""",
        rows,
    )
    page.wait_for_function("() => window.__acks.length > 0")  # type: ignore[attr-defined]

    # A re-read: no render call, just getPlottedSeries() again.
    page.evaluate(  # type: ignore[attr-defined]
        """() => {
          window.frames["main"].postMessage(
            { type: "chartagent/read", contractVersion: 1 },
            "*"
          );
        }"""
    )
    page.wait_for_function("() => window.__acks.length > 1")  # type: ignore[attr-defined]
    acks = page.evaluate("() => window.__acks")  # type: ignore[attr-defined]

    assert len(acks) == 2
    assert acks[1]["ok"] is True
    assert acks[1]["plottedSeries"] == acks[0]["plottedSeries"]
    main = page.frame(name="main")  # type: ignore[attr-defined]
    # No second render — the container still holds the first paint's text.
    assert main.evaluate("() => window.__paintCount") == 1


@pytestmark_live
def test_message_from_a_sibling_frame_is_ignored(page: object) -> None:
    shell = build_shell(_from_scratch_document(), libraries={})
    page.set_content(_iframe_harness(shell))  # type: ignore[attr-defined]
    page.wait_for_timeout(100)  # type: ignore[attr-defined]

    sibling = page.frame(name="sibling")  # type: ignore[attr-defined]
    sibling.evaluate(
        """() => {
          window.parent.frames["main"].postMessage(
            {
              type: "chartagent/paint",
              contractVersion: 1,
              rows: [{ malicious: true }],
            },
            "*"
          );
        }"""
    )
    page.wait_for_timeout(200)  # type: ignore[attr-defined]

    main = page.frame(name="main")  # type: ignore[attr-defined]
    assert main.evaluate("() => window.__paintCount") == 0
    assert page.evaluate("() => window.__acks.length") == 0  # type: ignore[attr-defined]


@pytestmark_live
def test_csp_blocks_eval_and_dynamically_injected_scripts(page: object) -> None:
    module = (
        _RENDER_MODULE
        + """
try {
  eval("window.__evalRan = true");
} catch (e) {
  window.__evalBlocked = true;
}
var injected = document.createElement("script");
injected.textContent = "window.__injected = true;";
document.head.appendChild(injected);
"""
    )
    shell = build_shell(_from_scratch_document(module=module), libraries={})
    page.set_content(_iframe_harness(shell))  # type: ignore[attr-defined]
    page.wait_for_timeout(200)  # type: ignore[attr-defined]

    main = page.frame(name="main")  # type: ignore[attr-defined]
    assert main.evaluate("() => window.__evalRan") is None
    assert main.evaluate("() => window.__evalBlocked") is True
    assert main.evaluate("() => window.__injected") is None
    # The hash-allowed module itself still ran fine under the same policy.
    assert main.evaluate("() => typeof window.render") == "function"
