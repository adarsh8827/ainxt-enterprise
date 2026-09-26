# SPDX-License-Identifier: MIT
# ============================================================
# Resolver service skeleton (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-3).
# get_effective_capabilities() is filled in by task B-11 (M3) — merges
# task B-4's legacy bridge with native ecosystem_installs rows, filtered by
# enabled=true, surface membership, and item_types[].state == "available".
# See docs/ecosystem/design/LLD/resolver.md.
# ============================================================

from __future__ import annotations

from typing import Any


def get_effective_capabilities(org_id: str, user_id: str, surface: str) -> list[dict[str, Any]]:
    raise NotImplementedError("resolver_service.get_effective_capabilities lands in task B-11 (M3)")
