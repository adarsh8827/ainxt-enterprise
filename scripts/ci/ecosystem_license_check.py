#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Ecosystem marketplace license-check CI job.

Fails the build if any file importing a banned-license dependency
(currently: lucide-react, ISC) is not present in the repo-root
`.ecosystem-license-allowlist.json`. The allowlist exists only to cover
code that predates the ban (see that file's own "description" field) — it
must shrink over time, never grow. Any file under `packages/ecosystem-ui`
is never exempt, regardless of what the allowlist contains, since that
package is new code held to the license rule with no exceptions from day
one (see docs/ecosystem/SKILLS_PHASE_PLAN.md task B-21).

Usage:
    python scripts/ci/ecosystem_license_check.py
    python scripts/ci/ecosystem_license_check.py --list   # print what would be scanned

Local-run parity: this is the same script CI runs, so `python
scripts/ci/ecosystem_license_check.py` reproduces the CI result exactly.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_PATH = REPO_ROOT / ".ecosystem-license-allowlist.json"

# Package -> (import-pattern, human-readable reason). Extend this dict as
# more banned licenses are identified; each gets its own allowlist section.
BANNED_PACKAGES = {
    "lucide-react": re.compile(r"""from\s+['"]lucide-react['"]"""),
}

SCAN_ROOTS = ["ai-ui/src", "packages/ecosystem-ui"]
SCAN_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx")

# No file under this prefix is ever exempt, regardless of the allowlist's
# contents — it is new code and is held to the license rule unconditionally.
NEVER_EXEMPT_PREFIX = "packages/ecosystem-ui/"


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


def find_violations(repo_root: Path = REPO_ROOT) -> list[tuple[str, str]]:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="print scanned files and exit")
    args = parser.parse_args()

    if args.list:
        for f in _scan():
            print(f.relative_to(REPO_ROOT).as_posix())
        return 0

    violations = find_violations()
    if violations:
        print("Ecosystem license check FAILED — banned-license import(s) outside the allowlist:", file=sys.stderr)
        for rel, package in violations:
            print(f"  {rel}  (imports {package!r})", file=sys.stderr)
        print(
            "\nNew code must not import a non-MIT/Apache-2.0-compatible dependency. "
            "If this file predates the ban and is not yet migrated, it does not belong "
            "under packages/ecosystem-ui/ — add it to .ecosystem-license-allowlist.json "
            "only if it is pre-existing code elsewhere in the tree.",
            file=sys.stderr,
        )
        return 1

    print(f"Ecosystem license check passed — {len(_scan())} files scanned, 0 violations outside the allowlist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
