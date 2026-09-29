# SPDX-License-Identifier: MIT
# ============================================================
# Contract conformance tests (task B-17, M3). CONTRACTS.md §16 point 1:
# "Backend response schemas validated against the generated OpenAPI spec
# on every PR touching routers/ecosystem_router.py or the service layer."
# Real Postgres — the service-layer functions this actually calls are
# the same DB-backed functions test_config_service.py/
# test_resolver_service.py exercise directly.
# ============================================================

from __future__ import annotations

import uuid

from routers.ecosystem_router import CapabilitiesResponse, ConfigResponse
from services.ecosystem import config_service, resolver_service


def test_get_effective_config_response_conforms_to_config_response_model():
    result = config_service.get_effective_config("default", f"user-{uuid.uuid4().hex[:8]}", None)
    # Raises pydantic.ValidationError (failing the test) if the service
    # layer's actual response shape has drifted from the schema
    # routers/ecosystem_router.py declares (and scripts/ecosystem/
    # generate_openapi.py generates docs/ecosystem/openapi.json from).
    validated = ConfigResponse(**result)
    assert validated.product == "enterprise"


def test_caller_permissions_reflects_the_caller_not_a_default():
    # A real, found-live bug: CreateForm.tsx/AddDialog.tsx were gating on
    # features.provisioning/share (per-product, same for every caller of
    # that product) instead of a real per-caller signal. caller_permissions
    # is that signal -- computed fresh from whatever set is passed in,
    # never a fixed True/False regardless of caller.
    #
    # can_provision stays pure-RBAC. can_share is no longer -- the sharing-
    # policy correction (2026-09-27) made it ALSO true whenever the org's
    # own who_can_share policy is "all_users" (the default), independent of
    # marketplace:share/marketplace:provision -- see config_service.py's
    # get_effective_config().
    no_perms = config_service.get_effective_config("default", "user-no-perms", None, caller_permissions=set())
    assert no_perms["caller_permissions"] == {"can_share": True, "can_provision": False, "can_admin_surfaces": False}

    full_perms = config_service.get_effective_config(
        "default", "user-full-perms", None, caller_permissions={"marketplace:share", "marketplace:provision"},
    )
    assert full_perms["caller_permissions"] == {"can_share": True, "can_provision": True, "can_admin_surfaces": False}
    # features.provisioning is unaffected -- still the product-level value,
    # not something caller_permissions overwrites.
    assert full_perms["features"]["provisioning"] == no_perms["features"]["provisioning"]


def test_can_share_is_false_with_no_permissions_when_the_org_restricts_sharing_to_admins():
    from services.ecosystem import policy_service

    org_id = "org-share-admins-only-contract-test"
    policy_service.set_policy(org_id, who_can_share="admins_only", updated_by="test-admin")

    no_perms = config_service.get_effective_config(org_id, "user-no-perms", None, caller_permissions=set())
    assert no_perms["caller_permissions"] == {"can_share": False, "can_provision": False, "can_admin_surfaces": False}

    admin = config_service.get_effective_config(
        org_id, "user-admin", None, caller_permissions={"marketplace:provision"},
    )
    assert admin["caller_permissions"]["can_share"] is True


def test_get_effective_capabilities_response_conforms_to_capabilities_response_model():
    surface = "chat"
    skills = resolver_service.get_effective_capabilities("default", f"user-{uuid.uuid4().hex[:8]}", surface)
    envelope = {"surface": surface, "skills": skills, "plugins": [], "connectors": [], "mcp_tools": []}
    validated = CapabilitiesResponse(**envelope)
    assert validated.surface == "chat"
