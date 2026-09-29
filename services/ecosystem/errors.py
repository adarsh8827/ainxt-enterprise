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


class LicenseNotAllowedError(EcosystemError):
    """The item's own declared license, or a dependency's, isn't
    MIT/Apache-2.0(-inclusive). Maps to CONTRACTS.md §3's LICENSE_NOT_ALLOWED.
    `stage` distinguishes the two call sites CONTRACTS.md §18 documents:
    'import_precheck' (before any fetch) or 'gate_license' (gate stage 2).
    """

    def __init__(self, message: str, *, stage: str, declared_license: str | None = None):
        super().__init__(message)
        self.stage = stage
        self.declared_license = declared_license


class LicenseAcknowledgementRequiredError(EcosystemError):
    """Tier 3 (docs/ecosystem/ECOSYSTEM_PLAN.md §11.2): a private-scope
    item/version's declared license isn't MIT/Apache-2.0 and the caller
    hasn't set `license_acknowledged=true` (declared, disallowed license),
    or the license is missing and the caller hasn't set `self_authored=true`
    (which would default it to MIT). Maps to CONTRACTS.md §3's
    LICENSE_ACKNOWLEDGEMENT_REQUIRED. `reason` is 'missing_license' or
    'acknowledgement_required' -- the two distinct UI prompts this maps to."""

    def __init__(self, message: str, *, reason: str, declared_license: str | None = None):
        super().__init__(message)
        self.reason = reason
        self.declared_license = declared_license


class LicenseNotAllowedByOrgPolicyError(EcosystemError):
    """Tier 2 (docs/ecosystem/ECOSYSTEM_PLAN.md §11.2): a license that isn't
    MIT/Apache-2.0 and also isn't on the target org's own
    `allowed_licenses_shared` list, at the exact point an item's scope
    would become shared/org/provisioned/required (creation-time
    provision_scope, share(), or the install-scope-validation check).
    Maps to CONTRACTS.md §3's LICENSE_NOT_ALLOWED_BY_ORG_POLICY."""

    def __init__(self, message: str, *, declared_license: str | None = None):
        super().__init__(message)
        self.declared_license = declared_license


class IconSourceNotAllowedError(EcosystemError):
    """An icon_url value pointed at something other than this instance's
    own object storage. Maps to CONTRACTS.md §3's ICON_SOURCE_NOT_ALLOWED."""


class ImportFetchError(EcosystemError):
    """External import (task I, pre-M3): the source could not be fetched
    at all — not found, malformed response, digest mismatch, SSRF-guard
    refusal, or a non-2xx the adapter doesn't otherwise special-case."""


class ImportRateLimitedError(EcosystemError):
    """External import: the source's API rate limit was hit. `retry_after`
    (seconds) comes from the response's own Retry-After header when
    present; None means the adapter couldn't determine one."""

    def __init__(self, message: str, *, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class PluginComposeInvalidError(EcosystemError):
    """Plugins phase (docs/ecosystem/PLUGINS_PHASE_PLAN.md item 1): a
    plugin's declared parts failed composition validation --
    services/ecosystem/plugin_manifest.py's validate_composition().
    `code` is one of PLUGIN_UNKNOWN_PART_KIND / PLUGIN_DUPLICATE_NAMESPACE /
    PLUGIN_PART_NOT_FOUND / PLUGIN_LICENSE_NOT_ALLOWED (CONTRACTS.md §20)."""

    def __init__(self, message: str, *, code: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class NeutralityViolationError(EcosystemError):
    """External import (real gap found 2026-09-29): create_via_import()'s
    github_repo/well_known fetch paths never ran
    catalog_crawler/neutrality_check.py's scan_for_ai_vendor_names() at
    all -- only the automated crawl.py pipeline did. An admin-driven
    one-off import (scripts/ecosystem/admin_import.py's starter batch)
    used this same function and landed a real violation
    (addyosmani/documentation-and-adrs, which names a specific AI
    assistant's own convention-file naming). Fail closed here too, same
    as every other create_via_import() rejection."""
