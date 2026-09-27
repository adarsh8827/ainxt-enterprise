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

import base64
import json
from typing import Any

from connectors.net_relay import relay_request
from services.ecosystem.errors import ImportFetchError, ImportRateLimitedError, LicenseNotAllowedError
from services.ecosystem.import_adapters import github_credential
from services.ecosystem.import_adapters.fetch_cache import get_cached, put_cached
from services.ecosystem.import_adapters.ssrf_guard import assert_safe_https_url
from services.ecosystem.license_policy import is_allowed_license

_API_BASE = "https://api.github.com"
_MAX_SKILL_MD_BYTES = 256 * 1024  # matches create_service.py's own upload cap

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


def _github_get(path: str) -> dict[str, Any]:
    url = assert_safe_https_url(f"{_API_BASE}{path}")
    headers = {"Accept": "application/vnd.github+json", **github_credential.auth_headers()}
    resp = relay_request("GET", url, headers=headers, timeout=15.0)

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

    try:
        return resp.json()
    except Exception as exc:
        raise ImportFetchError(f"GitHub API returned a non-JSON response for {path!r}") from exc


def _parse_owner_repo(repo: str) -> tuple[str, str]:
    parts = repo.strip().strip("/").split("/")
    if len(parts) != 2 or not all(parts):
        raise ImportFetchError(f"github_repo ref {repo!r} must be exactly 'owner/repo'")
    return parts[0], parts[1]


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

    fetch_identity = f"github_repo:{owner}/{name}:{resolved_sha}"
    cached = get_cached(fetch_identity)
    if cached is not None:
        skill_md_text = cached.decode("utf-8", errors="replace")
    else:
        content_meta = _github_get(f"/repos/{owner}/{name}/contents/SKILL.md?ref={resolved_sha}")
        if content_meta.get("type") != "file":
            raise ImportFetchError(f"{repo!r}@{resolved_sha[:12]} has no SKILL.md file at the repo root")
        if content_meta.get("size", 0) > _MAX_SKILL_MD_BYTES:
            raise ImportFetchError(
                f"{repo!r}'s SKILL.md exceeds the {_MAX_SKILL_MD_BYTES // 1024}KB limit"
            )
        encoded = content_meta.get("content", "")
        try:
            raw = base64.b64decode(encoded)
        except Exception as exc:
            raise ImportFetchError(f"could not decode SKILL.md content for {repo!r}") from exc
        skill_md_text = raw.decode("utf-8", errors="replace")
        put_cached(fetch_identity, raw)

    from services.ecosystem._agentstudio_interop import parse_skill_md_frontmatter

    frontmatter = parse_skill_md_frontmatter(skill_md_text)
    file_license = frontmatter.get("license", "")
    if not is_allowed_license(file_license):
        raise LicenseNotAllowedError(
            f"{repo!r}'s SKILL.md license: field ({file_license!r}) is not MIT/Apache-2.0",
            stage="import_precheck", declared_license=file_license or None,
        )

    display_name = frontmatter.get("name", name)
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
    fetch_identity = f"github_repo:{owner}/{name}:{sha}:{file_path}"
    cached = get_cached(fetch_identity)
    if cached is not None:
        return cached.decode("utf-8", errors="replace")

    content_meta = _github_get(f"/repos/{owner}/{name}/contents/{file_path}?ref={sha}")
    if content_meta.get("type") != "file":
        raise ImportFetchError(f"{file_path!r} is not a file in this repo")
    if content_meta.get("size", 0) > max_bytes:
        raise ImportFetchError(f"{file_path!r} exceeds the {max_bytes // 1024}KB limit")
    encoded = content_meta.get("content", "")
    try:
        raw = base64.b64decode(encoded)
    except Exception as exc:
        raise ImportFetchError(f"could not decode {file_path!r} content") from exc
    put_cached(fetch_identity, raw)
    return raw.decode("utf-8", errors="replace")


def _find_license_file(paths: set[str], folder: str) -> str | None:
    """A LICENSE/LICENSE.md/LICENSE.txt sitting DIRECTLY inside `folder`
    (not a nested subfolder, not an ancestor) -- `folder` == "" means the
    repo root."""
    prefix = f"{folder}/" if folder else ""
    for candidate in paths:
        if prefix and not candidate.startswith(prefix):
            continue
        rest = candidate[len(prefix):] if prefix else candidate
        if "/" in rest:
            continue
        if rest.lower() in _LICENSE_BASENAMES:
            return candidate
    return None


def _guess_license_from_text(text: str) -> str | None:
    """Best-effort SPDX guess from a LICENSE file's own text. This adapter
    has no full license-classifier dependency (and doesn't need one --
    the catalog only ever allows two families); anything that doesn't
    clearly match either returns None, which is_allowed_license(None)
    correctly treats as not-allowed rather than guessing optimistically.
    """
    lowered = text.lower()
    if "apache license" in lowered and "version 2.0" in lowered:
        return "Apache-2.0"
    if "mit license" in lowered or "permission is hereby granted, free of charge" in lowered:
        return "MIT"
    return None


def discover_skills_in_repo(repo: str, ref: str | None = None, path: str | None = None) -> list[dict[str, Any]]:
    """Finds every SKILL.md in `repo` (optionally scoped to a subdirectory
    `path`) and returns one candidate dict per skill, each carrying its own
    license-evidence and allow/deny verdict -- nothing is imported here.
    The caller (an admin picking from the starter catalog) reviews this
    list, including the excluded ones and their reasons, before calling
    import_from_github_path() on the ones actually wanted.

    Per-skill license precedence: a LICENSE/LICENSE.md/LICENSE.txt file
    sitting directly in the skill's own folder wins if present; otherwise
    the repo-level detected license is the fallback. Either way, the
    SKILL.md's own `license:` frontmatter field must ALSO be MIT/Apache-2.0
    -- both signals must pass (same AND-logic as import_from_github's
    root-level check).

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

    all_paths = {
        e.get("path", "") for e in entries
        if e.get("type") == "blob" and _is_safe_tree_path(e.get("path", ""))
    }

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

        license_file_path = _find_license_file(all_paths, folder)
        if license_file_path:
            license_text = _fetch_text_file(owner, name, resolved_sha, license_file_path)
            folder_license_source = "folder LICENSE file"
            folder_license_spdx_or_none = _guess_license_from_text(license_text)
            effective_license = folder_license_spdx_or_none or ""
        else:
            folder_license_source = "repo LICENSE (fallback)"
            folder_license_spdx_or_none = repo_license or None
            effective_license = repo_license

        folder_or_repo_allowed = is_allowed_license(effective_license)
        skill_md_allowed = is_allowed_license(skill_license_field)
        allowed = folder_or_repo_allowed and skill_md_allowed
        reason = ""
        if not folder_or_repo_allowed:
            reason = f"folder/repo license ({effective_license or None!r}) is not MIT/Apache-2.0"
        elif not skill_md_allowed:
            reason = f"SKILL.md license field ({skill_license_field or None!r}) is not MIT/Apache-2.0"

        candidates.append({
            "path": folder,
            "skill_md_path": skill_md_path,
            "display_name": frontmatter.get("name", folder.rsplit("/", 1)[-1] if folder else name),
            "description": frontmatter.get("description", ""),
            "license_evidence": {
                "repo_license": repo_license or None,
                "folder_license_source": folder_license_source,
                "folder_license_spdx_or_none": folder_license_spdx_or_none,
                "skill_md_license_field": skill_license_field or None,
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

    prefix = scoped_path + "/"
    folder_paths = {
        e.get("path", "") for e in entries
        if e.get("type") == "blob" and _is_safe_tree_path(e.get("path", ""))
        and (e.get("path", "") == scoped_path or e.get("path", "").startswith(prefix))
    }

    skill_md_path = f"{scoped_path}/SKILL.md"
    if skill_md_path not in folder_paths:
        raise ImportFetchError(f"{repo!r}@{resolved_sha[:12]} has no SKILL.md at {scoped_path!r}")

    skill_md_text = _fetch_text_file(owner, name, resolved_sha, skill_md_path)

    from services.ecosystem._agentstudio_interop import parse_skill_md_frontmatter

    frontmatter = parse_skill_md_frontmatter(skill_md_text)
    file_license = frontmatter.get("license", "")

    license_file_path = _find_license_file(folder_paths, scoped_path)
    if license_file_path:
        license_text = _fetch_text_file(owner, name, resolved_sha, license_file_path)
        effective_license = _guess_license_from_text(license_text) or ""
    else:
        effective_license = repo_license

    if not is_allowed_license(effective_license):
        raise LicenseNotAllowedError(
            f"{repo!r}'s folder {scoped_path!r} license ({effective_license!r}) is not MIT/Apache-2.0",
            stage="import_precheck", declared_license=effective_license or None,
        )
    if not is_allowed_license(file_license):
        raise LicenseNotAllowedError(
            f"{repo!r}'s SKILL.md license: field ({file_license!r}) is not MIT/Apache-2.0",
            stage="import_precheck", declared_license=file_license or None,
        )

    display_name = frontmatter.get("name", scoped_path.rsplit("/", 1)[-1])
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
        "license": file_license,
        "display_name": display_name,
        "description": description,
        "resolved_sha": resolved_sha,
        "source_url": f"https://github.com/{owner}/{name}/tree/{resolved_sha}/{scoped_path}",
    }
