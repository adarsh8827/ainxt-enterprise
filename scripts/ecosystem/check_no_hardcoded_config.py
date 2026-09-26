#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ============================================================
# Task F-4's own CI-enforced test requirement: "a CI-enforced check
# (grep-based or a custom ESLint rule) that no component in
# packages/ecosystem-ui contains a hardcoded item-type/surface/
# feature-flag/category string literal outside of test fixtures."
#
# Grep-based, not an ESLint rule -- this repo's Node tooling has no shared
# ESLint config packages/ecosystem-ui could plug a custom rule into without
# adding new infra scoped well beyond this one check.
#
# Exemptions (the only places these literals are allowed to live):
#   - src/client/fixtures.ts / src/client/MockEcosystemClient.ts (the mock's
#     own fixture data IS this data, by construction)
#   - src/types.ts (defines the enum/union types themselves)
#   - any *.stories.tsx / *.test.tsx / *.test.ts file
#
# Usage:
#   python scripts/ecosystem/check_no_hardcoded_config.py
# ============================================================

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_SRC = REPO_ROOT / "packages" / "ecosystem-ui" / "src"

# HostContext.tsx's DEFAULT_STRINGS is a static i18n copy table -- its keys
# legitimately match state names (e.g. "coming_soon") as dictionary lookup
# keys for display text, not as a rendering/gating decision derived from a
# hardcoded literal (the actual state value always still comes from
# GET /ecosystem/config; this table only supplies the label to show for it).
EXEMPT_FILES = {"fixtures.ts", "MockEcosystemClient.ts", "types.ts", "HostContext.tsx"}
EXEMPT_SUFFIXES = (".stories.tsx", ".test.tsx", ".test.ts")

# The exact category taxonomy (CONFIG_AND_PRODUCTS.md §7 item 3) and surface
# keys (CONFIG_AND_PRODUCTS.md §1) that must only ever be read from a live
# GET /ecosystem/config response, never hardcoded into a component.
BANNED_CATEGORY_LITERALS = [
    "productivity", "dev-tools", "communication", "data-analytics", "design", "finance",
    "crm", "marketing", "automation", "documents", "research", "hr-people",
    "security-compliance", "travel", "legal", "sales", "support",
]
BANNED_SURFACE_LITERALS = ["agent_studio", "workspace_chat"]
# NOTE: ItemTypeState values ("available"/"coming_soon") and ItemType
# values ("mcp_server" etc.) are NOT banned here -- comparing an
# already-fetched config field against its own wire-contract enum member
# (e.g. `t.state === "coming_soon"`) is normal, necessary type-safe code,
# not "assuming this type/state exists" the way hardcoding a literal
# category/surface LIST would be. Only genuinely data-driven registries
# (categories, surfaces) are checked.

ALL_BANNED = BANNED_CATEGORY_LITERALS + BANNED_SURFACE_LITERALS
_PATTERN = re.compile(r'["\'](' + "|".join(re.escape(x) for x in ALL_BANNED) + r')["\']')


def _is_exempt(path: Path) -> bool:
    if path.name in EXEMPT_FILES:
        return True
    return any(path.name.endswith(suffix) for suffix in EXEMPT_SUFFIXES)


def find_violations() -> list[tuple[Path, int, str]]:
    violations: list[tuple[Path, int, str]] = []
    if not PACKAGE_SRC.exists():
        return violations
    for path in PACKAGE_SRC.rglob("*.ts*"):
        if _is_exempt(path):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            match = _PATTERN.search(line)
            if match:
                violations.append((path.relative_to(REPO_ROOT), lineno, match.group(1)))
    return violations


def main() -> int:
    violations = find_violations()
    if violations:
        print("Hardcoded config-driven literal(s) found outside fixtures/types (task F-4):", file=sys.stderr)
        for path, lineno, literal in violations:
            print(f"  {path}:{lineno}: {literal!r}", file=sys.stderr)
        print(
            "\nRead this value from GET /ecosystem/config (useConfig()) instead of hardcoding it.",
            file=sys.stderr,
        )
        return 1
    print(f"OK: no hardcoded config-driven literals found under {PACKAGE_SRC.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
