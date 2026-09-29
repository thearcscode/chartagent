"""``build_shell`` — the custom rail's iframe shell (ADR-0017 Decisions 5-16).

The host owns the shell: the container element, the CSP, the hashed
``<script>`` tags, and the ``postMessage`` bootstrap that calls the agent's
two symbols, ``render(data, el)`` and ``getPlottedSeries()``. The agent
never writes the handshake or its ``event.source`` check — see ADR-0017
Decision 7 and its channel-contract erratum for the message shapes this
bootstrap speaks (contract version 1).

The shell is rows-free and theme-free: rows, theme and container dimensions
arrive later, by ``postMessage`` at paint time, so one assembled shell
serves both the user's render and the review render. ``build_shell`` never
fetches — the caller hands library bytes in, keyed by sha256, and every pin
in ``document.libraries`` is verified against them.

Module and library text is untrusted, so it is escaped before it is embedded
(see :func:`_embed_script`); the CSP hashes are computed over that same
escaped text, which is exactly what the browser parses.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from chartagent.errors import DocumentAssemblyError
from chartagent.recipe import ChartDocument, LibraryPin

_SUPPORTED_CONTRACT_VERSION = 1

# ADR-0017 Decision 5: exactly this token, never `allow-same-origin` — the
# two together would let the document remove the sandbox altogether.
_SANDBOX_TOKENS: tuple[str, ...] = ("allow-scripts",)

_CONTAINER_ID = "chartagent-container"

# Shipped size-cap defaults (ADR-0017 Decision 15), all in UTF-8 bytes. They
# are policy, not allowlists: callers override them by keyword. The per-blob
# default admits a Plotly-class minified library (~5 MB) with headroom, and
# the assembled default admits a page carrying one such blob.
DEFAULT_MAX_SOURCE_BYTES = 1024 * 1024
DEFAULT_MAX_LIBRARY_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_ASSEMBLED_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class Shell:
    """A ready-to-mount iframe page (ADR-0017 Decision 11).

    ``html`` is the full document to hand an iframe as ``srcdoc`` (or a
    blob URL). ``sandbox`` is the tuple of tokens the caller must apply to
    its own ``<iframe>`` element — the CSP and the ``postMessage``
    handshake travel inside ``html`` instead, because they are the
    boundary's other half and must not be left to the caller's memory.
    """

    html: str
    sandbox: tuple[str, ...]


def build_shell(
    document: ChartDocument,
    *,
    libraries: Mapping[str, bytes],
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
    max_library_bytes: int = DEFAULT_MAX_LIBRARY_BYTES,
    max_assembled_bytes: int = DEFAULT_MAX_ASSEMBLED_BYTES,
) -> Shell:
    """Assemble a rows-free, theme-free iframe shell for ``document``.

    ``libraries`` is a mapping from sha256 to bytes. Every pin in
    ``document.libraries`` is verified and loaded in tuple order, before
    the module; an empty map is legal (the from-scratch document) and a
    blob the document does not pin is ignored. Deterministic in
    ``(document, libraries)`` — two calls with equal inputs return an equal
    ``Shell``.

    Three size caps, in bytes, are keyword arguments with shipped defaults:
    ``max_source_bytes`` bounds the module plus CSS together (default 1 MiB),
    ``max_library_bytes`` bounds each library blob on its own (default
    10 MiB, admitting Plotly-class libraries), and ``max_assembled_bytes``
    bounds the finished UTF-8 page (default 16 MiB).

    Raises :class:`~chartagent.errors.DocumentAssemblyError`:

    - ``kind="contract_unsupported"`` if ``document.contract_version`` is
      not the one version this build serves.
    - ``kind="pin_missing"`` if a pinned library has no entry in
      ``libraries``.
    - ``kind="pin_mismatch"`` if the supplied bytes do not hash to the pin.
    - ``kind="source_too_large"`` if module plus CSS exceed
      ``max_source_bytes``.
    - ``kind="library_too_large"`` if a pinned blob exceeds
      ``max_library_bytes``.
    - ``kind="assembled_too_large"`` if the page exceeds
      ``max_assembled_bytes``.
    """
    if document.contract_version != _SUPPORTED_CONTRACT_VERSION:
        raise DocumentAssemblyError(
            f"contract_version {document.contract_version} is not supported "
            f"(this build serves version {_SUPPORTED_CONTRACT_VERSION})",
            kind="contract_unsupported",
        )

    source_bytes = len(document.module.encode("utf-8")) + len(
        (document.styles or "").encode("utf-8")
    )
    if source_bytes > max_source_bytes:
        raise DocumentAssemblyError(
            f"module and CSS total {source_bytes} bytes, over the "
            f"{max_source_bytes}-byte source cap",
            kind="source_too_large",
        )

    library_scripts = [
        _verify_pin(pin, libraries, max_library_bytes) for pin in document.libraries
    ]
    scripts = [
        _embed_script(text)
        for text in (*library_scripts, document.module, _bootstrap_js())
    ]

    csp = _content_security_policy(_script_hash(text) for text in scripts)
    script_tags = "\n".join(f"<script>{text}</script>" for text in scripts)
    style_block = _style_block(document.styles)

    html = (
        "<!doctype html>\n"
        "<html>\n"
        "<head>\n"
        '<meta charset="utf-8" />\n'
        f'<meta http-equiv="Content-Security-Policy" content="{csp}" />\n'
        f"{style_block}"
        "</head>\n"
        "<body>\n"
        f'<div id="{_CONTAINER_ID}"></div>\n'
        f"{script_tags}\n"
        "</body>\n"
        "</html>"
    )
    assembled_bytes = len(html.encode("utf-8"))
    if assembled_bytes > max_assembled_bytes:
        raise DocumentAssemblyError(
            f"assembled page is {assembled_bytes} bytes, over the "
            f"{max_assembled_bytes}-byte assembled-page cap",
            kind="assembled_too_large",
        )
    return Shell(html=html, sandbox=_SANDBOX_TOKENS)


def _verify_pin(
    pin: LibraryPin, libraries: Mapping[str, bytes], max_library_bytes: int
) -> str:
    blob = libraries.get(pin.sha256)
    if blob is None:
        raise DocumentAssemblyError(
            f"no bytes supplied for pinned library {pin.name}@{pin.version} "
            f"({pin.sha256})",
            kind="pin_missing",
        )
    if len(blob) > max_library_bytes:
        raise DocumentAssemblyError(
            f"library {pin.name}@{pin.version} is {len(blob)} bytes, over the "
            f"{max_library_bytes}-byte library cap",
            kind="library_too_large",
        )
    actual = hashlib.sha256(blob).hexdigest()
    if actual != pin.sha256:
        raise DocumentAssemblyError(
            f"library {pin.name}@{pin.version} bytes hash to {actual}, "
            f"pinned as {pin.sha256}",
            kind="pin_mismatch",
        )
    return blob.decode("utf-8")


# Sequences that can end or re-enter an inline element's raw text per the
# HTML tokenizer: `</script` (any case) closes a <script>, `<!--` opens the
# escaped states in which a following `<script` swallows the real close tag,
# and `</style` closes a <style>.
_SCRIPT_CLOSE = re.compile(r"<(/script)", re.IGNORECASE)
_STYLE_CLOSE = re.compile(r"<(/style)", re.IGNORECASE)
_COMMENT_OPEN = re.compile(r"<!--")


def _escape_close_tag(pattern: re.Pattern[str], text: str) -> str:
    return pattern.sub(r"<\\\1", text)


def _style_block(styles: str | None) -> str:
    if not styles:
        return ""
    # Scoped to the container so a stray `body` or `*` rule cannot restyle
    # the shell's chrome (ADR-0017 Decision 7); `</style` is escaped so the
    # text cannot close its own element (CSS reads `\/` as `/`).
    styles = _escape_close_tag(_STYLE_CLOSE, styles)
    return f"<style>@scope (#{_CONTAINER_ID}) {{\n{styles}\n}}</style>\n"


def _embed_script(text: str) -> str:
    """Make ``text`` safe to sit inside an inline ``<script>`` element.

    ``</script`` becomes ``<\\/script`` and ``<!--`` becomes ``\\x3C!--``.
    In a JS string, template, regex literal (including ``u``/``v`` flags) or
    comment the escape denotes the same character, so
    behaviour is unchanged and the bytes differ only at those sequences.
    Text that hits them outside such a context (e.g. ``a<!--b`` as bare code,
    an HTML-like comment) cannot be preserved; that residual case is for an
    ADR-0017 amendment rather than a new ``DocumentAssemblyError`` kind.
    """
    text = _escape_close_tag(_SCRIPT_CLOSE, text)
    return _COMMENT_OPEN.sub(r"\\x3C!--", text)


def _script_hash(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")


def _content_security_policy(hashes: Iterable[str]) -> str:
    script_src = " ".join(f"'{h}'" for h in hashes)
    directives = [
        "default-src 'none'",
        f"script-src {script_src}",
        # Inline styles must stay possible — canvas/SVG libraries set
        # element styles at runtime (ADR-0017's implementation note under
        # Decision 15's CSP clause).
        "style-src 'unsafe-inline'",
        "img-src data:",
        "font-src data:",
        "connect-src 'none'",
        "frame-src 'none'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
    ]
    return "; ".join(directives)


def _bootstrap_js() -> str:
    # The host-owned postMessage handshake (ADR-0017 Decision 7). Checks
    # event.source, never event.origin — an opaque origin serialises to
    # "null" for every iframe, so origin equality is meaningless here.
    # See the ADR-0017 channel-contract erratum for the message shapes.
    return f"""(function () {{
  var container = document.getElementById({json.dumps(_CONTAINER_ID)});

  function paint(message) {{
    var ok = false;
    var plottedSeries = null;
    try {{
      var container_ = message.container;
      if (container_ && typeof container_.width === "number") {{
        container.style.width = container_.width + "px";
      }}
      if (container_ && typeof container_.height === "number") {{
        container.style.height = container_.height + "px";
      }}
      var theme = message.theme;
      if (theme && typeof theme === "object") {{
        for (var key in theme) {{
          if (Object.prototype.hasOwnProperty.call(theme, key)) {{
            container.style.setProperty("--" + key, theme[key]);
          }}
        }}
      }}
      container.innerHTML = "";
      if (
        typeof window.render !== "function" ||
        typeof window.getPlottedSeries !== "function"
      ) {{
        throw new Error("render or getPlottedSeries is not defined");
      }}
      window.render(message.rows, container);
      plottedSeries = window.getPlottedSeries();
      ok = true;
    }} catch (err) {{
      ok = false;
      plottedSeries = null;
    }}
    report(ok, plottedSeries);
  }}

  function read() {{
    // A re-read without a redraw (ADR-0017 Decision 7): no container
    // clear, no render — just getPlottedSeries() again, which the module
    // must answer consistently from whatever it last drew.
    var ok = false;
    var plottedSeries = null;
    try {{
      if (typeof window.getPlottedSeries !== "function") {{
        throw new Error("getPlottedSeries is not defined");
      }}
      plottedSeries = window.getPlottedSeries();
      ok = true;
    }} catch (err) {{
      ok = false;
      plottedSeries = null;
    }}
    report(ok, plottedSeries);
  }}

  function report(ok, plottedSeries) {{
    window.parent.postMessage(
      {{
        type: "chartagent/painted",
        contractVersion: 1,
        ok: ok,
        plottedSeries: ok ? plottedSeries : null,
      }},
      "*"
    );
  }}

  window.addEventListener("message", function (event) {{
    if (event.source !== window.parent) return;
    var message = event.data;
    if (!message) return;
    if (message.type === "chartagent/paint") {{
      paint(message);
    }} else if (message.type === "chartagent/read") {{
      read();
    }}
  }});
}})();"""
