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


def test_get_effective_capabilities_response_conforms_to_capabilities_response_model():
    surface = "chat"
    skills = resolver_service.get_effective_capabilities("default", f"user-{uuid.uuid4().hex[:8]}", surface)
    envelope = {"surface": surface, "skills": skills, "plugins": [], "connectors": [], "mcp_tools": []}
    validated = CapabilitiesResponse(**envelope)
    assert validated.surface == "chat"
