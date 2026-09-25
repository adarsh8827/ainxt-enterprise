#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Ecosystem marketplace license-check CI job.

Two independent checks, both must pass:

1. Import-level check: fails if any file importing a banned-license
   dependency (currently: lucide-react, ISC) is not present in the
   repo-root `.ecosystem-license-allowlist.json`. The allowlist exists only
   to cover code that predates the ban — it must shrink over time, never
   grow. Any file under `packages/ecosystem-ui` is never exempt, regardless
   of what the allowlist contains, since that package is new code held to
   the license rule with no exceptions from day one.

2. Dependency-manifest check: fails if a dependency newly added to a
   Python (`requirements*.txt`) or npm (`package.json`) manifest, relative
   to a base git ref, is not recorded in this repo's compliance inventory
   (`compliance/python-components.tsv` / `compliance/node-components.tsv`)
   under an MIT/Apache-2.0-compatible license. A dependency missing from
   the inventory entirely fails closed (needs a verified entry, not a
   silent pass) — this catches the case the import-level check cannot:
   a new dependency added to a manifest but not yet imported anywhere.

See docs/ecosystem/SKILLS_PHASE_PLAN.md task B-21.

Usage:
    python scripts/ci/ecosystem_license_check.py
    python scripts/ci/ecosystem_license_check.py --list   # print what would be scanned
    python scripts/ci/ecosystem_license_check.py --base-ref origin/main

Local-run parity: this is the same script CI runs, so `python
scripts/ci/ecosystem_license_check.py` reproduces the CI result exactly
(given the same base ref — CI's default, origin/main, requires that ref
to exist locally too; override with --base-ref or
ECOSYSTEM_LICENSE_CHECK_BASE_REF if it doesn't).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_PATH = REPO_ROOT / ".ecosystem-license-allowlist.json"

# ── Check 1: banned-license imports ─────────────────────────────────────────

# Package -> import-pattern. Extend this dict as more banned licenses are
# identified; each gets its own allowlist section (keyed by package name).
BANNED_PACKAGES = {
    "lucide-react": re.compile(r"""from\s+['"]lucide-react['"]"""),
}

SCAN_ROOTS = ["ai-ui/src", "packages/ecosystem-ui"]
SCAN_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx")

# No file under this prefix is ever exempt, regardless of the allowlist's
# contents — it is new code and is held to the license rule unconditionally.
NEVER_EXEMPT_PREFIX = "packages/ecosystem-ui/"

# ── Check 2: newly added dependencies ────────────────────────────────────────

PYTHON_MANIFESTS = ["requirements.txt", "requirements-ldap.txt", "requirements-ocr.txt"]
NPM_MANIFESTS = ["ai-ui/package.json", "desktop/package.json", "AgentStudio/frontend/package.json"]

PYTHON_COMPLIANCE_TSV = "compliance/python-components.tsv"
NPM_COMPLIANCE_TSV = "compliance/node-components.tsv"

DEFAULT_BASE_REF = os.environ.get("ECOSYSTEM_LICENSE_CHECK_BASE_REF", "origin/main")

_REQ_LINE_RE = re.compile(r"""^\s*([A-Za-z0-9_.\-]+)\s*(?:[=<>!~]=?.*)?$""")


def _git_show(ref: str, rel_path: str, repo_root: Path) -> str | None:
    """Return the file's content at `ref`, or None if it doesn't exist there
    (a brand-new manifest, or a ref this checkout doesn't have).

    Decodes as UTF-8 explicitly rather than relying on subprocess's default
    locale encoding: on Windows that default is cp1252, which raises on the
    non-ASCII bytes these manifests' comments contain and previously made
    every dependency look "newly added" (the old-side read came back empty).
    """
    try:
        result = subprocess.run(
            ["git", "show", f"{ref}:{rel_path}"],
            cwd=repo_root, capture_output=True, check=False,
        )
    except FileNotFoundError:
        return None
    return result.stdout.decode("utf-8") if result.returncode == 0 else None


def _parse_requirements(text: str) -> dict[str, str]:
    deps: dict[str, str] = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "--")):
            continue
        m = _REQ_LINE_RE.match(line)
        if m:
            deps[m.group(1).lower()] = line
    return deps


def _parse_package_json(text: str) -> dict[str, str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    deps: dict[str, str] = {}
    for section in ("dependencies", "devDependencies"):
        deps.update(data.get(section, {}) or {})
    return deps


def _load_compliance_tsv(repo_root: Path, rel_path: str) -> dict[str, str]:
    """name -> license, last-listed version wins if a name appears more than
    once (e.g. different versions across sub-dependencies)."""
    path = repo_root / rel_path
    if not path.exists():
        return {}
    licenses: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines[1:]:  # skip header
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        name, _version, license_str = parts[0], parts[1], parts[2]
        # node-components.tsv nests transitive deps as "pkg/node_modules/sub" —
        # only the top-level name matters for a manifest-level diff.
        top_level_name = name.split("/node_modules/")[0]
        licenses[top_level_name.lower()] = license_str
    return licenses


def _is_allowed_new_dependency_license(license_str: str) -> bool:
    """Stricter than the whole-repo rule (which tolerates BSD/ISC/MPL for
    already-reviewed pre-existing deps): a *new* dependency must be MIT or
    Apache-2.0, or a dual/multi-license string that includes one of those
    as an option. This is a heuristic substring match, not a legal
    determination — THIRD-PARTY-NOTICES.md's own human review is still the
    final word for anything this flags as borderline."""
    s = license_str.lower()
    return "mit" in s or "apache" in s


def find_import_violations(repo_root: Path = REPO_ROOT) -> list[tuple[str, str]]:
    """Return (relative_path, package) for every banned-license import found
    outside the allowlist (or anywhere under NEVER_EXEMPT_PREFIX)."""
    allowlists = _load_allowlist(repo_root)
    violations: list[tuple[str, str]] = []

    for path in _scan(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for package, pattern in BANNED_PACKAGES.items():
            if not pattern.search(text):
                continue
            allowed = allowlists.get(package, set())
            if rel.startswith(NEVER_EXEMPT_PREFIX) or rel not in allowed:
                violations.append((rel, package))
    return violations


# Backward-compatible alias (existing tests/callers use this name for the
# import-level check specifically).
find_violations = find_import_violations


def find_dependency_violations(
    repo_root: Path = REPO_ROOT, base_ref: str = DEFAULT_BASE_REF
) -> list[tuple[str, str, str]]:
    """Return (manifest_path, dependency_name, reason) for every dependency
    newly added to a manifest (relative to base_ref) whose license is either
    missing from the compliance inventory or not MIT/Apache-2.0-compatible."""
    violations: list[tuple[str, str, str]] = []

    manifests: list[tuple[str, str, callable, dict[str, str]]] = [
        (m, "python", _parse_requirements, _load_compliance_tsv(repo_root, PYTHON_COMPLIANCE_TSV))
        for m in PYTHON_MANIFESTS
    ] + [
        (m, "npm", _parse_package_json, _load_compliance_tsv(repo_root, NPM_COMPLIANCE_TSV))
        for m in NPM_MANIFESTS
    ]

    for rel_path, _kind, parser, licenses in manifests:
        current_path = repo_root / rel_path
        if not current_path.exists():
            continue
        new_text = current_path.read_text(encoding="utf-8")
        old_text = _git_show(base_ref, rel_path, repo_root) or ""

        new_deps = parser(new_text)
        old_deps = parser(old_text)
        added_names = set(new_deps) - set(old_deps)

        for name in sorted(added_names):
            license_str = licenses.get(name.lower())
            if license_str is None:
                violations.append((
                    rel_path, name,
                    "no compliance record found (add a verified entry to the compliance "
                    "TSV and THIRD-PARTY-NOTICES.md before this can be checked)",
                ))
            elif not _is_allowed_new_dependency_license(license_str):
                violations.append((
                    rel_path, name,
                    f"license {license_str!r} is not MIT/Apache-2.0-compatible for a new dependency",
                ))
    return violations


def _load_allowlist(repo_root: Path = REPO_ROOT) -> dict[str, set[str]]:
    allowlist_path = repo_root / ".ecosystem-license-allowlist.json"
    if not allowlist_path.exists():
        return {}
    data = json.loads(allowlist_path.read_text(encoding="utf-8"))
    package = data.get("package", "")
    files = set(data.get("files", []))
    return {package: files} if package else {}


def _scan(repo_root: Path = REPO_ROOT) -> list[Path]:
    found = []
    for root in SCAN_ROOTS:
        base = repo_root / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in SCAN_EXTENSIONS:
                found.append(path)
    return sorted(found)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="print scanned files and exit")
    parser.add_argument("--base-ref", default=DEFAULT_BASE_REF, help="git ref to diff manifests against (default: origin/main, or $ECOSYSTEM_LICENSE_CHECK_BASE_REF)")
    parser.add_argument("--skip-dependency-check", action="store_true", help="skip check 2 (useful when base-ref isn't fetched locally)")
    args = parser.parse_args()

    if args.list:
        for f in _scan():
            print(f.relative_to(REPO_ROOT).as_posix())
        return 0

    exit_code = 0

    import_violations = find_import_violations()
    if import_violations:
        exit_code = 1
        print("Ecosystem license check FAILED — banned-license import(s) outside the allowlist:", file=sys.stderr)
        for rel, package in import_violations:
            print(f"  {rel}  (imports {package!r})", file=sys.stderr)
        print(
            "\nNew code must not import a non-MIT/Apache-2.0-compatible dependency. "
            "If this file predates the ban and is not yet migrated, it does not belong "
            "under packages/ecosystem-ui/ — add it to .ecosystem-license-allowlist.json "
            "only if it is pre-existing code elsewhere in the tree.",
            file=sys.stderr,
        )

    if not args.skip_dependency_check:
        dep_violations = find_dependency_violations(base_ref=args.base_ref)
        if dep_violations:
            exit_code = 1
            print("\nEcosystem license check FAILED — newly added dependencies with an unverified/disallowed license:", file=sys.stderr)
            for manifest, name, reason in dep_violations:
                print(f"  {manifest}: {name} — {reason}", file=sys.stderr)

    if exit_code == 0:
        print(f"Ecosystem license check passed — {len(_scan())} files scanned for banned imports, dependency manifests checked against {args.base_ref}.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
