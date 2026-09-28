# SPDX-License-Identifier: MIT
# ============================================================
# github_repo import adapter (task I, pre-M3) — SKILL.md bundles from a
# public GitHub repository.
#
# License pre-check BEFORE any content download, per the task spec: the
# repo's own SPDX license (GitHub's license-detection API) AND the
# SKILL.md's own `license:` frontmatter field must BOTH be MIT/Apache-2.0
# -- either one failing blocks the whole import with LICENSE_NOT_ALLOWED.
# Two independent signals because a repo's detected SPDX license can
# legitimately disagree with an individual file's own declared license
# (a permissively-licensed repo can still bundle a differently-licensed
# file) -- checking only one would miss that.
#
# Extended (explicit decision, superseding the disclosed scope limitation
# above and docs/ecosystem/EXTERNAL_SOURCES_PLAN.md's original "keep the
# instance-side adapter root-only" recommendation): discover_skills_in_repo()
# and import_from_github_path() below add subdirectory-scoped discovery and
# import -- most real-world skill publishers ship one repo per collection,
# not one repo per skill, and root-only import can't reach any of them.
# import_from_github() itself is untouched; both are additive.
# ============================================================

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from connectors.net_relay import relay_request
from services.ecosystem.errors import ImportFetchError, ImportRateLimitedError, LicenseNotAllowedError
from services.ecosystem.import_adapters import github_credential
from services.ecosystem.import_adapters.fetch_cache import get_cached, put_cached
from services.ecosystem.import_adapters.ssrf_guard import assert_safe_https_url
from services.ecosystem.license_policy import is_allowed_license

_API_BASE = "https://api.github.com"
_RAW_BASE = "https://raw.githubusercontent.com"
_MAX_SKILL_MD_BYTES = 256 * 1024  # matches create_service.py's own upload cap

# Rate-limit accounting (task: crawl efficiency review, 2026-09-28). The
# external-sources crawler's own rehearsal runs exhausted GitHub's
# unauthenticated 60-req/hour budget almost immediately -- NOT because a
# configured GITHUB_IMPORT_TOKEN was somehow insufficient, but because
# no token was ever configured in that environment at all (confirmed
# directly: every 403 in that run's own log said "No GITHUB_IMPORT_TOKEN
# is configured"). Separately, and regardless of a token being present,
# the adapter's own call pattern was wasteful: one Contents-API call per
# file (SKILL.md, every conflict-scan file, every bundle file) plus a
# full repo-meta/commit/tree re-fetch in import_from_github_path() for
# every candidate discover_skills_in_repo() had *already* just fetched
# the same three things for, moments earlier, in the same process. Fixed
# below: file content now comes from raw.githubusercontent.com (not
# subject to the REST API's rate limit at all), and every api.github.com
# call is ETag-cached (a 304 response is documented by GitHub to NOT
# count against the rate limit either) -- so a same-run or same-day
# re-fetch of unchanged repo/commit/tree metadata costs nothing.
_total_requests_made = 0
_rate_limit_consuming_requests = 0


def get_api_call_stats() -> dict[str, int]:
    """{"total_requests": N, "rate_limit_consuming_requests": M} -- M <=
    N; the gap is 304s (ETag hits), which GitHub does not charge against
    the primary rate limit. Logged per crawl in the crawl report."""
    return {"total_requests": _total_requests_made, "rate_limit_consuming_requests": _rate_limit_consuming_requests}


def reset_api_call_stats() -> None:
    global _total_requests_made, _rate_limit_consuming_requests
    _total_requests_made = 0
    _rate_limit_consuming_requests = 0


# A SKILL.md's frontmatter "name" is normally already a fine, human-
# readable display name as-is ("Hello Skill", title case + spaces --
# test_import_clean_mit_skill_succeeds's own fixture, confirmed real via
# the actual GitHub API shape) -- this is deliberately NOT the strict
# kebab-case skill_factory/pipeline.py's _validate_skill_md() enforces
# for the AgentStudio create/upload flow's own "name" field, a different
# concept this module never runs that validator for at all. What's
# actually broken: a "::" inside the name, which is a NAMESPACING
# convention belonging to the source repo's own internal organization,
# never a display name. Real bug found live: google-labs-code/
# stitch-skills' own react-native/SKILL.md declares
# `name: stitch::react-native` -- fine for that repo's own purposes, but
# rendered verbatim as the item's title downstream ("stitch::react-native"
# instead of a clean name).
_DISPLAY_NAME_NAMESPACE_SEPARATOR_RE = re.compile(r"::")


def _clean_display_name(frontmatter_name: str, fallback: str) -> str:
    """Returns `frontmatter_name` unless it's empty or carries a "::"
    namespacing separator, in which case the folder/repo-derived
    `fallback` (already clean -- it's just a path segment) is used
    instead."""
    candidate = (frontmatter_name or "").strip()
    if candidate and not _DISPLAY_NAME_NAMESPACE_SEPARATOR_RE.search(candidate):
        return candidate
    return fallback


# Subdirectory discovery/import guards (task: starter-catalog subdirectory
# extension). Bundle-file caps mirror create_service.py's own upload-path
# constants (_UPLOAD_MAX_BUNDLE_FILE_BYTES / _UPLOAD_MAX_TOTAL_UNCOMPRESSED_
# BYTES) -- same numeric policy, not re-derived, cited rather than imported
# since create_service.py pulls in DB/session machinery this framework-
# agnostic adapter module has no other reason to depend on.
_MAX_TREE_ENTRIES = 20_000       # GitHub's own recursive-tree API truncates near this scale
_MAX_DISCOVERED_SKILLS = 200     # cap on SKILL.md files returned per discovery call
_MAX_BUNDLE_FILE_BYTES = 64 * 1024
_MAX_FOLDER_TOTAL_BYTES = 8 * 1024 * 1024
_LICENSE_BASENAMES = {"license", "license.md", "license.txt"}
# NOTICE/COPYING participate only in conflict detection (a real, concretely
# detected OTHER license in one of these blocks a skill even when the
# inheritance chain below would otherwise allow it) -- never in the
# inheritance chain itself, since a bare NOTICE file is typically pure
# attribution text _guess_license_from_text can't classify at all, and an
# unclassifiable file must never itself count as "not MIT/Apache" (that
# would spuriously block real MIT/Apache skills that simply carry one).
_OTHER_LICENSE_BASENAMES = {"copying", "copying.md", "copying.txt", "notice", "notice.md", "notice.txt"}
# Real, unambiguous machine-readable signal -- a bundled file's own
# SPDX-License-Identifier header comment. Scanned across a capped set of
# non-LICENSE/SKILL.md files in the skill's folder (never the whole repo);
# caps keep this from multiplying API calls per candidate under GitHub's
# unauthenticated 60-req/hour limit.
_SPDX_HEADER_RE = re.compile(r"SPDX-License-Identifier:\s*([A-Za-z0-9.\-+]+(?:\s+(?:OR|AND)\s+[A-Za-z0-9.\-+]+)*)")
_MAX_CONFLICT_SCAN_FILES = 8
_MAX_CONFLICT_SCAN_FILE_BYTES = 8 * 1024


def _github_get(path: str) -> dict[str, Any]:
    global _total_requests_made, _rate_limit_consuming_requests

    etag_cache_key = f"github_repo:etag:{path}"
    cached_raw = get_cached(etag_cache_key)
    cached_etag: str | None = None
    cached_body: str | None = None
    if cached_raw is not None:
        try:
            cached_obj = json.loads(cached_raw.decode("utf-8"))
            cached_etag = cached_obj.get("etag")
            cached_body = cached_obj.get("body")
        except (ValueError, UnicodeDecodeError, AttributeError):
            cached_etag = cached_body = None

    url = assert_safe_https_url(f"{_API_BASE}{path}")
    headers = {"Accept": "application/vnd.github+json", **github_credential.auth_headers()}
    if cached_etag:
        headers["If-None-Match"] = cached_etag
    resp = relay_request("GET", url, headers=headers, timeout=15.0)
    _total_requests_made += 1

    # Documented GitHub behavior: a 304 response does NOT count against
    # the primary rate limit -- deliberately not added to
    # _rate_limit_consuming_requests, unlike every other branch below.
    if resp.status_code == 304 and cached_body is not None:
        try:
            return json.loads(cached_body)
        except ValueError:
            pass  # corrupt cache entry -- fall through and treat as if nothing were cached

    _rate_limit_consuming_requests += 1

    if resp.status_code in (403, 429):
        retry_after = None
        raw_retry_after = resp.headers.get("Retry-After")
        if raw_retry_after:
            try:
                retry_after = int(raw_retry_after)
            except ValueError:
                pass
        hint = github_credential.configure_github_access_hint()
        message = f"GitHub API rate-limited fetching {path!r}"
        if hint:
            message = f"{message} — {hint}"
        raise ImportRateLimitedError(message, retry_after=retry_after)

    if resp.status_code == 404:
        raise ImportFetchError(f"GitHub returned 404 for {path!r} — repo, ref, or file not found")
    if resp.status_code != 200:
        raise ImportFetchError(f"GitHub API error fetching {path!r}: HTTP {resp.status_code}")

    body_text = resp.text
    etag = resp.headers.get("ETag") or resp.headers.get("etag")
    if etag:
        put_cached(etag_cache_key, json.dumps({"etag": etag, "body": body_text}).encode("utf-8"))

    try:
        return json.loads(body_text)
    except Exception as exc:
        raise ImportFetchError(f"GitHub API returned a non-JSON response for {path!r}") from exc


def _parse_owner_repo(repo: str) -> tuple[str, str]:
    parts = repo.strip().strip("/").split("/")
    if len(parts) != 2 or not all(parts):
        raise ImportFetchError(f"github_repo ref {repo!r} must be exactly 'owner/repo'")
    return parts[0], parts[1]


def get_resolved_head_sha(repo: str, ref: str | None = None) -> str:
    """Resolves `repo`'s HEAD (or `ref`) to an exact commit SHA using
    only the two lightweight, ETag-cacheable metadata calls (repo meta +
    commit lookup) -- no tree listing, no file fetch. Lets a caller (the
    crawler) check "has this repo moved since the last crawl" before
    doing any of the expensive per-skill discovery/import work."""
    owner, name = _parse_owner_repo(repo)
    repo_meta = _github_get(f"/repos/{owner}/{name}")
    commit_ref = ref or repo_meta.get("default_branch") or "HEAD"
    commit_meta = _github_get(f"/repos/{owner}/{name}/commits/{commit_ref}")
    resolved_sha = commit_meta.get("sha")
    if not resolved_sha:
        raise ImportFetchError(f"could not resolve {commit_ref!r} to a commit sha for {repo!r}")
    return resolved_sha


def import_from_github(repo: str, ref: str | None = None) -> dict[str, Any]:
    """
    repo: "owner/repo". ref: branch/tag/sha, or None for the repo's
    default branch HEAD.

    Returns {"manifest", "files", "license", "display_name",
    "description", "resolved_sha", "source_url"}. Raises ImportFetchError /
    ImportRateLimitedError / LicenseNotAllowedError.
    """
    owner, name = _parse_owner_repo(repo)

    repo_meta = _github_get(f"/repos/{owner}/{name}")
    repo_license = ((repo_meta.get("license") or {}).get("spdx_id")) or ""
    if not is_allowed_license(repo_license):
        raise LicenseNotAllowedError(
            f"repo {repo!r}'s detected SPDX license {repo_license!r} is not MIT/Apache-2.0",
            stage="import_precheck", declared_license=repo_license or None,
        )

    commit_ref = ref or repo_meta.get("default_branch") or "HEAD"
    commit_meta = _github_get(f"/repos/{owner}/{name}/commits/{commit_ref}")
    resolved_sha = commit_meta.get("sha")
    if not resolved_sha:
        raise ImportFetchError(f"could not resolve {commit_ref!r} to a commit sha for {repo!r}")

    # Content comes from raw.githubusercontent.com (via _fetch_text_file,
    # defined below), never the Contents API -- not subject to the REST
    # API's rate limit at all, and the same helper every other content
    # fetch in this module already uses.
    skill_md_text = _fetch_text_file(owner, name, resolved_sha, "SKILL.md")

    from services.ecosystem._agentstudio_interop import parse_skill_md_frontmatter

    frontmatter = parse_skill_md_frontmatter(skill_md_text)
    file_license = frontmatter.get("license", "")
    if not is_allowed_license(file_license):
        raise LicenseNotAllowedError(
            f"{repo!r}'s SKILL.md license: field ({file_license!r}) is not MIT/Apache-2.0",
            stage="import_precheck", declared_license=file_license or None,
        )

    display_name = _clean_display_name(frontmatter.get("name", ""), name)
    description = frontmatter.get("description", "")
    manifest = {"name": display_name, "description": description, "instructions": skill_md_text}

    return {
        "manifest": manifest,
        "files": {},
        "license": file_license,
        "display_name": display_name,
        "description": description,
        "resolved_sha": resolved_sha,
        "source_url": f"https://github.com/{owner}/{name}",
    }


def _assert_safe_relative_path(path: str | None) -> str | None:
    """Normalizes an optional caller-supplied subdirectory scope and
    rejects path-traversal attempts. Returns None for "no scope" (whole
    repo), or the cleaned relative path (no leading/trailing slash) --
    never raises for a merely-empty path, only for one that tries to
    escape the repo root."""
    if path is None:
        return None
    cleaned = path.strip().strip("/")
    if not cleaned:
        return None
    if cleaned.startswith("/") or ":" in cleaned or "\\" in cleaned:
        raise ImportFetchError(f"path {path!r} is not a valid repo-relative subdirectory")
    segments = cleaned.split("/")
    if any(seg in ("", ".", "..") for seg in segments):
        raise ImportFetchError(f"path {path!r} contains an invalid or traversal path segment")
    return cleaned


def _is_safe_tree_path(entry_path: str) -> bool:
    """Defense-in-depth guard on every path GitHub's tree API returns --
    treated as untrusted input regardless of how unlikely a real
    traversal-shaped entry from GitHub itself would be."""
    if not entry_path or entry_path.startswith("/") or "\\" in entry_path:
        return False
    return ".." not in entry_path.split("/")


def _fetch_tree(owner: str, name: str, sha: str) -> dict[str, Any]:
    fetch_identity = f"github_tree:{owner}/{name}:{sha}"
    cached = get_cached(fetch_identity)
    if cached is not None:
        return json.loads(cached.decode("utf-8"))
    tree_meta = _github_get(f"/repos/{owner}/{name}/git/trees/{sha}?recursive=1")
    put_cached(fetch_identity, json.dumps(tree_meta).encode("utf-8"))
    return tree_meta


def _fetch_text_file(owner: str, name: str, sha: str, file_path: str, max_bytes: int = _MAX_SKILL_MD_BYTES) -> str:
    """Fetches one file's text content at a pinned commit SHA, straight
    from raw.githubusercontent.com -- never the Contents API. This is
    the single biggest source of rate-limit consumption this adapter
    had (one API call per file: every SKILL.md, every conflict-scan
    file, every bundle file); the raw content host serves the same
    bytes with no JSON/base64 wrapping and is not subject to the REST
    API's rate limit at all. Still cached (24h, matching every other
    fetch in this module) so a re-run of the same commit doesn't even
    need the network."""
    fetch_identity = f"github_repo:{owner}/{name}:{sha}:{file_path}"
    cached = get_cached(fetch_identity)
    if cached is not None:
        return cached.decode("utf-8", errors="replace")

    encoded_path = "/".join(quote(segment, safe="") for segment in file_path.split("/"))
    url = assert_safe_https_url(f"{_RAW_BASE}/{owner}/{name}/{sha}/{encoded_path}")
    resp = relay_request("GET", url, timeout=15.0)
    if resp.status_code == 404:
        raise ImportFetchError(f"{file_path!r} is not a file in this repo (raw content 404)")
    if resp.status_code != 200:
        raise ImportFetchError(f"raw content fetch for {file_path!r} returned HTTP {resp.status_code}")
    raw = resp.content
    if len(raw) > max_bytes:
        raise ImportFetchError(f"{file_path!r} exceeds the {max_bytes // 1024}KB limit")
    put_cached(fetch_identity, raw)
    return raw.decode("utf-8", errors="replace")


def _find_license_file_in_folder(paths: set[str], folder: str, basenames: set[str]) -> str | None:
    """A file whose basename is in `basenames` sitting DIRECTLY inside
    `folder` (not a nested subfolder) -- `folder` == "" means the repo
    root."""
    prefix = f"{folder}/" if folder else ""
    for candidate in paths:
        if prefix and not candidate.startswith(prefix):
            continue
        rest = candidate[len(prefix):] if prefix else candidate
        if "/" in rest:
            continue
        if rest.lower() in basenames:
            return candidate
    return None


def _ancestor_folders(folder: str) -> list[str]:
    """`folder`'s own path, then each enclosing directory, nearest first,
    stopping BEFORE the repo root (`""`) -- the root's license is handled
    separately via the GitHub-API-provided repo_license, not a text guess,
    so it is deliberately excluded from this list."""
    if not folder:
        return []
    parts = folder.split("/")
    return ["/".join(parts[:i]) for i in range(len(parts), 0, -1)]


def _find_nearest_license_file(paths: set[str], folder: str) -> str | None:
    """The nearest LICENSE/LICENSE.md/LICENSE.txt to `folder`, checking the
    skill's own folder first and then each enclosing directory in turn
    (nearest wins) -- never the repo root itself (that's the separate,
    GitHub-API-provided repo_license fallback)."""
    for candidate_folder in _ancestor_folders(folder):
        found = _find_license_file_in_folder(paths, candidate_folder, _LICENSE_BASENAMES)
        if found:
            return found
    return None


def _guess_license_from_text(text: str) -> str | None:
    """Best-effort SPDX guess from a LICENSE-shaped file's own text.

    Returns an SPDX-ish id for the license families this adapter actually
    recognizes -- MIT/Apache-2.0 (the only two ever allowed) plus a small
    set of common OTHER families (GPL/LGPL/BSD/MPL/ISC) recognized ONLY so
    a real, concrete conflict can be reported instead of a bare "unknown".
    Anything that doesn't clearly match ANY of these returns None -- an
    ambiguous file (e.g. a bare NOTICE attribution blurb) must never count
    as "detected as some other license" and must never, by itself, block
    an otherwise-MIT/Apache skill.
    """
    lowered = text.lower()
    if "apache license" in lowered and "version 2.0" in lowered:
        return "Apache-2.0"
    if "mit license" in lowered or "permission is hereby granted, free of charge" in lowered:
        return "MIT"
    if "gnu general public license" in lowered or "gnu lesser general public license" in lowered:
        return "GPL"
    if "mozilla public license" in lowered:
        return "MPL-2.0"
    if "redistributions of source code must retain" in lowered:
        return "BSD"
    if "permission to use, copy, modify, and/or distribute this software" in lowered:
        return "ISC"
    return None


def _resolve_effective_license(
    owner: str, name: str, resolved_sha: str, folder: str, all_paths: set[str],
    repo_license: str, skill_license_field: str,
) -> tuple[str | None, str]:
    """Inheritance order (first found wins, per explicit review): the
    skill's own SKILL.md `license:` field -> the nearest LICENSE file in
    its own folder or an enclosing folder -> the repo-root SPDX license.

    A present-but-wrong `license:` field is still "found" -- it is NOT
    skipped in favor of a folder LICENSE just because it would fail the
    allow-check; the field, when present at all, IS the effective
    declaration, and a wrong one correctly fails allow-listing on its own
    merits rather than being silently overridden by a more permissive
    fallback.

    Returns (effective_license_or_none, source_description).
    """
    if skill_license_field:
        return skill_license_field, "SKILL.md license: field"

    license_file_path = _find_nearest_license_file(all_paths, folder)
    if license_file_path:
        license_text = _fetch_text_file(owner, name, resolved_sha, license_file_path)
        guessed = _guess_license_from_text(license_text)
        return guessed, f"LICENSE file at {license_file_path!r}"

    return (repo_license or None), "repo LICENSE (fallback)"


def _scan_folder_for_conflicting_license_evidence(
    owner: str, name: str, resolved_sha: str, folder: str, all_paths: set[str],
    entry_sizes: dict[str, int], skip_paths: set[str],
) -> tuple[str, str] | None:
    """Real, concrete conflict signals inside the skill's own folder that
    must exclude it even when the inheritance chain above would otherwise
    allow it:
      1. A COPYING/NOTICE file (any LICENSE-basename already feeds the
         inheritance chain itself, so isn't re-checked here) whose text
         guesses to a CONCRETE, non-MIT/Apache family -- an ambiguous
         (None-guessed) COPYING/NOTICE is never treated as a conflict.
      1b. A LICENSE/LICENSE.md/LICENSE.txt sitting directly in the skill's
         OWN folder that concretely disagrees -- this matters specifically
         when a SKILL.md `license:` field is present (so it, not this
         file, determined the effective license per the inheritance
         order) but the folder ALSO carries its own conflicting LICENSE
         file; without this check a skill could declare "license: MIT" in
         its frontmatter while shipping an actual GPL LICENSE file
         alongside it, uncaught.
      2. Any other smallish file directly under the folder carrying its
         own `SPDX-License-Identifier:` header naming a non-MIT/Apache id
         -- an explicit, machine-readable per-file declaration always
         wins over inherited evidence, matching real-world monorepo
         practice.
    Capped (_MAX_CONFLICT_SCAN_FILES / _MAX_CONFLICT_SCAN_FILE_BYTES) to
    bound the extra API calls this costs under GitHub's unauthenticated
    rate limit -- a folder with more candidate files than the cap allows
    is scanned partially rather than exhaustively; this is a best-effort
    extra safety net, not the primary license gate.

    Returns (conflicting_file_path, conflicting_spdx_or_family) or None.
    """
    checked_license_paths: set[str] = set()
    for basenames in (_LICENSE_BASENAMES, _OTHER_LICENSE_BASENAMES):
        own_license_path = _find_license_file_in_folder(all_paths, folder, basenames)
        if own_license_path:
            checked_license_paths.add(own_license_path)
            text = _fetch_text_file(owner, name, resolved_sha, own_license_path, max_bytes=_MAX_CONFLICT_SCAN_FILE_BYTES)
            guessed = _guess_license_from_text(text)
            if guessed and not is_allowed_license(guessed):
                return own_license_path, guessed

    prefix = f"{folder}/" if folder else ""
    scan_candidates = sorted(
        p for p in all_paths
        if p not in skip_paths and p not in checked_license_paths
        and (p == folder or p.startswith(prefix))
        and 0 < entry_sizes.get(p, _MAX_CONFLICT_SCAN_FILE_BYTES + 1) <= _MAX_CONFLICT_SCAN_FILE_BYTES
    )[:_MAX_CONFLICT_SCAN_FILES]
    for candidate_path in scan_candidates:
        text = _fetch_text_file(owner, name, resolved_sha, candidate_path, max_bytes=_MAX_CONFLICT_SCAN_FILE_BYTES)
        match = _SPDX_HEADER_RE.search(text)
        if match and not is_allowed_license(match.group(1)):
            return candidate_path, match.group(1)

    return None


def discover_skills_in_repo(repo: str, ref: str | None = None, path: str | None = None) -> list[dict[str, Any]]:
    """Finds every SKILL.md in `repo` (optionally scoped to a subdirectory
    `path`) and returns one candidate dict per skill, each carrying its own
    license-evidence and allow/deny verdict -- nothing is imported here.
    The caller (an admin picking from the starter catalog) reviews this
    list, including the excluded ones and their reasons, before calling
    import_from_github_path() on the ones actually wanted.

    Per-skill license resolution (explicit review decision, superseding
    this function's original stricter AND-only rule): inheritance order is
    the SKILL.md's own `license:` field, then the nearest LICENSE file in
    the skill's own folder or an enclosing folder, then the repo-root SPDX
    license -- first one found applies, so a repo that is genuinely
    MIT/Apache-2.0 but simply never bothered with a redundant per-skill
    `license:` field is no longer spuriously rejected. A skill is still
    excluded outright if anything in its own folder actively CONFLICTS
    with an otherwise-allowed result: an explicit non-MIT/Apache
    `license:` field, a COPYING/NOTICE file that concretely guesses to a
    different family, or an `SPDX-License-Identifier:` header in one of
    its own bundled files naming a different license.

    Raises ImportFetchError for a malformed `path`, an unresolvable ref, or
    a repo tree too large to scan (truncated by GitHub, or over
    _MAX_TREE_ENTRIES/_MAX_DISCOVERED_SKILLS) -- never a LicenseNotAllowedError,
    since a per-candidate license failure is reported IN the list, not
    raised (only import_from_github_path raises on that).
    """
    owner, name = _parse_owner_repo(repo)
    scoped_path = _assert_safe_relative_path(path)

    repo_meta = _github_get(f"/repos/{owner}/{name}")
    repo_license = ((repo_meta.get("license") or {}).get("spdx_id")) or ""

    commit_ref = ref or repo_meta.get("default_branch") or "HEAD"
    commit_meta = _github_get(f"/repos/{owner}/{name}/commits/{commit_ref}")
    resolved_sha = commit_meta.get("sha")
    if not resolved_sha:
        raise ImportFetchError(f"could not resolve {commit_ref!r} to a commit sha for {repo!r}")

    tree_meta = _fetch_tree(owner, name, resolved_sha)
    if tree_meta.get("truncated"):
        raise ImportFetchError(
            f"{repo!r}@{resolved_sha[:12]}'s file tree is too large for GitHub to list in one call "
            "(truncated) -- narrow the search with a specific subdirectory `path` instead of the whole repo"
        )
    entries = tree_meta.get("tree") or []
    if len(entries) > _MAX_TREE_ENTRIES:
        raise ImportFetchError(f"{repo!r} has {len(entries)} tree entries, exceeding the {_MAX_TREE_ENTRIES} scan limit")

    blob_entries = [e for e in entries if e.get("type") == "blob" and _is_safe_tree_path(e.get("path", ""))]
    all_paths = {e.get("path", "") for e in blob_entries}
    entry_sizes = {e.get("path", ""): e.get("size", 0) for e in blob_entries}

    if scoped_path is not None:
        prefix = scoped_path + "/"
        candidate_paths = {p for p in all_paths if p == scoped_path or p.startswith(prefix)}
    else:
        candidate_paths = all_paths

    skill_md_paths = sorted(p for p in candidate_paths if p == "SKILL.md" or p.endswith("/SKILL.md"))
    if len(skill_md_paths) > _MAX_DISCOVERED_SKILLS:
        raise ImportFetchError(
            f"{repo!r} contains {len(skill_md_paths)} SKILL.md files, exceeding the "
            f"{_MAX_DISCOVERED_SKILLS} discovery limit -- narrow with `path`"
        )

    from services.ecosystem._agentstudio_interop import parse_skill_md_frontmatter

    candidates: list[dict[str, Any]] = []
    for skill_md_path in skill_md_paths:
        folder = skill_md_path.rsplit("/", 1)[0] if "/" in skill_md_path else ""
        skill_md_text = _fetch_text_file(owner, name, resolved_sha, skill_md_path)
        frontmatter = parse_skill_md_frontmatter(skill_md_text)
        skill_license_field = frontmatter.get("license", "")

        effective_license, license_source = _resolve_effective_license(
            owner, name, resolved_sha, folder, all_paths, repo_license, skill_license_field,
        )
        allowed = is_allowed_license(effective_license)
        reason = "" if allowed else f"effective license ({effective_license or None!r}, via {license_source}) is not MIT/Apache-2.0"

        conflict = None
        if allowed:
            conflict = _scan_folder_for_conflicting_license_evidence(
                owner, name, resolved_sha, folder, all_paths, entry_sizes, skip_paths={skill_md_path},
            )
            if conflict:
                allowed = False
                reason = f"{conflict[0]!r} declares {conflict[1]!r}, conflicting with the otherwise-effective {effective_license!r}"

        candidates.append({
            "path": folder,
            "skill_md_path": skill_md_path,
            "display_name": _clean_display_name(frontmatter.get("name", ""), folder.rsplit("/", 1)[-1] if folder else name),
            "description": frontmatter.get("description", ""),
            "license_evidence": {
                "repo_license": repo_license or None,
                "effective_license": effective_license,
                "effective_license_source": license_source,
                "skill_md_license_field": skill_license_field or None,
                "conflict": {"path": conflict[0], "declared": conflict[1]} if conflict else None,
            },
            "resolved_sha": resolved_sha,
            "allowed": allowed,
            "reason": reason,
        })

    return candidates


def import_from_github_path(repo: str, path: str, ref: str | None = None) -> dict[str, Any]:
    """Imports one skill from a specific subdirectory of `repo` (as
    identified by a prior discover_skills_in_repo() call), bundling every
    other file in that same folder into `files` alongside SKILL.md --
    unlike import_from_github(), which only ever reads the repo root's
    lone SKILL.md with no bundle files. Pinned to the resolved commit sha
    throughout (every content fetch uses `?ref={resolved_sha}`, never a
    mutable ref). Same return shape as import_from_github().

    Raises ImportFetchError for a malformed/missing path or oversized
    folder, LicenseNotAllowedError if either the folder/repo license or
    the SKILL.md's own license field isn't MIT/Apache-2.0.
    """
    owner, name = _parse_owner_repo(repo)
    scoped_path = _assert_safe_relative_path(path)
    if not scoped_path:
        raise ImportFetchError("import_from_github_path requires a non-empty folder path")

    repo_meta = _github_get(f"/repos/{owner}/{name}")
    repo_license = ((repo_meta.get("license") or {}).get("spdx_id")) or ""

    commit_ref = ref or repo_meta.get("default_branch") or "HEAD"
    commit_meta = _github_get(f"/repos/{owner}/{name}/commits/{commit_ref}")
    resolved_sha = commit_meta.get("sha")
    if not resolved_sha:
        raise ImportFetchError(f"could not resolve {commit_ref!r} to a commit sha for {repo!r}")

    tree_meta = _fetch_tree(owner, name, resolved_sha)
    if tree_meta.get("truncated"):
        raise ImportFetchError(
            f"{repo!r}@{resolved_sha[:12]}'s file tree is too large for GitHub to list in one call (truncated)"
        )
    entries = tree_meta.get("tree") or []
    if len(entries) > _MAX_TREE_ENTRIES:
        raise ImportFetchError(f"{repo!r} has {len(entries)} tree entries, exceeding the {_MAX_TREE_ENTRIES} scan limit")

    # Full-tree paths (not pre-filtered to the scoped folder) so the license
    # inheritance walk below can find a LICENSE file in an ENCLOSING folder,
    # not just the skill's own -- matching discover_skills_in_repo() exactly,
    # since a candidate marked "allowed" there must import with the same
    # verdict here. `folder_paths` (scoped-down) is still what actually gets
    # bundled into `files` further below.
    blob_entries = [e for e in entries if e.get("type") == "blob" and _is_safe_tree_path(e.get("path", ""))]
    all_paths = {e.get("path", "") for e in blob_entries}
    entry_sizes = {e.get("path", ""): e.get("size", 0) for e in blob_entries}

    prefix = scoped_path + "/"
    folder_paths = {p for p in all_paths if p == scoped_path or p.startswith(prefix)}

    skill_md_path = f"{scoped_path}/SKILL.md"
    if skill_md_path not in folder_paths:
        raise ImportFetchError(f"{repo!r}@{resolved_sha[:12]} has no SKILL.md at {scoped_path!r}")

    skill_md_text = _fetch_text_file(owner, name, resolved_sha, skill_md_path)

    from services.ecosystem._agentstudio_interop import parse_skill_md_frontmatter

    frontmatter = parse_skill_md_frontmatter(skill_md_text)
    file_license = frontmatter.get("license", "")

    effective_license, license_source = _resolve_effective_license(
        owner, name, resolved_sha, scoped_path, all_paths, repo_license, file_license,
    )
    if not is_allowed_license(effective_license):
        raise LicenseNotAllowedError(
            f"{repo!r}'s folder {scoped_path!r} effective license ({effective_license!r}, via {license_source}) "
            "is not MIT/Apache-2.0",
            stage="import_precheck", declared_license=effective_license or None,
        )

    conflict = _scan_folder_for_conflicting_license_evidence(
        owner, name, resolved_sha, scoped_path, all_paths, entry_sizes, skip_paths={skill_md_path},
    )
    if conflict:
        raise LicenseNotAllowedError(
            f"{repo!r}'s folder {scoped_path!r}: {conflict[0]!r} declares {conflict[1]!r}, conflicting with "
            f"the otherwise-effective {effective_license!r}",
            stage="import_precheck", declared_license=conflict[1],
        )

    display_name = _clean_display_name(frontmatter.get("name", ""), scoped_path.rsplit("/", 1)[-1])
    description = frontmatter.get("description", "")
    manifest = {"name": display_name, "description": description, "instructions": skill_md_text}

    files: dict[str, str] = {}
    total_bytes = 0
    for entry_path in sorted(folder_paths):
        if entry_path == skill_md_path:
            continue
        rel_path = entry_path[len(prefix):]
        text = _fetch_text_file(owner, name, resolved_sha, entry_path, max_bytes=_MAX_BUNDLE_FILE_BYTES)
        total_bytes += len(text.encode("utf-8"))
        if total_bytes > _MAX_FOLDER_TOTAL_BYTES:
            raise ImportFetchError(
                f"{repo!r}'s folder {scoped_path!r} exceeds the "
                f"{_MAX_FOLDER_TOTAL_BYTES // (1024 * 1024)}MB total bundle-file limit"
            )
        files[rel_path] = text

    return {
        "manifest": manifest,
        "files": files,
        # The actually-validated effective license (may be inherited from a
        # LICENSE file or the repo, not necessarily file_license itself,
        # e.g. when SKILL.md carries no license: field at all) -- this is
        # the license this import was actually allowed under.
        "license": effective_license,
        "display_name": display_name,
        "description": description,
        "resolved_sha": resolved_sha,
        "source_url": f"https://github.com/{owner}/{name}/tree/{resolved_sha}/{scoped_path}",
    }


# External-sources catalog crawler support (additive) -- topic search is
# discovery-only: it surfaces CANDIDATE repos for a human to add to the
# crawl allowlist (docs/ecosystem/catalog/sources.yaml) via a reviewed PR,
# never something the crawler itself trusts or fetches from automatically.
_MAX_SEARCH_RESULTS_PER_PAGE = 50


def search_repos_by_topic(topic: str, page: int = 1) -> list[dict[str, Any]]:
    """GitHub topic search (`GET /search/repositories?q=topic:{topic}`),
    unauthenticated-capable (github_credential.auth_headers() adds a token
    only if one is configured -- this call works without one, just at a
    lower rate limit). Returns each hit's own repo full_name/html_url/
    description/license/pushed_at -- callers still run the real
    discover_skills_in_repo() walk before treating anything here as a
    catalog candidate; this is a discovery hint, not a license verdict.
    """
    query = f"topic:{topic}" if topic and " " not in topic else f'topic:"{topic}"'
    path = f"/search/repositories?q={query}&per_page={_MAX_SEARCH_RESULTS_PER_PAGE}&page={max(1, page)}"
    data = _github_get(path)
    items = data.get("items") or []
    return [
        {
            "full_name": item.get("full_name", ""),
            "html_url": item.get("html_url", ""),
            "description": item.get("description") or "",
            "license_spdx": ((item.get("license") or {}).get("spdx_id")) or None,
            "pushed_at": item.get("pushed_at"),
            "stargazers_count": item.get("stargazers_count", 0),
        }
        for item in items
        if isinstance(item, dict) and item.get("full_name")
    ]
