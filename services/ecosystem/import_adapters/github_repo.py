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
from typing import Any, Callable
from urllib.parse import quote

from connectors.net_relay import relay_request
from services.ecosystem.errors import ImportFetchError, ImportRateLimitedError, LicenseNotAllowedError
from services.ecosystem.import_adapters import github_credential
from services.ecosystem.import_adapters.fetch_cache import get_cached, put_cached
from services.ecosystem.import_adapters.skill_path_utils import (
    _LICENSE_BASENAMES,
    assert_safe_relative_path,
    clean_display_name,
    find_license_file_in_folder,
    find_nearest_license_file,
    guess_license_from_text,
    is_safe_tree_path,
    resolve_effective_license,
    scan_folder_for_conflicting_license_evidence,
)
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
#
# clean_display_name()/assert_safe_relative_path()/is_safe_tree_path()/
# find_license_file_in_folder()/find_nearest_license_file()/
# guess_license_from_text()/resolve_effective_license()/
# scan_folder_for_conflicting_license_evidence() moved to the source-
# agnostic services/ecosystem/import_adapters/skill_path_utils.py (task:
# generic git source adapter, 2026-09-30) -- behavior unchanged, now
# shared with git_repo.py rather than duplicated.

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
    commit_ref = ref or repo_meta.get("default_branch") or "HEAD"
    commit_meta = _github_get(f"/repos/{owner}/{name}/commits/{commit_ref}")
    resolved_sha = commit_meta.get("sha")
    if not resolved_sha:
        raise ImportFetchError(f"could not resolve {commit_ref!r} to a commit sha for {repo!r}")

    # BUG-U06 fix: the GitHub API's own spdx_id is a linguist-based guess
    # and can be wrong for a real, correctly-MIT/Apache-licensed repo (the
    # same "NOASSERTION" gap already documented and already handled, via
    # this exact guess_license_from_text() fallback, by every OTHER
    # license-resolution path in this module -- import_repo_metadata(),
    # discover_skills_in_repo()/resolve_effective_license(). This was the
    # one function the basic single-repo "Import a skill" dialog actually
    # calls, and it alone had no fallback at all -- confirmed live against
    # lodash/lodash (API reports NOASSERTION for a repo with a real,
    # unmodified MIT LICENSE file). Needs resolved_sha first (to fetch the
    # tree/LICENSE file), so this check now runs after commit resolution
    # above instead of before it -- no extra network calls for the common
    # case where the API's own signal already resolves cleanly.
    repo_license = ((repo_meta.get("license") or {}).get("spdx_id")) or ""
    if not is_allowed_license(repo_license):
        tree_meta = _fetch_tree(owner, name, resolved_sha)
        all_paths = {e["path"] for e in tree_meta.get("tree", []) if e.get("type") == "blob"}
        license_file_path = find_license_file_in_folder(all_paths, "", _LICENSE_BASENAMES)
        if license_file_path:
            license_text = _fetch_text_file(owner, name, resolved_sha, license_file_path)
            guessed = guess_license_from_text(license_text)
            if guessed:
                repo_license = guessed
    if not is_allowed_license(repo_license):
        raise LicenseNotAllowedError(
            f"repo {repo!r}'s detected SPDX license {repo_license!r} is not MIT/Apache-2.0",
            stage="import_precheck", declared_license=repo_license or None,
        )

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

    display_name = clean_display_name(frontmatter.get("name", ""), name)
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


def _text_fetcher(owner: str, name: str, sha: str) -> Callable[[str, int], str]:
    """A skill_path_utils.FetchText closure over this pinned commit --
    what resolve_effective_license()/scan_folder_for_conflicting_license_evidence()
    call to read a file's text, without either of them needing to know
    anything about GitHub/raw.githubusercontent.com/the ETag cache."""
    return lambda file_path, max_bytes=_MAX_SKILL_MD_BYTES: _fetch_text_file(owner, name, sha, file_path, max_bytes)


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
    scoped_path = assert_safe_relative_path(path)

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

    blob_entries = [e for e in entries if e.get("type") == "blob" and is_safe_tree_path(e.get("path", ""))]
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

        fetch_text = _text_fetcher(owner, name, resolved_sha)
        effective_license, license_source = resolve_effective_license(
            fetch_text, folder, all_paths, repo_license, skill_license_field,
        )
        allowed = is_allowed_license(effective_license)
        reason = "" if allowed else f"effective license ({effective_license or None!r}, via {license_source}) is not MIT/Apache-2.0"

        conflict = None
        if allowed:
            conflict = scan_folder_for_conflicting_license_evidence(
                fetch_text, folder, all_paths, entry_sizes, skip_paths={skill_md_path},
            )
            if conflict:
                allowed = False
                reason = f"{conflict[0]!r} declares {conflict[1]!r}, conflicting with the otherwise-effective {effective_license!r}"

        candidates.append({
            "path": folder,
            "skill_md_path": skill_md_path,
            "display_name": clean_display_name(frontmatter.get("name", ""), folder.rsplit("/", 1)[-1] if folder else name),
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
    scoped_path = assert_safe_relative_path(path)
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
    blob_entries = [e for e in entries if e.get("type") == "blob" and is_safe_tree_path(e.get("path", ""))]
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

    fetch_text = _text_fetcher(owner, name, resolved_sha)
    effective_license, license_source = resolve_effective_license(
        fetch_text, scoped_path, all_paths, repo_license, file_license,
    )
    if not is_allowed_license(effective_license):
        raise LicenseNotAllowedError(
            f"{repo!r}'s folder {scoped_path!r} effective license ({effective_license!r}, via {license_source}) "
            "is not MIT/Apache-2.0",
            stage="import_precheck", declared_license=effective_license or None,
        )

    conflict = scan_folder_for_conflicting_license_evidence(
        fetch_text, scoped_path, all_paths, entry_sizes, skip_paths={skill_md_path},
    )
    if conflict:
        raise LicenseNotAllowedError(
            f"{repo!r}'s folder {scoped_path!r}: {conflict[0]!r} declares {conflict[1]!r}, conflicting with "
            f"the otherwise-effective {effective_license!r}",
            stage="import_precheck", declared_license=conflict[1],
        )

    display_name = clean_display_name(frontmatter.get("name", ""), scoped_path.rsplit("/", 1)[-1])
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


def search_repos_by_query(query: str, page: int = 1) -> list[dict[str, Any]]:
    """Live search (external sources plan §10, real gap found live
    2026-09-29): a free-text GitHub repo search, unlike
    search_repos_by_topic()'s exact-topic match -- the query IS whatever
    a live-search caller typed. Reuses the exact same `_github_get()`
    (ETag-cached, credential-aware, rate-limit-detecting) and response
    shape search_repos_by_topic() already established -- this is a
    discovery/search hint, not a license verdict; a caller must still run
    the real license/neutrality check (create_via_import() already does
    this on install) before treating a hit as installable.
    """
    path = f"/search/repositories?q={quote(query)}&per_page={_MAX_SEARCH_RESULTS_PER_PAGE}&page={max(1, page)}"
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


def import_repo_metadata(repo: str) -> dict[str, Any]:
    """Repo-level metadata for a whole-repo-as-one-item pointer (Connectors
    phase, McpServerRepoSource in sources_config.py) -- unlike
    import_from_github() above, this does NOT require a SKILL.md at the
    repo root; it's for a source whose content isn't fetched at crawl
    time at all (an mcp_server pointer with content_hash="", same as an
    mcp_registry entry).

    License resolution is intentionally NOT just the GitHub API's own
    spdx_id: that field is a linguist-based guess and can be wrong for a
    real, correctly-MIT-licensed repo whose LICENSE file has any
    non-boilerplate preamble (confirmed live, 2026-09-30, against
    activepieces/activepieces -- API reports "NOASSERTION" for a LICENSE
    file whose applicable-to-most-of-the-repo body is a verified,
    unmodified MIT license text). Falls back to a real text-guess against
    the actual LICENSE file content, via the same _guess_license_from_text
    this module already uses for per-skill license resolution, whenever
    the API's own signal doesn't already recognize the repo as
    MIT/Apache-2.0.

    Returns {"resolved_sha", "license", "license_evidence", "display_name",
    "description", "source_url"}. Raises ImportFetchError.
    """
    owner, name = _parse_owner_repo(repo)
    repo_meta = _github_get(f"/repos/{owner}/{name}")
    resolved_sha = get_resolved_head_sha(repo)

    api_license = ((repo_meta.get("license") or {}).get("spdx_id")) or ""
    if is_allowed_license(api_license):
        license_spdx, license_evidence = api_license, "GitHub API license detection"
    else:
        tree_meta = _fetch_tree(owner, name, resolved_sha)
        all_paths = {e["path"] for e in tree_meta.get("tree", []) if e.get("type") == "blob"}
        license_file_path = find_license_file_in_folder(all_paths, "", _LICENSE_BASENAMES)
        guessed = None
        if license_file_path:
            license_text = _fetch_text_file(owner, name, resolved_sha, license_file_path)
            guessed = guess_license_from_text(license_text)
        license_spdx = guessed or api_license
        license_evidence = (
            f"LICENSE file at {license_file_path!r} (text-guess; API reported {api_license!r})"
            if guessed else "GitHub API license detection"
        )

    return {
        "resolved_sha": resolved_sha,
        "license": license_spdx or "",
        "license_evidence": license_evidence,
        "display_name": repo_meta.get("name", name),
        "description": repo_meta.get("description") or "",
        "source_url": f"https://github.com/{owner}/{name}",
    }


def import_activepieces_piece(piece: str) -> dict[str, Any]:
    """One community piece from the fixed, hardcoded activepieces/
    activepieces repo (Connectors phase, ActivepiecesSource in
    sources_config.py) -- a piece's own package.json carries NO license
    field (verified live, 2026-09-30: every sampled community piece's
    package.json has name/version/main/types/dependencies only). License
    comes from the nearest LICENSE file to packages/pieces/community/
    <piece>/ (falls through to the repo root's own LICENSE, which pieces
    always resolve to in practice -- packages/pieces/community/ is never
    itself nested under packages/ee/, verified via the live repo tree),
    text-guessed the same way as import_repo_metadata() above (NOT the
    GitHub API's spdx_id, which is "NOASSERTION" for this repo's own
    multi-license LICENSE file structure even though the community-piece-
    applicable portion is plain, verified MIT text).

    Returns {"resolved_sha", "license", "license_evidence", "display_name",
    "description", "source_url", "package_name"}. Raises ImportFetchError
    if the piece directory doesn't exist.
    """
    owner, name = "activepieces", "activepieces"
    piece_slug = piece.strip().lower()
    piece_folder = f"packages/pieces/community/{piece_slug}"
    resolved_sha = get_resolved_head_sha(f"{owner}/{name}")

    tree_meta = _fetch_tree(owner, name, resolved_sha)
    all_paths = {e["path"] for e in tree_meta.get("tree", []) if e.get("type") == "blob"}
    if not any(p.startswith(f"{piece_folder}/") for p in all_paths):
        raise ImportFetchError(f"{piece_folder!r} is not a piece directory in activepieces/activepieces")

    # _find_nearest_license_file deliberately never checks the repo root
    # (that's a separate fallback everywhere else in this module too --
    # see _resolve_effective_license above) -- but every real Activepieces
    # piece's own LICENSE resolves to the repo root in practice (no piece
    # folder or its ancestors up to "packages/" carries its own LICENSE
    # file), so the root check is NOT optional here the way it might be
    # for a skill repo with per-skill LICENSE files.
    license_file_path = find_nearest_license_file(all_paths, piece_folder) or find_license_file_in_folder(all_paths, "", _LICENSE_BASENAMES)
    guessed = None
    if license_file_path:
        license_text = _fetch_text_file(owner, name, resolved_sha, license_file_path)
        guessed = guess_license_from_text(license_text)

    package_json_path = f"{piece_folder}/package.json"
    package_name = piece_slug
    if package_json_path in all_paths:
        try:
            pkg = json.loads(_fetch_text_file(owner, name, resolved_sha, package_json_path))
            package_name = pkg.get("name", piece_slug)
        except Exception:
            pass

    return {
        "resolved_sha": resolved_sha,
        "license": guessed or "",
        "license_evidence": (
            f"LICENSE file at {license_file_path!r} (text-guess)" if guessed and license_file_path
            else "no LICENSE file found in this piece's own or any ancestor folder"
        ),
        "display_name": piece_slug.replace("-", " ").title(),
        "description": f"Activepieces integration piece for {piece_slug} ({package_name}).",
        "source_url": f"https://github.com/{owner}/{name}/tree/{resolved_sha}/{piece_folder}",
        "package_name": package_name,
    }
