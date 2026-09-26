# SPDX-License-Identifier: MIT
# ============================================================
# Shared exception types for the ecosystem marketplace service layer.
#
# Framework-agnostic on purpose (docs/ecosystem/SKILLS_PHASE_PLAN.md task
# B-3): these carry no HTTP status code. routers/ecosystem_router.py (once
# it exists, task B-6 onward) is responsible for catching these and mapping
# them to the wire error codes in docs/ecosystem/CONTRACTS.md §3.
# ============================================================

from __future__ import annotations


class EcosystemError(Exception):
    """Base class for every ecosystem-service exception."""


class NamespaceInvalidError(EcosystemError):
    """The namespace's publisher segment doesn't resolve, or the caller
    doesn't own it. Maps to CONTRACTS.md §3's NAMESPACE_INVALID."""


class PolicyForbiddenError(EcosystemError):
    """A real, existing resource the caller isn't entitled/permitted to
    use. Maps to CONTRACTS.md §3's POLICY_FORBIDDEN."""


class NotFoundError(EcosystemError):
    """The resource itself doesn't exist. Maps to a 404 / NOT_FOUND."""
