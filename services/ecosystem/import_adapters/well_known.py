# SPDX-License-Identifier: MIT
# ============================================================
# well_known import adapter (task I, pre-M3; rewritten 2026-09-28).
#
# ORIGINAL VERSION'S BUG, FOUND LIVE: this adapter's original index shape
# (slug/download_url/sha256/license fields on each entry) was an invented
# guess, disclosed as such in this file's own header at the time ("no
# external spec document was available to verify this against"). Testing
# it live against two real sites that actually publish a well-known skill
# index (docs.x.com, supabase.com) showed neither matches that guess --
# both implement the real, published Agent Skills Discovery format
# instead: https://schemas.agentskills.io/discovery/0.2.0/schema.json.
#
# Real index shape (verified live against both sites' actual JSON):
#   {
#     "$schema": "https://schemas.agentskills.io/discovery/0.2.0/schema.json",
#     "skills": [
#       {
#         "name": "...",
#         "type": "skill-md" | "archive",
#         "description": "...",
#         "url": "<absolute, or relative to the site's own origin>",
#         "digest": "sha256:<hex>"
#       },
#       ...
#     ]
#   }
# "skill-md": `url` points directly at one SKILL.md file.
# "archive": `url` points at a .tar.gz containing SKILL.md at its root
# (verified structure: SKILL.md + a references/ tree, no path traversal,
# no symlinks in the one real example inspected -- still guarded against
# regardless, since archive members are untrusted input).
#
# Legacy format (also real -- docs.x.com serves this too, at the OTHER
# well-known path, /.well-known/skills/index.json, alongside the modern
# one at /.well-known/agent-skills/index.json): a bare
#   {"skills": [{"name": "...", "description": "...", "files": ["SKILL.md", ...]}]}
# with no url/digest/license at all. Verified live that each listed file
# lives at /.well-known/skills/<name>/<file> (same name-prefixed-subfolder
# convention as the modern format's own skill-md URLs) -- confirmed by a
# real fetch (200) vs. the flat-path alternative (404).
#
# License handling (explicit review decision): this format has no
# index-level license field at all (the old code's assumption of one was
# itself part of the original bug) -- the license is read from the
# fetched SKILL.md's own `license:` frontmatter field, same as every other
# adapter in this package. Missing -> excluded under tier 1, same
# fail-closed rule as everywhere else; never inferred from the site name
# or any other signal.
# ============================================================

from __future__ import annotations

import hashlib
import io
import tarfile
from typing import Any
from urllib.parse import urljoin

from connectors.net_relay import relay_request
from services.ecosystem.errors import ImportFetchError, LicenseNotAllowedError
from services.ecosystem.import_adapters.fetch_cache import get_cached, put_cached
from services.ecosystem.import_adapters.ssrf_guard import assert_safe_https_url
from services.ecosystem.license_policy import is_allowed_license

_MAX_REDIRECTS = 5
_MODERN_INDEX_PATH = "/.well-known/agent-skills/index.json"
_LEGACY_INDEX_PATH = "/.well-known/skills/index.json"
_MAX_INDEX_BYTES = 1 * 1024 * 1024
_MAX_SKILL_MD_BYTES = 256 * 1024
_MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
_MAX_ARCHIVE_MEMBER_BYTES = 512 * 1024
_MAX_ARCHIVE_MEMBERS = 500


def _normalize_domain(domain: str) -> str:
    d = domain.strip()
    for prefix in ("https://", "http://"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d.rstrip("/")


def _get_json(url: str, *, max_bytes: int) -> dict[str, Any] | None:
    """Returns the parsed JSON body, or None if this URL isn't a usable
    JSON index (404, non-2xx, wrong content, a redirect to something that
    still isn't a real index, etc.) -- callers try the next candidate path
    rather than treating "not found here" as fatal. Follows redirects
    itself (see _fetch_bytes's own docstring for why) -- a site can
    legitimately redirect its bare domain to a www subdomain."""
    current_url = url
    for _ in range(_MAX_REDIRECTS + 1):
        safe_url = assert_safe_https_url(current_url)
        try:
            resp = relay_request("GET", safe_url, headers={"Accept": "application/json"}, timeout=15.0)
        except Exception:
            return None
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location") or resp.headers.get("Location")
            if not location:
                return None
            current_url = urljoin(current_url, location)
            continue
        if resp.status_code != 200:
            return None
        if len(resp.content) > max_bytes:
            raise ImportFetchError(f"{current_url}'s index exceeds the {max_bytes // 1024}KB limit")
        try:
            parsed = resp.json()
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) and isinstance(parsed.get("skills"), list) else None
    return None


def _parse_digest(digest: str, *, context: str) -> str:
    if not digest or not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise ImportFetchError(f"{context}: digest {digest!r} is missing or not in 'sha256:<hex>' form")
    hexpart = digest[len("sha256:"):].strip().lower()
    if len(hexpart) != 64 or any(c not in "0123456789abcdef" for c in hexpart):
        raise ImportFetchError(f"{context}: digest {digest!r} is not a well-formed sha256 hex digest")
    return hexpart


def _fetch_bytes(url: str, *, max_bytes: int, fetch_identity: str) -> bytes:
    """GETs `url`, following redirects itself (connectors.net_relay.
    relay_request's own httpx.request() call does not set
    follow_redirects=True, and that shared, widely-used relay function is
    not this adapter's to change) -- real-world skill archives are
    published as GitHub release assets, which always 302 to a signed
    objects.githubusercontent.com URL. Every redirect target is re-checked
    through the SSRF guard before being fetched, same as the original URL
    -- a redirect chain is exactly the kind of attacker-influenced input
    that guard exists for.
    """
    cached = get_cached(fetch_identity)
    if cached is not None:
        return cached

    current_url = url
    for _ in range(_MAX_REDIRECTS + 1):
        safe_url = assert_safe_https_url(current_url)
        resp = relay_request("GET", safe_url, timeout=20.0)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location") or resp.headers.get("Location")
            if not location:
                raise ImportFetchError(f"{current_url} returned HTTP {resp.status_code} with no Location header")
            current_url = urljoin(current_url, location)
            continue
        if resp.status_code != 200:
            raise ImportFetchError(f"{current_url} returned HTTP {resp.status_code}")
        raw = resp.content
        if len(raw) > max_bytes:
            raise ImportFetchError(f"{current_url} exceeds the {max_bytes // 1024}KB limit")
        put_cached(fetch_identity, raw)
        return raw

    raise ImportFetchError(f"{url}: exceeded {_MAX_REDIRECTS} redirects")


def _verify_digest(raw: bytes, declared_hex: str, *, context: str) -> None:
    actual = hashlib.sha256(raw).hexdigest()
    if actual != declared_hex:
        raise ImportFetchError(
            f"{context}: digest mismatch -- index declared sha256:{declared_hex}, "
            f"downloaded content hashes to sha256:{actual}"
        )


def _safe_archive_member_name(name: str) -> bool:
    """Defense in depth against a malicious/corrupt archive -- untrusted
    input regardless of how unlikely a traversal member from a real
    release asset would be."""
    if not name or name.startswith("/") or "\\" in name:
        return False
    return ".." not in name.split("/")


def _extract_skill_from_archive(raw: bytes, *, context: str) -> tuple[str, dict[str, str]]:
    """Safely extracts a skill-shaped tar.gz: SKILL.md must sit at the
    archive root; every other regular file becomes a bundled file (path
    relative to the archive root). Rejects symlinks/hardlinks/devices
    outright (never followed, never extracted) and enforces per-member and
    total size caps -- a compressed archive's uncompressed size is
    untrusted input (decompression-bomb guard), checked as each member is
    read rather than trusted from the tar header alone.
    """
    try:
        tf = tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz")
    except Exception as exc:
        raise ImportFetchError(f"{context}: not a valid .tar.gz archive: {exc}") from exc

    members = tf.getmembers()
    if len(members) > _MAX_ARCHIVE_MEMBERS:
        raise ImportFetchError(f"{context}: archive has {len(members)} members, exceeding the {_MAX_ARCHIVE_MEMBERS} limit")

    skill_md_text: str | None = None
    files: dict[str, str] = {}
    total_bytes = 0
    for member in members:
        if not member.isfile():
            continue  # directories, symlinks, hardlinks, devices -- never extracted
        if not _safe_archive_member_name(member.name):
            raise ImportFetchError(f"{context}: archive member {member.name!r} has an unsafe path")
        if member.size > _MAX_ARCHIVE_MEMBER_BYTES:
            raise ImportFetchError(
                f"{context}: archive member {member.name!r} ({member.size} bytes) exceeds the "
                f"{_MAX_ARCHIVE_MEMBER_BYTES // 1024}KB per-file limit"
            )
        total_bytes += member.size
        if total_bytes > _MAX_ARCHIVE_BYTES:
            raise ImportFetchError(f"{context}: archive exceeds the {_MAX_ARCHIVE_BYTES // (1024 * 1024)}MB total-uncompressed limit")

        extracted = tf.extractfile(member)
        if extracted is None:
            continue
        text = extracted.read().decode("utf-8", errors="replace")

        if member.name == "SKILL.md":
            skill_md_text = text
        else:
            files[member.name] = text

    if skill_md_text is None:
        raise ImportFetchError(f"{context}: archive has no SKILL.md at its root")
    return skill_md_text, files


def _fetch_modern_entry(domain: str, index: dict[str, Any], skill_slug: str) -> dict[str, Any]:
    entry = next((s for s in index["skills"] if isinstance(s, dict) and s.get("name") == skill_slug), None)
    if entry is None:
        raise ImportFetchError(f"{domain!r}'s modern skill index has no entry named {skill_slug!r}")

    entry_type = entry.get("type")
    if entry_type not in ("skill-md", "archive"):
        raise ImportFetchError(f"{domain!r}/{skill_slug!r}: unsupported entry type {entry_type!r} (expected 'skill-md' or 'archive')")

    raw_url = entry.get("url") or ""
    if not raw_url:
        raise ImportFetchError(f"{domain!r}/{skill_slug!r}'s index entry has no url")
    resolved_url = urljoin(f"https://{domain}/", raw_url)
    digest_hex = _parse_digest(entry.get("digest", ""), context=f"{domain!r}/{skill_slug!r}")

    fetch_identity = f"well_known:{domain}:{skill_slug}:{digest_hex}"
    max_bytes = _MAX_ARCHIVE_BYTES if entry_type == "archive" else _MAX_SKILL_MD_BYTES
    raw = _fetch_bytes(resolved_url, max_bytes=max_bytes, fetch_identity=fetch_identity)
    _verify_digest(raw, digest_hex, context=f"{domain!r}/{skill_slug!r}")

    if entry_type == "archive":
        skill_md_text, files = _extract_skill_from_archive(raw, context=f"{domain!r}/{skill_slug!r}")
    else:
        skill_md_text = raw.decode("utf-8", errors="replace")
        files = {}

    return {
        "skill_md_text": skill_md_text, "files": files, "resolved_sha": digest_hex,
        "index_description": entry.get("description") or "", "source_url": f"https://{domain}",
    }


def _fetch_legacy_entry(domain: str, index: dict[str, Any], skill_slug: str) -> dict[str, Any]:
    entry = next((s for s in index["skills"] if isinstance(s, dict) and s.get("name") == skill_slug), None)
    if entry is None:
        raise ImportFetchError(f"{domain!r}'s legacy skill index has no entry named {skill_slug!r}")

    file_list = entry.get("files")
    if not isinstance(file_list, list) or not file_list:
        raise ImportFetchError(f"{domain!r}/{skill_slug!r}'s legacy index entry has no files list")
    for filename in file_list:
        if not isinstance(filename, str) or not filename or filename.startswith("/") or ".." in filename.split("/"):
            raise ImportFetchError(f"{domain!r}/{skill_slug!r}: unsafe filename {filename!r} in legacy index")
    if "SKILL.md" not in file_list:
        raise ImportFetchError(f"{domain!r}/{skill_slug!r}'s legacy index entry has no SKILL.md in its files list")

    skill_md_text: str | None = None
    files: dict[str, str] = {}
    for filename in file_list:
        url = f"https://{domain}{_LEGACY_INDEX_PATH.rsplit('/', 1)[0]}/{skill_slug}/{filename}"
        fetch_identity = f"well_known_legacy:{domain}:{skill_slug}:{filename}"
        raw = _fetch_bytes(url, max_bytes=_MAX_SKILL_MD_BYTES, fetch_identity=fetch_identity)
        text = raw.decode("utf-8", errors="replace")
        if filename == "SKILL.md":
            skill_md_text = text
        else:
            files[filename] = text

    assert skill_md_text is not None  # guaranteed by the "SKILL.md" in file_list check above
    # Legacy entries carry no digest at all -- resolved_sha is a content
    # hash of what was actually fetched, so pinning/attribution still work,
    # just without an upstream-declared digest to verify against.
    resolved_sha = hashlib.sha256(skill_md_text.encode("utf-8")).hexdigest()
    return {
        "skill_md_text": skill_md_text, "files": files, "resolved_sha": resolved_sha,
        "index_description": entry.get("description") or "", "source_url": f"https://{domain}",
    }


def import_from_well_known(domain: str, skill_slug: str) -> dict[str, Any]:
    """
    domain: "example.com" (scheme optional, stripped if present).
    skill_slug: the `name` of an entry in the domain's index (modern or
    legacy format -- modern is tried first, legacy is the fallback).

    Returns {"manifest", "files", "license", "display_name",
    "description", "resolved_sha", "source_url"}. Raises ImportFetchError /
    LicenseNotAllowedError.
    """
    domain = _normalize_domain(domain)

    modern_index = _get_json(f"https://{domain}{_MODERN_INDEX_PATH}", max_bytes=_MAX_INDEX_BYTES)
    if modern_index is not None:
        fetched = _fetch_modern_entry(domain, modern_index, skill_slug)
    else:
        legacy_index = _get_json(f"https://{domain}{_LEGACY_INDEX_PATH}", max_bytes=_MAX_INDEX_BYTES)
        if legacy_index is None:
            raise ImportFetchError(
                f"no well-known skill index found for {domain!r} "
                f"(tried {_MODERN_INDEX_PATH} and {_LEGACY_INDEX_PATH})"
            )
        fetched = _fetch_legacy_entry(domain, legacy_index, skill_slug)

    from services.ecosystem._agentstudio_interop import parse_skill_md_frontmatter
    from services.ecosystem.import_adapters.github_repo import _clean_display_name

    frontmatter = parse_skill_md_frontmatter(fetched["skill_md_text"])
    license_str = frontmatter.get("license", "")
    if not is_allowed_license(license_str):
        raise LicenseNotAllowedError(
            f"{domain!r}/{skill_slug!r}'s SKILL.md license: field ({license_str!r}) is missing or not MIT/Apache-2.0",
            stage="import_precheck", declared_license=license_str or None,
        )

    # Same fix as github_repo.py's own display_name derivation (real bug
    # found live: a source's own frontmatter "name" can carry that
    # source's internal naming convention, e.g. "collection::skill" --
    # not a display name, just leaked through verbatim otherwise).
    display_name = _clean_display_name(frontmatter.get("name", ""), skill_slug)
    description = fetched["index_description"] or frontmatter.get("description", "")
    manifest = {"name": display_name, "description": description, "instructions": fetched["skill_md_text"]}

    return {
        "manifest": manifest,
        "files": fetched["files"],
        "license": license_str,
        "display_name": display_name,
        "description": description,
        "resolved_sha": fetched["resolved_sha"],
        "source_url": fetched["source_url"],
    }


# External-sources catalog crawler support (additive) -- lists every entry
# at a well-known domain's index WITHOUT importing/storing any of them,
# mirroring discover_skills_in_repo()'s shape: one candidate dict per
# entry, license evidence + allow/deny verdict included, nothing raised for
# an individual entry's own license failure (only for "no index at all").
def discover_skills_at_well_known(domain: str) -> list[dict[str, Any]]:
    """Fetches `domain`'s modern (falling back to legacy) skill index and
    resolves each listed entry's SKILL.md far enough to read its license:
    field -- the only license signal this format has (see this module's
    header comment). Raises ImportFetchError only if `domain` has no
    parseable index at all; a per-entry license failure is reported IN
    the returned list (allowed=False, reason set), not raised.
    """
    domain = _normalize_domain(domain)

    modern_index = _get_json(f"https://{domain}{_MODERN_INDEX_PATH}", max_bytes=_MAX_INDEX_BYTES)
    if modern_index is not None:
        entries = [e for e in modern_index["skills"] if isinstance(e, dict) and e.get("name")]
        fetch_one = lambda slug: _fetch_modern_entry(domain, modern_index, slug)  # noqa: E731
    else:
        legacy_index = _get_json(f"https://{domain}{_LEGACY_INDEX_PATH}", max_bytes=_MAX_INDEX_BYTES)
        if legacy_index is None:
            raise ImportFetchError(
                f"no well-known skill index found for {domain!r} "
                f"(tried {_MODERN_INDEX_PATH} and {_LEGACY_INDEX_PATH})"
            )
        entries = [e for e in legacy_index["skills"] if isinstance(e, dict) and e.get("name")]
        fetch_one = lambda slug: _fetch_legacy_entry(domain, legacy_index, slug)  # noqa: E731

    from services.ecosystem._agentstudio_interop import parse_skill_md_frontmatter

    candidates: list[dict[str, Any]] = []
    for entry in entries:
        slug = entry["name"]
        try:
            fetched = fetch_one(slug)
        except ImportFetchError as exc:
            candidates.append({
                "slug": slug, "allowed": False, "reason": f"fetch failed: {exc}",
                "license_evidence": {}, "resolved_sha": None, "source_url": f"https://{domain}",
            })
            continue

        frontmatter = parse_skill_md_frontmatter(fetched["skill_md_text"])
        license_str = frontmatter.get("license", "")
        allowed = is_allowed_license(license_str)
        candidates.append({
            "slug": slug,
            "display_name": frontmatter.get("name") or slug,
            "description": fetched["index_description"] or frontmatter.get("description", ""),
            "license_evidence": {"skill_md_license_field": license_str or None},
            "resolved_sha": fetched["resolved_sha"],
            "source_url": fetched["source_url"],
            # Included so a caller (the catalog crawler) can hash/fast-safety-
            # check the actual content without a second fetch -- discarded by
            # import_from_well_known()'s own separate call path, which is
            # unaffected by this addition.
            "skill_md_text": fetched["skill_md_text"] if allowed else None,
            "files": fetched["files"] if allowed else None,
            "allowed": allowed,
            "reason": "" if allowed else f"SKILL.md license: field ({license_str or None!r}) is missing or not MIT/Apache-2.0",
        })

    return candidates
