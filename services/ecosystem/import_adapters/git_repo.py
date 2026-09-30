# SPDX-License-Identifier: MIT
# ============================================================
# git_repo import adapter (Connectors+Plugins phase follow-up, 2026-09-30)
# -- SKILL.md bundles from ANY git host reachable over plain git-over-HTTPS
# (gitlab.com, a self-hosted GitLab/Gitea/Bitbucket instance, or anything
# else that speaks the standard git smart-HTTP protocol), with no
# host-specific REST API required at all. Same license/discovery/
# neutrality/provenance/dedup contract as github_repo.py -- reuses that
# module's own path/license helpers (services/ecosystem/import_adapters/
# skill_path_utils.py, extracted for exactly this reuse) rather than
# re-deriving any of that logic.
#
# The one thing this adapter genuinely can't do that github_repo.py can:
# there is no API-reported repo-level SPDX license field for an arbitrary
# git host, so the repo-root license fallback here is ALWAYS a text-guess
# against the root LICENSE file (guess_license_from_text()) -- never a
# second, independent signal the way GitHub's license-detection API is.
# A repo with no real root LICENSE and no per-skill license: field simply
# has no effective license and is excluded, same as github_repo.py's own
# behavior when neither signal is present.
#
# Real git-protocol limitation, disclosed rather than worked around with
# something fragile: fetching an EXACT historical commit (not just a
# branch/tag tip) over git-over-HTTP requires the server to allow it
# (`uploadpack.allowReachableSHA1InWant`/`allowTipSHA1InWant`, on by
# default on gitlab.com and most modern self-hosted Git servers, off by
# default on GitHub -- which is WHY github_repo.py uses GitHub's own REST
# API instead of a real clone). _clone_at_ref() tries a direct shallow
# fetch of the requested ref first (works whether that ref is a
# branch/tag name at crawl time or the exact pinned commit SHA at install
# time, on any server that allows it); if the server rejects a raw-SHA
# fetch, it falls back to fetching `ref_hint` (the branch/tag actually
# configured in sources.yaml) and unshallowing only if the pinned commit
# isn't already the tip -- so an install still resolves correctly even
# against a server that only ever allows fetching named refs, at the cost
# of a heavier clone in that one fallback case.
# ============================================================

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Any, Callable
from urllib.parse import urlsplit

from services.ecosystem.errors import ImportFetchError, LicenseNotAllowedError
from services.ecosystem.import_adapters.skill_path_utils import (
    assert_safe_relative_path,
    clean_display_name,
    find_license_file_in_folder,
    guess_license_from_text,
    is_safe_tree_path,
    resolve_effective_license,
    scan_folder_for_conflicting_license_evidence,
)
from services.ecosystem.license_policy import is_allowed_license

# Same numeric policy as github_repo.py -- not re-derived, cited.
_MAX_SKILL_MD_BYTES = 256 * 1024
_MAX_DISCOVERED_SKILLS = 200
_MAX_BUNDLE_FILE_BYTES = 64 * 1024
_MAX_FOLDER_TOTAL_BYTES = 8 * 1024 * 1024
_MAX_WALK_ENTRIES = 20_000       # mirrors github_repo.py's _MAX_TREE_ENTRIES
_LICENSE_ROOT_BASENAMES = {"license", "license.md", "license.txt"}
_GIT_TIMEOUT_SECONDS = 120


def _validate_url(url: str) -> str:
    """Confirms `url` is a well-formed URL (a scheme and a host) and
    returns it unchanged. Deliberately does NOT restrict the scheme to
    https:// here -- that policy belongs to sources_config.py's loader
    (checked once, at config-load time, against sources.yaml's own
    entries, the same real "must be https" boundary github_repo.py's
    assert_safe_https_url enforces for its own fetches) rather than this
    lower-level clone function, which a test fixture also calls directly
    with a file:// URL against a local repo it just built (git clones
    file:// natively, no network -- the only practical way to test a
    real `git clone` without a live external server)."""
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        raise ImportFetchError(f"git_repo url {url!r} is not a well-formed URL")
    return url


def derive_publisher_and_name(url: str) -> tuple[str, str]:
    """Best-effort "owner/repo"-shaped pair from an arbitrary git URL,
    for namespace derivation -- e.g. "https://gitlab.com/group/proj.git"
    -> ("group", "proj"); "https://git.example.com/team/sub/proj.git" ->
    ("team", "proj") (a nested GitLab subgroup's own middle segments are
    dropped -- disclosed simplification, same class of judgment call as
    github_repo.py's own owner/repo assumption, which has no subgroup
    concept at all). Raises ImportFetchError if the URL has fewer than 2
    path segments (nothing to derive an owner/repo pair from)."""
    parsed = urlsplit(url)
    segments = [s for s in parsed.path.strip("/").split("/") if s]
    if len(segments) < 2:
        raise ImportFetchError(f"git_repo url {url!r} needs at least two path segments (owner/repo)")
    owner = segments[0]
    repo = segments[-1]
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    return owner, repo


def _git_env(read_token_env: str | None) -> dict[str, str]:
    """Base subprocess env for every git invocation -- never inherits an
    interactive credential prompt (GIT_TERMINAL_PROMPT=0, so a bad/missing
    token fails fast with a real error instead of hanging the crawl job)."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git_auth_args(read_token_env: str | None) -> list[str]:
    """Optional per-source read token (sources.yaml's `read_token_env:
    SOME_ENV_VAR_NAME` -- the same "env var as platform secret"
    convention github_credential.py already documents for
    GITHUB_IMPORT_TOKEN, just per-source instead of one instance-wide
    token, since a generic git source can point at any host with its own
    unrelated credential). Passed as a Bearer Authorization header via
    `-c http.extraHeader`, which every modern git-over-HTTP server this
    adapter targets (GitLab, Gitea, self-hosted) accepts -- avoids
    embedding the token in the remote URL (which would leak it into
    `.git/config` and this process's own argv). Disclosed limitation: the
    token IS visible in this process's own argv (e.g. to another local
    process listing `ps`/Task Manager) for the duration of the git
    subprocess call -- acceptable for a CI runner (the crawl workflow's
    own execution environment) or a trusted admin's install-time
    materialize call, not a substitute for a real secret-injection
    mechanism if this ever runs on a genuinely multi-tenant host.
    """
    if not read_token_env:
        return []
    token = os.getenv(read_token_env)
    if not token:
        return []
    return ["-c", f"http.extraHeader=Authorization: Bearer {token}"]


def _run_git(args: list[str], *, cwd: str | None = None, read_token_env: str | None = None) -> str:
    full_args = ["git", *_git_auth_args(read_token_env), *args]
    try:
        result = subprocess.run(
            full_args, cwd=cwd, env=_git_env(read_token_env),
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ImportFetchError(f"git {' '.join(args)!r} timed out after {_GIT_TIMEOUT_SECONDS}s") from exc
    except OSError as exc:
        raise ImportFetchError(f"could not run git ({exc}) -- is git installed on this host?") from exc
    if result.returncode != 0:
        raise ImportFetchError(f"git {' '.join(args)!r} failed: {result.stderr.strip()[:500]}")
    return result.stdout.strip()


def _clone_at_ref(url: str, ref: str, dest_dir: str, *, read_token_env: str | None = None) -> str:
    """Shallow-clones `url` at `ref` into `dest_dir` and returns the
    resolved commit SHA. `ref` may be a branch/tag name (crawl time) or
    an exact pinned commit SHA (install time, re-verifying the same
    commit the crawler recorded) -- tried identically, since a direct
    shallow fetch of an arbitrary ref/SHA is exactly the same git
    operation either way on a server that allows it.

    Falls back to fetching `ref` as a named ref with a deeper (bounded)
    history if the direct shallow fetch fails -- covers the real,
    disclosed case (module docstring) where the server only allows
    fetching by name, not by arbitrary reachable SHA, and the caller
    actually wanted a *pinned* commit that may no longer be that ref's
    current tip.
    """
    _run_git(["init", "-q", dest_dir])
    # Real bug found live (2026-09-30, Windows dev host): git's own
    # core.autocrlf default can rewrite a committed file's LF line endings
    # to CRLF on checkout -- silently corrupting the YAML frontmatter
    # parser (parse_skill_md_frontmatter returns {} on a CRLF-mangled
    # SKILL.md) and, more importantly, making compute_content_hash()
    # produce a DIFFERENT hash for the exact same commit depending on
    # which OS/git-config crawled it (the production crawl workflow runs
    # on ubuntu-latest, where this wouldn't normally trigger -- but
    # nothing about this adapter's own correctness should depend on that;
    # a local install-time re-fetch on Windows must reproduce the exact
    # same bytes the crawler hashed). Forcing core.autocrlf=false makes
    # every checkout byte-identical to what's actually committed,
    # regardless of host OS -- the same guarantee GitHub's raw-content
    # host already gives github_repo.py for free (it serves committed
    # bytes untouched, no local checkout involved at all).
    _run_git(["config", "core.autocrlf", "false"], cwd=dest_dir)
    _run_git(["remote", "add", "origin", url], cwd=dest_dir)
    try:
        _run_git(["fetch", "--depth", "1", "origin", ref], cwd=dest_dir, read_token_env=read_token_env)
        _run_git(["checkout", "-q", "FETCH_HEAD"], cwd=dest_dir)
    except ImportFetchError:
        # Real, disclosed fallback (module docstring): the server rejected
        # a direct fetch of this exact ref (most often because `ref` is a
        # pinned SHA the server won't serve without the branch history
        # around it) -- unbounded-depth fetch of a REAL branch/tag name is
        # the only remaining way to reach it. Only meaningful when `ref`
        # itself isn't already a plain branch/tag (a genuinely missing/
        # renamed branch would fail here too, correctly, as ImportFetchError).
        _run_git(["fetch", "--no-tags", "origin", ref], cwd=dest_dir, read_token_env=read_token_env)
        _run_git(["checkout", "-q", "FETCH_HEAD"], cwd=dest_dir)
    return _run_git(["rev-parse", "HEAD"], cwd=dest_dir)


def _walk_files(root: str) -> tuple[set[str], dict[str, int]]:
    """Every real file under `root` (POSIX-style relative paths, `.git/`
    excluded) plus its byte size -- the local-clone equivalent of
    github_repo.py's GitHub-tree-API blob-entry listing. Symlinks are
    skipped entirely (both file and directory symlinks) -- a real guard
    the API-based adapter doesn't need (GitHub's raw-content host
    resolves a symlink server-side; a LOCAL clone's symlink could
    otherwise be walked or read straight through to a path outside
    `root`, e.g. a maliciously crafted repo committing a symlink to
    `../../etc/passwd`)."""
    paths: set[str] = set()
    sizes: dict[str, int] = {}
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git" and not os.path.islink(os.path.join(dirpath, d))]
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            if os.path.islink(full_path):
                continue
            rel_path = os.path.relpath(full_path, root).replace(os.sep, "/")
            if not is_safe_tree_path(rel_path):
                continue
            paths.add(rel_path)
            try:
                sizes[rel_path] = os.path.getsize(full_path)
            except OSError:
                sizes[rel_path] = 0
            if len(paths) > _MAX_WALK_ENTRIES:
                raise ImportFetchError(f"{root!r} has more than {_MAX_WALK_ENTRIES} files, exceeding the scan limit")
    return paths, sizes


def _read_text(root: str, rel_path: str, max_bytes: int) -> str:
    """Reads one file's text content from the local clone, capped at
    `max_bytes`. Defense-in-depth path-containment check (belt-and-
    suspenders alongside is_safe_tree_path()'s own string-level guard in
    _walk_files()): the resolved real path must still live under `root`
    after resolving any remaining `..`/symlink components, and must not
    itself be a symlink."""
    root_real = os.path.realpath(root)
    full_path = os.path.join(root, rel_path)
    if os.path.islink(full_path):
        raise ImportFetchError(f"{rel_path!r} is a symlink -- refusing to read it")
    real_path = os.path.realpath(full_path)
    if not (real_path == root_real or real_path.startswith(root_real + os.sep)):
        raise ImportFetchError(f"{rel_path!r} resolves outside the repository root -- refusing to read it")
    try:
        with open(real_path, "rb") as f:
            raw = f.read(max_bytes + 1)
    except OSError as exc:
        raise ImportFetchError(f"could not read {rel_path!r}: {exc}") from exc
    if len(raw) > max_bytes:
        raise ImportFetchError(f"{rel_path!r} exceeds the {max_bytes // 1024}KB limit")
    return raw.decode("utf-8", errors="replace")


def _text_fetcher(root: str) -> Callable[[str, int], str]:
    return lambda rel_path, max_bytes=_MAX_SKILL_MD_BYTES: _read_text(root, rel_path, max_bytes)


def _repo_root_license(root: str, all_paths: set[str]) -> str:
    """Text-guessed license of the repo-root LICENSE/LICENSE.md/LICENSE.txt
    -- the only repo-level fallback signal available with no host API
    (module docstring). Empty string (never None) when no root LICENSE
    file exists or its text doesn't clearly match a recognized family,
    matching github_repo.py's own repo_license shape (an empty-string
    "no signal", not a special sentinel). Uses find_license_file_in_folder()
    (case-insensitive basename match, folder="" == repo root) rather than
    a direct `all_paths` lookup -- a real repo's LICENSE file is
    conventionally all-caps ("LICENSE"), not the lowercase basenames this
    module's own constant spells for comparison purposes."""
    license_path = find_license_file_in_folder(all_paths, "", _LICENSE_ROOT_BASENAMES)
    if license_path:
        return guess_license_from_text(_read_text(root, license_path, _MAX_SKILL_MD_BYTES)) or ""
    return ""


class _ClonedRepo:
    """Context manager: clones `url` at `ref` into a fresh temp dir,
    yields (clone_dir, resolved_sha), always removes the temp dir on
    exit -- every public function below uses this rather than managing
    its own tempdir lifecycle, so a raised ImportFetchError mid-clone
    still cleans up."""

    def __init__(self, url: str, ref: str, *, read_token_env: str | None = None) -> None:
        self._url = _validate_url(url)
        self._ref = ref
        self._read_token_env = read_token_env
        self._tmpdir: str | None = None

    def __enter__(self) -> tuple[str, str]:
        self._tmpdir = tempfile.mkdtemp(prefix="ainxt-git-source-")
        resolved_sha = _clone_at_ref(self._url, self._ref, self._tmpdir, read_token_env=self._read_token_env)
        return self._tmpdir, resolved_sha

    def __exit__(self, *exc_info: object) -> None:
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)


def discover_skills_in_git_repo(
    url: str, ref: str = "HEAD", path: str | None = None, *, read_token_env: str | None = None,
) -> list[dict[str, Any]]:
    """Finds every SKILL.md in `url`@`ref` (optionally scoped to a
    subdirectory `path`) and returns one candidate dict per skill, in the
    exact same shape as github_repo.py's discover_skills_in_repo() --
    "path", "skill_md_path", "display_name", "description",
    "license_evidence", "resolved_sha", "allowed", "reason" -- so
    crawl.py's own per-candidate handling (exclude/include, license
    evidence recording) works identically for either source kind.

    Raises ImportFetchError for a malformed `path`, an unreachable/
    unresolvable ref, or a repo with more files than this adapter will
    scan -- never a LicenseNotAllowedError, matching github_repo.py's own
    contract (a per-candidate license failure is reported IN the list).
    """
    scoped_path = assert_safe_relative_path(path)

    with _ClonedRepo(url, ref, read_token_env=read_token_env) as (root, resolved_sha):
        all_paths, entry_sizes = _walk_files(root)
        repo_license = _repo_root_license(root, all_paths)

        if scoped_path is not None:
            prefix = scoped_path + "/"
            candidate_paths = {p for p in all_paths if p == scoped_path or p.startswith(prefix)}
        else:
            candidate_paths = all_paths

        skill_md_paths = sorted(p for p in candidate_paths if p == "SKILL.md" or p.endswith("/SKILL.md"))
        if len(skill_md_paths) > _MAX_DISCOVERED_SKILLS:
            raise ImportFetchError(
                f"{url!r} contains {len(skill_md_paths)} SKILL.md files, exceeding the "
                f"{_MAX_DISCOVERED_SKILLS} discovery limit -- narrow with `path`"
            )

        from services.ecosystem._agentstudio_interop import parse_skill_md_frontmatter

        fetch_text = _text_fetcher(root)
        candidates: list[dict[str, Any]] = []
        for skill_md_path in skill_md_paths:
            folder = skill_md_path.rsplit("/", 1)[0] if "/" in skill_md_path else ""
            skill_md_text = _read_text(root, skill_md_path, _MAX_SKILL_MD_BYTES)
            frontmatter = parse_skill_md_frontmatter(skill_md_text)
            skill_license_field = frontmatter.get("license", "")

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

            fallback_name = folder.rsplit("/", 1)[-1] if folder else derive_publisher_and_name(url)[1]
            candidates.append({
                "path": folder,
                "skill_md_path": skill_md_path,
                "display_name": clean_display_name(frontmatter.get("name", ""), fallback_name),
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


def import_from_git_path(url: str, path: str, ref: str = "HEAD", *, read_token_env: str | None = None) -> dict[str, Any]:
    """Imports one skill from a specific subdirectory of `url`@`ref` (as
    identified by a prior discover_skills_in_git_repo() call, or the
    exact pinned commit SHA recorded by a prior crawl), bundling every
    other file in that same folder into `files` alongside SKILL.md.

    Same return shape as github_repo.py's import_from_github_path():
    {"manifest", "files", "license", "display_name", "description",
    "resolved_sha", "source_url"}. Raises ImportFetchError for a
    malformed/missing path or oversized folder, LicenseNotAllowedError if
    the effective license or a conflicting bundled file isn't MIT/Apache-2.0.
    """
    scoped_path = assert_safe_relative_path(path)
    if not scoped_path:
        raise ImportFetchError("import_from_git_path requires a non-empty folder path")

    with _ClonedRepo(url, ref, read_token_env=read_token_env) as (root, resolved_sha):
        all_paths, _entry_sizes = _walk_files(root)
        repo_license = _repo_root_license(root, all_paths)

        prefix = scoped_path + "/"
        folder_paths = {p for p in all_paths if p == scoped_path or p.startswith(prefix)}

        skill_md_path = f"{scoped_path}/SKILL.md"
        if skill_md_path not in folder_paths:
            raise ImportFetchError(f"{url!r}@{resolved_sha[:12]} has no SKILL.md at {scoped_path!r}")

        skill_md_text = _read_text(root, skill_md_path, _MAX_SKILL_MD_BYTES)

        from services.ecosystem._agentstudio_interop import parse_skill_md_frontmatter

        frontmatter = parse_skill_md_frontmatter(skill_md_text)
        file_license = frontmatter.get("license", "")

        fetch_text = _text_fetcher(root)
        effective_license, license_source = resolve_effective_license(
            fetch_text, scoped_path, all_paths, repo_license, file_license,
        )
        if not is_allowed_license(effective_license):
            raise LicenseNotAllowedError(
                f"{url!r}'s folder {scoped_path!r} effective license ({effective_license!r}, via {license_source}) "
                "is not MIT/Apache-2.0",
                stage="import_precheck", declared_license=effective_license or None,
            )

        conflict = scan_folder_for_conflicting_license_evidence(
            fetch_text, scoped_path, all_paths, _entry_sizes, skip_paths={skill_md_path},
        )
        if conflict:
            raise LicenseNotAllowedError(
                f"{url!r}'s folder {scoped_path!r}: {conflict[0]!r} declares {conflict[1]!r}, conflicting with "
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
            text = _read_text(root, entry_path, _MAX_BUNDLE_FILE_BYTES)
            total_bytes += len(text.encode("utf-8"))
            if total_bytes > _MAX_FOLDER_TOTAL_BYTES:
                raise ImportFetchError(
                    f"{url!r}'s folder {scoped_path!r} exceeds the "
                    f"{_MAX_FOLDER_TOTAL_BYTES // (1024 * 1024)}MB total bundle-file limit"
                )
            files[rel_path] = text

        return {
            "manifest": manifest,
            "files": files,
            "license": effective_license,
            "display_name": display_name,
            "description": description,
            "resolved_sha": resolved_sha,
            "source_url": f"{url.rstrip('/')}/-/tree/{resolved_sha}/{scoped_path}",
        }


def import_from_git(url: str, ref: str = "HEAD", *, read_token_env: str | None = None) -> dict[str, Any]:
    """Root-of-repo import (no subdirectory) -- mirrors github_repo.py's
    import_from_github() for a repo whose lone SKILL.md lives at the
    repo root. Same return shape."""
    with _ClonedRepo(url, ref, read_token_env=read_token_env) as (root, resolved_sha):
        all_paths, _entry_sizes = _walk_files(root)
        repo_license = _repo_root_license(root, all_paths)

        if "SKILL.md" not in all_paths:
            raise ImportFetchError(f"{url!r}@{resolved_sha[:12]} has no SKILL.md at the repo root")

        skill_md_text = _read_text(root, "SKILL.md", _MAX_SKILL_MD_BYTES)

        from services.ecosystem._agentstudio_interop import parse_skill_md_frontmatter

        frontmatter = parse_skill_md_frontmatter(skill_md_text)
        file_license = frontmatter.get("license", "")

        fetch_text = _text_fetcher(root)
        effective_license, license_source = resolve_effective_license(
            fetch_text, "", all_paths, repo_license, file_license,
        )
        if not is_allowed_license(effective_license):
            raise LicenseNotAllowedError(
                f"{url!r} effective license ({effective_license!r}, via {license_source}) is not MIT/Apache-2.0",
                stage="import_precheck", declared_license=effective_license or None,
            )

        _, repo_name = derive_publisher_and_name(url)
        display_name = clean_display_name(frontmatter.get("name", ""), repo_name)
        description = frontmatter.get("description", "")
        manifest = {"name": display_name, "description": description, "instructions": skill_md_text}

        return {
            "manifest": manifest,
            "files": {},
            "license": effective_license,
            "display_name": display_name,
            "description": description,
            "resolved_sha": resolved_sha,
            "source_url": url,
        }


def get_resolved_head_sha(url: str, ref: str = "HEAD", *, read_token_env: str | None = None) -> str:
    """Resolves `url`@`ref` to an exact commit SHA using `git ls-remote`
    -- no clone at all, mirroring github_repo.py's own
    get_resolved_head_sha() (repo meta + commit lookup, no tree listing)
    for the same purpose: letting the crawler check "has this source
    moved since the last crawl" before doing any of the expensive
    discovery/import work. Raises ImportFetchError if `ref` doesn't
    resolve to exactly one commit (missing ref, or an ambiguous one)."""
    _validate_url(url)
    output = _run_git(["ls-remote", url, ref], read_token_env=read_token_env)
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        raise ImportFetchError(f"{url!r}: ref {ref!r} not found (ls-remote returned nothing)")
    resolved_sha = lines[0].split("\t", 1)[0].strip()
    if len(resolved_sha) != 40:
        raise ImportFetchError(f"{url!r}: ls-remote for {ref!r} did not return a full commit sha ({resolved_sha!r})")
    return resolved_sha
