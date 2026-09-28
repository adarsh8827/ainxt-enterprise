# SPDX-License-Identifier: MIT
# ============================================================
# Instance-level GitHub credential resolution (task I, pre-M3).
#
# ONE credential for the whole instance, set by an admin -- never a
# per-user token this phase (contrast core/platform_credentials.py's
# get_github_token(), which is deliberately per-user for the SDLC/index
# pipeline; that resolver is the wrong pattern here on purpose).
#
# Storage: a fine-grained, read-only GitHub personal access token in the
# GITHUB_IMPORT_TOKEN env var -- the existing "env var as platform secret"
# convention this codebase already uses for every other instance-level
# credential (core/platform_credentials.py's own GITLAB_TOKEN service-
# account fallback is the precedent), kept until a real SecretStore
# exists. A GitHub App installation (read-only public contents) is the
# preferred long-term shape per the task's own spec, but implementing App
# JWT-signing/installation-token exchange is a materially larger, separate
# piece of work than a bearer PAT header; documented here as the
# improvement path, not implemented, rather than half-building it.
#
# Without a configured token, adapters fall back to anonymous GitHub API
# access (unauthenticated rate limit: 60 requests/hour) -- see
# github_repo.py's Retry-After handling for what happens once that's hit.
# ============================================================

from __future__ import annotations

import os


def get_github_import_token() -> str | None:
    return os.getenv("GITHUB_IMPORT_TOKEN") or None


def auth_headers() -> dict[str, str]:
    token = get_github_import_token()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def configure_github_access_hint() -> str | None:
    """A message worth surfacing to admins when import calls are being
    made anonymously (no configured token) -- None when a token is set,
    since there's nothing to hint about."""
    if get_github_import_token():
        return None
    return (
        "No GITHUB_IMPORT_TOKEN is configured -- GitHub imports are running "
        "anonymously, limited to 60 requests/hour by GitHub's own unauthenticated "
        "rate limit. Set GITHUB_IMPORT_TOKEN to a fine-grained, read-only "
        "(public repository contents) personal access token to raise this limit."
    )
