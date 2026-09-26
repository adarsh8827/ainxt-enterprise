# SPDX-License-Identifier: MIT
# ============================================================
# Drafts service skeleton (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-3).
# Filled in by task B-14 (Create-with-AI drafts, M5) — backed by the
# existing AgentStudio Skill Factory pipeline, per
# docs/ecosystem/CONFIG_AND_PRODUCTS.md §7 item 4.
# See docs/ecosystem/design/LLD/create-with-ai.md.
# ============================================================

from __future__ import annotations

from typing import Any


def create_draft(**payload: Any) -> dict[str, Any]:
    raise NotImplementedError("drafts_service.create_draft lands in task B-14 (M5)")


def submit_draft(draft_id: str) -> dict[str, Any]:
    raise NotImplementedError("drafts_service.submit_draft lands in task B-14 (M5)")
