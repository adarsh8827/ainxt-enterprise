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
# Disclosed scope limitation: fetches SKILL.md only, not a directory of
# bundled scripts/references -- create_via_write's own shape (a skill
# with no required bundle files) is what this phase's import path
# produces. Extending to a full directory tree is future work, not
# silently faked here.
# ============================================================

from __future__ import annotations

import base64
from typing import Any

from connectors.net_relay import relay_request
from services.ecosystem.errors import ImportFetchError, ImportRateLimitedError, LicenseNotAllowedError
from services.ecosystem.import_adapters import github_credential
from services.ecosystem.import_adapters.fetch_cache import get_cached, put_cached
from services.ecosystem.import_adapters.ssrf_guard import assert_safe_https_url
from services.ecosystem.license_policy import is_allowed_license

_API_BASE = "https://api.github.com"
_MAX_SKILL_MD_BYTES = 256 * 1024  # matches create_service.py's own upload cap


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
