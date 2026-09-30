# SPDX-License-Identifier: MIT
# ============================================================
# Source-agnostic SKILL.md discovery/license-resolution helpers, shared
# between every "walk a tree of files, find SKILL.md, resolve its
# effective license" adapter (github_repo.py, and the generic git_repo.py
# added for the Connectors+Plugins phase's "any HTTPS git host" source).
#
# Extracted verbatim from github_repo.py (task: generic git source
# adapter, 2026-09-30) -- behavior is byte-for-byte unchanged for GitHub;
# see that module's git history for the original inline versions and
# their own dated bug-fix comments. Nothing here is GitHub-specific: the
# two functions that need to read a file's content (resolve_effective_license/
# scan_folder_for_conflicting_license_evidence) take a `fetch_text`
# callback instead of GitHub API coordinates, so any adapter that can
# produce (a) a set of repo-relative file paths, (b) a path -> size map,
# and (c) a way to read one file's text can reuse this exactly -- no
# duplicated license-inheritance/conflict-detection logic per source kind.
# ============================================================

from __future__ import annotations

import re
from typing import Callable

# A SKILL.md's frontmatter "name" is normally already a fine, human-
# readable display name as-is -- this rejects only a "::" namespacing
# separator (a source repo's own internal organization convention, never
# a real display name), not the field in general. See github_repo.py's
# original comment (real bug found live: google-labs-code/stitch-skills'
# own react-native/SKILL.md declares `name: stitch::react-native`).
_DISPLAY_NAME_NAMESPACE_SEPARATOR_RE = re.compile(r"::")

_LICENSE_BASENAMES = {"license", "license.md", "license.txt"}
# NOTICE/COPYING participate only in conflict detection (a real, concretely
# detected OTHER license in one of these blocks a skill even when the
# inheritance chain below would otherwise allow it) -- never in the
# inheritance chain itself, since a bare NOTICE file is typically pure
# attribution text guess_license_from_text() can't classify at all, and an
# unclassifiable file must never itself count as "not MIT/Apache" (that
# would spuriously block real MIT/Apache skills that simply carry one).
_OTHER_LICENSE_BASENAMES = {"copying", "copying.md", "copying.txt", "notice", "notice.md", "notice.txt"}
# Real, unambiguous machine-readable signal -- a bundled file's own
# SPDX-License-Identifier header comment.
_SPDX_HEADER_RE = re.compile(r"SPDX-License-Identifier:\s*([A-Za-z0-9.\-+]+(?:\s+(?:OR|AND)\s+[A-Za-z0-9.\-+]+)*)")
_MAX_CONFLICT_SCAN_FILES = 8
_MAX_CONFLICT_SCAN_FILE_BYTES = 8 * 1024

# FetchText: (path, max_bytes) -> text. Each adapter supplies its own
# closure (github_repo.py's wraps raw.githubusercontent.com + its ETag
# cache; git_repo.py's reads straight off the local shallow clone).
FetchText = Callable[[str, int], str]


def clean_display_name(frontmatter_name: str, fallback: str) -> str:
    """Returns `frontmatter_name` unless it's empty or carries a "::"
    namespacing separator, in which case the folder/repo-derived
    `fallback` (already clean -- it's just a path segment) is used
    instead."""
    candidate = (frontmatter_name or "").strip()
    if candidate and not _DISPLAY_NAME_NAMESPACE_SEPARATOR_RE.search(candidate):
        return candidate
    return fallback


def assert_safe_relative_path(path: str | None) -> str | None:
    """Normalizes an optional caller-supplied subdirectory scope and
    rejects path-traversal attempts. Returns None for "no scope" (whole
    repo), or the cleaned relative path (no leading/trailing slash) --
    never raises for a merely-empty path, only for one that tries to
    escape the repo root."""
    from services.ecosystem.errors import ImportFetchError

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


def is_safe_tree_path(entry_path: str) -> bool:
    """Defense-in-depth guard on every path a source's own tree/file
    listing returns -- treated as untrusted input regardless of how
    unlikely a real traversal-shaped entry from the source itself would be."""
    if not entry_path or entry_path.startswith("/") or "\\" in entry_path:
        return False
    return ".." not in entry_path.split("/")


def find_license_file_in_folder(paths: set[str], folder: str, basenames: set[str]) -> str | None:
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


def ancestor_folders(folder: str) -> list[str]:
    """`folder`'s own path, then each enclosing directory, nearest first,
    stopping BEFORE the repo root (`""`) -- the root's license is handled
    separately (a repo-level fallback, not a text guess against an
    ancestor folder), so it is deliberately excluded from this list."""
    if not folder:
        return []
    parts = folder.split("/")
    return ["/".join(parts[:i]) for i in range(len(parts), 0, -1)]


def find_nearest_license_file(paths: set[str], folder: str) -> str | None:
    """The nearest LICENSE/LICENSE.md/LICENSE.txt to `folder`, checking the
    skill's own folder first and then each enclosing directory in turn
    (nearest wins) -- never the repo root itself (that's a separate,
    caller-provided repo-level fallback)."""
    for candidate_folder in ancestor_folders(folder):
        found = find_license_file_in_folder(paths, candidate_folder, _LICENSE_BASENAMES)
        if found:
            return found
    return None


def guess_license_from_text(text: str) -> str | None:
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


def resolve_effective_license(
    fetch_text: FetchText, folder: str, all_paths: set[str],
    repo_license: str, skill_license_field: str,
) -> tuple[str | None, str]:
    """Inheritance order (first found wins, per explicit review): the
    skill's own SKILL.md `license:` field -> the nearest LICENSE file in
    its own folder or an enclosing folder -> the repo-root license.

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

    license_file_path = find_nearest_license_file(all_paths, folder)
    if license_file_path:
        license_text = fetch_text(license_file_path, _MAX_CONFLICT_SCAN_FILE_BYTES * 32)
        guessed = guess_license_from_text(license_text)
        return guessed, f"LICENSE file at {license_file_path!r}"

    return (repo_license or None), "repo LICENSE (fallback)"


def scan_folder_for_conflicting_license_evidence(
    fetch_text: FetchText, folder: str, all_paths: set[str],
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
         file.
      2. Any other smallish file directly under the folder carrying its
         own `SPDX-License-Identifier:` header naming a non-MIT/Apache id
         -- an explicit, machine-readable per-file declaration always
         wins over inherited evidence, matching real-world monorepo
         practice.
    Capped (_MAX_CONFLICT_SCAN_FILES / _MAX_CONFLICT_SCAN_FILE_BYTES) to
    bound the extra fetches this costs -- a folder with more candidate
    files than the cap allows is scanned partially rather than
    exhaustively; this is a best-effort extra safety net, not the primary
    license gate.

    Returns (conflicting_file_path, conflicting_spdx_or_family) or None.
    """
    from services.ecosystem.license_policy import is_allowed_license

    checked_license_paths: set[str] = set()
    for basenames in (_LICENSE_BASENAMES, _OTHER_LICENSE_BASENAMES):
        own_license_path = find_license_file_in_folder(all_paths, folder, basenames)
        if own_license_path:
            checked_license_paths.add(own_license_path)
            text = fetch_text(own_license_path, _MAX_CONFLICT_SCAN_FILE_BYTES)
            guessed = guess_license_from_text(text)
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
        text = fetch_text(candidate_path, _MAX_CONFLICT_SCAN_FILE_BYTES)
        match = _SPDX_HEADER_RE.search(text)
        if match and not is_allowed_license(match.group(1)):
            return candidate_path, match.group(1)

    return None
