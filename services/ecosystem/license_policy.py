# SPDX-License-Identifier: MIT
# ============================================================
# Shared license-policy check (docs/ecosystem/ECOSYSTEM_PLAN.md §11.1,
# docs/ecosystem/CONTRACTS.md §18) — the one place "is this license
# allowed" is decided, reused by the import pre-check (task B-6), gate
# stage 2 (task B-8), and CI (task B-21's ecosystem_license_check.py keeps
# its own copy for dependency graphs, since it can't import this package
# from a CI-only script context, but the *rule* is identical).
#
# Allowed: MIT, Apache-2.0, or a dual/multi-license string where at least
# one option is MIT or Apache-2.0. Everything else is blocked. No override.
# ============================================================

from __future__ import annotations


def is_allowed_license(license_str: str | None) -> bool:
    """True if license_str is MIT/Apache-2.0, or a dual/multi-license
    declaration including one of those as an option. A missing/empty
    declaration is NOT allowed — it must be explicit."""
    if not license_str:
        return False
    normalized = license_str.lower()
    return "mit" in normalized or "apache" in normalized
