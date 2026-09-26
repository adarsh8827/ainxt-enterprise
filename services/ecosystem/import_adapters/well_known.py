# SPDX-License-Identifier: MIT
# ============================================================
# well_known import adapter (task I, pre-M3) — a domain's own published
# skill index at /.well-known/agent-skills/index.json (schema 0.2.0),
# falling back to /.well-known/skills/index.json.
#
# Index shape this implementation expects (documented here because no
# external spec document was available to verify this against — this is
# a first-pass, clearly-scoped interpretation, not a claim that this
# matches some published standard byte-for-byte):
#
#   {
#     "schema_version": "0.2.0",
#     "skills": [
#       {
#         "slug": "unique-within-this-index",
#         "name": "Display Name",
#         "description": "...",
#         "download_url": "https://.../SKILL.md",   # https, same SSRF checks apply
#         "sha256": "<hex digest of the bytes at download_url>",
#         "license": "MIT"
#       },
#       ...
#     ]
#   }
#
# sha256 is verified on every fetch (task spec) — a mismatch is a hard
# failure, never a warning, since it means either the index or the
# downloaded content was tampered with or is simply wrong.
# ============================================================

from __future__ import annotations

import hashlib
from typing import Any

from connectors.net_relay import relay_request
from services.ecosystem.errors import ImportFetchError, LicenseNotAllowedError
from services.ecosystem.import_adapters.fetch_cache import get_cached, put_cached
from services.ecosystem.import_adapters.ssrf_guard import assert_safe_https_url
from services.ecosystem.license_policy import is_allowed_license

_INDEX_PATHS = ("/.well-known/agent-skills/index.json", "/.well-known/skills/index.json")
_MAX_INDEX_BYTES = 1 * 1024 * 1024
_MAX_SKILL_BYTES = 256 * 1024


def _normalize_domain(domain: str) -> str:
    d = domain.strip()
    for prefix in ("https://", "http://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d.rstrip("/")


def _fetch_index(domain: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for path in _INDEX_PATHS:
        url = assert_safe_https_url(f"https://{domain}{path}")
        try:
            resp = relay_request("GET", url, headers={"Accept": "application/json"}, timeout=15.0)
        except Exception as exc:
            last_error = exc
            continue
        if resp.status_code != 200:
            last_error = ImportFetchError(f"{url} returned HTTP {resp.status_code}")
            continue
        if len(resp.content) > _MAX_INDEX_BYTES:
            raise ImportFetchError(f"{url}'s index exceeds the {_MAX_INDEX_BYTES // 1024}KB limit")
        try:
            return resp.json()
        except Exception as exc:
            last_error = ImportFetchError(f"{url} did not return valid JSON: {exc}")
    raise ImportFetchError(
        f"no well-known skill index found for {domain!r} "
        f"(tried {', '.join(_INDEX_PATHS)}): {last_error}"
    )


def import_from_well_known(domain: str, skill_slug: str) -> dict[str, Any]:
    """
    domain: "example.com" (scheme optional, stripped if present).
    skill_slug: which entry in the domain's index to import.

    Returns {"manifest", "files", "license", "display_name",
    "description", "resolved_sha" (the verified sha256), "source_url"}.
    Raises ImportFetchError / LicenseNotAllowedError.
    """
    domain = _normalize_domain(domain)
    index = _fetch_index(domain)

    skills = index.get("skills")
    if not isinstance(skills, list):
        raise ImportFetchError(f"{domain!r}'s skill index has no 'skills' array")

    entry = next((s for s in skills if isinstance(s, dict) and s.get("slug") == skill_slug), None)
    if entry is None:
        raise ImportFetchError(f"{domain!r}'s skill index has no entry with slug {skill_slug!r}")

    download_url = entry.get("download_url", "")
    declared_sha256 = (entry.get("sha256") or "").lower()
    license_str = entry.get("license", "")

    if not is_allowed_license(license_str):
        raise LicenseNotAllowedError(
            f"{domain!r}/{skill_slug!r}'s license ({license_str!r}) is missing or not MIT/Apache-2.0",
            stage="import_precheck", declared_license=license_str or None,
        )
    if not download_url:
        raise ImportFetchError(f"{domain!r}/{skill_slug!r}'s index entry has no download_url")
    if not declared_sha256:
        raise ImportFetchError(f"{domain!r}/{skill_slug!r}'s index entry has no sha256 digest")

    fetch_identity = f"well_known:{domain}:{skill_slug}:{declared_sha256}"
    cached = get_cached(fetch_identity)
    if cached is not None:
        raw = cached
    else:
        safe_url = assert_safe_https_url(download_url)
        resp = relay_request("GET", safe_url, timeout=15.0)
        if resp.status_code != 200:
            raise ImportFetchError(f"{download_url} returned HTTP {resp.status_code}")
        raw = resp.content
        if len(raw) > _MAX_SKILL_BYTES:
            raise ImportFetchError(f"{download_url} exceeds the {_MAX_SKILL_BYTES // 1024}KB limit")

    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != declared_sha256:
        raise ImportFetchError(
            f"{domain!r}/{skill_slug!r}: sha256 mismatch — index declared {declared_sha256}, "
            f"downloaded content hashes to {actual_sha256}"
        )
    if cached is None:
        put_cached(fetch_identity, raw)

    skill_md_text = raw.decode("utf-8", errors="replace")

    from services.ecosystem._agentstudio_interop import parse_skill_md_frontmatter

    frontmatter = parse_skill_md_frontmatter(skill_md_text)
    display_name = entry.get("name") or frontmatter.get("name", skill_slug)
    description = entry.get("description") or frontmatter.get("description", "")
    manifest = {"name": display_name, "description": description, "instructions": skill_md_text}

    return {
        "manifest": manifest,
        "files": {},
        "license": license_str,
        "display_name": display_name,
        "description": description,
        "resolved_sha": actual_sha256,
        "source_url": f"https://{domain}",
    }
