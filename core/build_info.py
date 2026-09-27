# SPDX-License-Identifier: MIT
# ============================================================
# Build-info visibility (real incident, 2026-09-27): a full day of manual
# testing ran against a 15-hour-stale ainxt-enterprise:local image, with
# no way to tell from the running app that it wasn't current. GIT_COMMIT/
# BUILD_TIME are baked in as env vars at image build time (Dockerfile's
# runtime stage, docker-compose.yml's gateway build.args -- .git/ is
# excluded from the build context via .dockerignore, so this is the only
# way this information reaches a running container). Read lazily (a
# function, not a module-level constant) so a `--reload` dev process
# picks up a changed env var without a restart, matching this codebase's
# own established convention elsewhere (e.g. core/factory_utils.py's
# resolve_factory_model()).
# ============================================================

from __future__ import annotations

import os


def get_build_info() -> dict[str, str]:
    """{"commit": <full sha or 'unknown'>, "built_at": <ISO8601 or 'unknown'>}.
    Admin-only exposure is the caller's job (services/ecosystem/config_service.py) --
    this function itself has no permission awareness."""
    return {
        "commit": os.getenv("GIT_COMMIT", "unknown"),
        "built_at": os.getenv("BUILD_TIME", "unknown"),
    }
