"""Renderer bundle sanity checks.

The bundle is served verbatim from app/renderer/widget.js (versioned by its
content hash), so we assert on source-level invariants the HTTP tests cannot
see -- these guard the fixes for how the inline form is placed and what gets
into style strings.
"""

from pathlib import Path

_RENDERER = Path(__file__).resolve().parent.parent / "app" / "renderer" / "widget.js"


def _bundle() -> str:
    return _RENDERER.read_text(encoding="utf-8")


def test_inline_form_renders_in_place_next_to_script():
    bundle = _bundle()
    # The inline branch no longer pins to the viewport…
    assert "document.body.appendChild(card)" not in bundle
    # …it inserts next to the embed script, in page flow…
    assert "host.insertBefore(card, currentScript.nextSibling)" in bundle
    # …while the floating launcher still mounts on <body>.
    assert "document.body.appendChild(launcher)" in bundle
    assert "document.body.appendChild(modal)" in bundle


def test_accent_color_restricted_to_hex_values():
    bundle = _bundle()
    assert "^#[0-9a-fA-F]{6}$" in bundle


def test_versioned_bundle_is_byte_identical(client):
    from app.version import WIDGET_SCRIPT_VERSION

    res = client.get(f"/embed/{WIDGET_SCRIPT_VERSION}/widget.js")
    assert res.status_code == 200
    assert res.content == _RENDERER.read_bytes()

    # Unknown versions are rejected.
    assert client.get("/embed/w0deadbeef/widget.js").status_code == 404