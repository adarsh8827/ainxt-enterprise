# SPDX-License-Identifier: MIT
# ============================================================
# Icon service (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-7).
#
# SVG sanitization uses defusedxml (already a repo dependency, PSF-2.0,
# pre-existing — not a new dependency added by this task) for XXE-safe
# parsing; the actual sanitization (stripping <script>, on* handlers, and
# external href/xlink:href) is a manual allowlist rewrite on top, since
# defusedxml itself only guards XML parsing, not SVG content semantics.
#
# Known gap, disclosed rather than silently worked around: CONTRACTS.md §7
# specifies icon_url's `url:` form as "a same-origin object-storage path"
# but no GET endpoint to actually serve a stored icon back over HTTP exists
# in CONTRACTS.md's endpoint list. This task stores the sanitized content
# and returns `url:<content-hash key>` — resolving that key into a real,
# servable HTTP path is a gap for whichever future task adds the missing
# GET route, not solved here.
# ============================================================

from __future__ import annotations

import re

from defusedxml import ElementTree as _safe_ET

from services.ecosystem.errors import EcosystemError
from store.ecosystem_object_storage import get_ecosystem_object_storage

_MAX_ICON_BYTES = 512 * 1024  # 512KB — an icon is not a document
_RASTER_MAGIC = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpg",
    b"RIFF": "webp",  # narrowed further below (RIFF....WEBP)
}

_SVG_TAG_RE = re.compile(r"\{[^}]*\}")  # strips XML namespace braces from tag names


def _strip_ns(tag: str) -> str:
    return _SVG_TAG_RE.sub("", tag)


def _is_external_reference(value: str) -> bool:
    """True if an href/xlink:href value points outside the document itself —
    anything except a fragment (#id) or an embedded data: URI is external."""
    v = value.strip()
    return not (v.startswith("#") or v.startswith("data:"))


def sanitize_svg(content: bytes) -> bytes:
    """Parse with defusedxml (XXE-safe), then strip every <script> element,
    every on* event-handler attribute, and every external href/xlink:href —
    returns the sanitized SVG, never rejects outright (task B-7's test
    requirement: a malicious SVG is cleaned, not bounced)."""
    try:
        root = _safe_ET.fromstring(content)
    except Exception as exc:
        raise EcosystemError(f"invalid SVG/XML: {exc}") from exc

    for element in list(root.iter()):
        if _strip_ns(element.tag) == "script":
            # ElementTree has no direct "remove from anywhere" — collect
            # parents via iteration and drop matching children.
            for parent in root.iter():
                for child in list(parent):
                    if child is element:
                        parent.remove(child)
        else:
            for attr_name in list(element.attrib.keys()):
                # defusedxml/ElementTree exposes a namespaced attribute (e.g.
                # xlink:href) as "{namespace-uri}href" — stripping the {..}
                # prefix reduces both plain "href" and namespaced "xlink:href"
                # to the same local name "href", so one check covers both.
                local_name = _strip_ns(attr_name)
                if local_name.startswith("on"):
                    del element.attrib[attr_name]
                elif local_name == "href" and _is_external_reference(element.attrib[attr_name]):
                    del element.attrib[attr_name]

    return _safe_ET.tostring(root)


def _detect_raster_kind(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    return None


def upload_icon(content: bytes, content_type: str) -> str:
    """Sanitize (if SVG) and store an icon; returns its icon_url in the
    'url:<key>' form (CONTRACTS.md §7)."""
    if len(content) > _MAX_ICON_BYTES:
        raise EcosystemError(f"icon exceeds the {_MAX_ICON_BYTES // 1024}KB limit")

    is_svg = content_type == "image/svg+xml" or content.lstrip().startswith(b"<svg") or content.lstrip().startswith(b"<?xml")
    if is_svg:
        stored_content = sanitize_svg(content)
    else:
        if _detect_raster_kind(content) is None:
            raise EcosystemError("unrecognized icon format — expected PNG, JPEG, WebP, or SVG")
        stored_content = content

    store = get_ecosystem_object_storage()
    object_key = store.put(stored_content)
    return f"url:{object_key}"
