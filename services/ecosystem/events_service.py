# SPDX-License-Identifier: MIT
# ============================================================
# Events service skeleton (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-3).
# publish_ecosystem_changed() is filled in by task B-13 (M3) — the
# ecosystem.changed Redis pub/sub publisher (docs/ecosystem/CONTRACTS.md
# §13), reusing the Redis-pub/sub-to-WebSocket relay pattern already used by
# routers/cowork_mcp_router.py / routers/cowork_dispatch_router.py.
# See docs/ecosystem/design/LLD/events.md.
# ============================================================

from __future__ import annotations

from typing import Any


def publish_ecosystem_changed(org_id: str, event: dict[str, Any]) -> None:
    raise NotImplementedError("events_service.publish_ecosystem_changed lands in task B-13 (M3)")
