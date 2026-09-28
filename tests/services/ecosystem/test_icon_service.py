# SPDX-License-Identifier: MIT
# ============================================================
# Icon upload/sanitization tests (task B-7).
# ============================================================

from __future__ import annotations

import pytest

from services.ecosystem.errors import EcosystemError
from services.ecosystem.icon_service import sanitize_svg, upload_icon

_MALICIOUS_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
    b"<script>alert(1)</script>"
    b'<rect onload="evil()" width="1" height="1"/>'
    b'<image xlink:href="http://evil.com/x.png"/>'
    b'<a xlink:href="#frag">ok</a>'
    b"</svg>"
)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def test_sanitize_svg_strips_script_tag():
    result = sanitize_svg(_MALICIOUS_SVG)
    assert b"script" not in result
    assert b"alert(1)" not in result


def test_sanitize_svg_strips_event_handler_attribute():
    result = sanitize_svg(_MALICIOUS_SVG)
    assert b"onload" not in result
    assert b"evil()" not in result


def test_sanitize_svg_strips_external_href():
    result = sanitize_svg(_MALICIOUS_SVG)
    assert b"evil.com" not in result


def test_sanitize_svg_preserves_fragment_href():
    result = sanitize_svg(_MALICIOUS_SVG)
    assert b"#frag" in result


def test_sanitize_svg_does_not_reject_outright():
    # Task B-7's own test requirement: sanitize, don't bounce.
    result = sanitize_svg(_MALICIOUS_SVG)
    assert result  # non-empty, sanitization succeeded rather than raising


def test_sanitize_svg_rejects_invalid_xml():
    with pytest.raises(EcosystemError):
        sanitize_svg(b"not xml at all {{{")


def test_upload_icon_svg_round_trips_sanitized(monkeypatch, tmp_path):
    monkeypatch.setenv("ECOSYSTEM_OBJECT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("ECOSYSTEM_OBJECT_STORAGE_LOCAL_DIR", str(tmp_path))
    import importlib

    import core.config as config_module

    importlib.reload(config_module)

    icon_url = upload_icon(_MALICIOUS_SVG, content_type="image/svg+xml")
    assert icon_url.startswith("url:")

    from store.ecosystem_object_storage import get_ecosystem_object_storage

    stored = get_ecosystem_object_storage().get(icon_url[len("url:"):])
    assert b"script" not in stored


def test_upload_icon_raster_stored_unmodified(monkeypatch, tmp_path):
    monkeypatch.setenv("ECOSYSTEM_OBJECT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("ECOSYSTEM_OBJECT_STORAGE_LOCAL_DIR", str(tmp_path))
    import importlib

    import core.config as config_module

    importlib.reload(config_module)

    icon_url = upload_icon(_PNG_MAGIC, content_type="image/png")
    assert icon_url.startswith("url:")

    from store.ecosystem_object_storage import get_ecosystem_object_storage

    stored = get_ecosystem_object_storage().get(icon_url[len("url:"):])
    assert stored == _PNG_MAGIC


def test_upload_icon_rejects_unrecognized_format():
    with pytest.raises(EcosystemError):
        upload_icon(b"just some random bytes, not an image", content_type="application/octet-stream")


def test_upload_icon_rejects_oversized_content():
    huge = b"\x89PNG\r\n\x1a\n" + b"\x00" * (600 * 1024)
    with pytest.raises(EcosystemError):
        upload_icon(huge, content_type="image/png")
