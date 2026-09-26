#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# ============================================================
# Task F-10: negative-verification against F-2 through F-9's output.
# Confirms no ThirdPartyCheckModal-shaped component, and no "Skills
# created by you / Skills from third parties" two-section layout, exists
# anywhere in packages/ecosystem-ui -- both were the merged frontend's old
# pattern (ai-ui/src/components/Marketplace.jsx, superseded by the real
# trust-tier badge system and Verification tab, task F-5/F-7).
# ============================================================

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_SRC = REPO_ROOT / "packages" / "ecosystem-ui" / "src"

BANNED_PATTERNS = [
    re.compile(r"ThirdPartyCheckModal", re.IGNORECASE),
    re.compile(r"third[- ]part(y|ies)", re.IGNORECASE),
    re.compile(r"created\s+by\s+you.{0,40}third", re.IGNORECASE | re.DOTALL),
]


def main() -> int:
    if not PACKAGE_SRC.exists():
        print(f"SKIP: {PACKAGE_SRC} does not exist yet")
        return 0

    violations: list[tuple[Path, int, str]] = []
    for path in PACKAGE_SRC.rglob("*.ts*"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern in BANNED_PATTERNS:
                if pattern.search(line):
                    violations.append((path.relative_to(REPO_ROOT), lineno, pattern.pattern))

    if violations:
        print("Task F-10 violation: ThirdPartyCheckModal / first-third-party split found:", file=sys.stderr)
        for path, lineno, pattern in violations:
            print(f"  {path}:{lineno}: matched {pattern!r}", file=sys.stderr)
        return 1

    print(f"OK: no ThirdPartyCheckModal / first-third-party split found under {PACKAGE_SRC.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
