# SPDX-License-Identifier: MIT
# ============================================================
# Icon service skeleton (docs/ecosystem/SKILLS_PHASE_PLAN.md task B-3).
# Filled in by task B-7 (icon upload + SVG sanitization, M2) — backs
# POST /ecosystem/uploads/icon (docs/ecosystem/CONTRACTS.md §10).
# See docs/ecosystem/design/LLD/ui-package.md.
# ============================================================

from __future__ import annotations


def upload_icon(content: bytes, content_type: str) -> str:
    """Sanitize (if SVG) and store an icon; return its icon_url ('url:...'
    or 'emoji:...' form, per CONTRACTS.md §7 item 9)."""
    raise NotImplementedError("icon_service.upload_icon lands in task B-7 (M2)")
