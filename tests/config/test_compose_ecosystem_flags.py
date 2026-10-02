# SPDX-License-Identifier: MIT
# ============================================================
# Task B-7: the ecosystem marketplace's feature flags were never reachable
# from a real deployment. tests/config/test_ecosystem_flags.py already
# proves core.config resolves each flag's Python-side default correctly —
# but docker-compose.yml's environment: blocks are an explicit allowlist
# (documented repeatedly elsewhere in this file — FERNET_KEY, EMBED_SVC_URL,
# HOD_APPROVAL_ENABLED, CODEWIKI_*, ...): a var with no corresponding line
# in a service's environment: block never reaches that container's process
# at all, no matter what .env sets. This file proves the allowlist gap is
# closed for gateway/gate-worker, and stays closed under drift.
# ============================================================

from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

_COMPOSE_YML = Path(__file__).resolve().parents[2] / "docker-compose.yml"


class ComposeService(BaseModel):
    model_config = ConfigDict(frozen=True)

    environment: dict[str, str] = Field(default_factory=dict)


class ComposeConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    services: dict[str, ComposeService]


def _rendered_config() -> ComposeConfig:
    # Deliberately whatever .env/override the environment this runs in
    # already has -- this only proves the KEY is allowlisted (reaches the
    # container at all), not any particular resolved value, which depends
    # on ambient .env/docker-compose.override.yml a developer may have.
    rendered = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        check=True, capture_output=True, text=True,
    )
    return ComposeConfig.model_validate_json(rendered.stdout)


def test_gateway_environment_allowlists_ecosystem_flags():
    config = _rendered_config()
    gateway = config.services["gateway"]
    for key in (
        "ENABLE_ECOSYSTEM_MARKETPLACE",
        "ECOSYSTEM_CHAT_SKILLS",
        "ECOSYSTEM_TYPE_PLUGIN",
        "ECOSYSTEM_TYPE_MCP",
        "ECOSYSTEM_TYPE_CONNECTOR",
        "ECOSYSTEM_OBJECT_STORAGE_BACKEND",
        "ECOSYSTEM_CONNECTOR_REGISTRY_BRIDGE",
        "COMPLIANCE_SERVICE_ENABLED",
        # Connectors+Plugins phase (2026-09-30) -- both read at gateway-
        # process runtime (routers/ecosystem_connectors_router.py,
        # mcp/ecosystem_tool_calling.py). Added after a real gap: these were
        # defined in core/config.py and set in .env but never reached the
        # container because this allowlist test itself was never updated to
        # cover them either -- the same class of silent-no-op this whole
        # file exists to catch.
        "ECOSYSTEM_CREDENTIAL_BROKER",
        "ECOSYSTEM_TOOL_CALLING",
    ):
        assert key in gateway.environment, f"gateway is missing {key} from its environment: allowlist"


def test_gateway_does_not_allowlist_the_skills_pg_and_agentstudio_bridge_flags():
    """ECOSYSTEM_LEGACY_BRIDGE_SKILLS_PG / ECOSYSTEM_LEGACY_BRIDGE_AGENTSTUDIO
    are read only by the standalone scripts/ecosystem/backfill_legacy_items.py
    one-off script -- routers/ecosystem_router.py's list_installs() always
    returns legacy_items=[] today regardless of either flag ("not done this
    pass" per that function's own comment), so allowlisting them here would
    be inert cruft implying request-time behavior that doesn't exist yet.
    Run the backfill script directly (with the flag set in whatever shell
    invokes it) to actually mirror AgentStudio/skills_pg -- not via this
    container's own environment.

    ECOSYSTEM_LEGACY_BRIDGE_CONNECTORS / ECOSYSTEM_LEGACY_BRIDGE_COWORK_ROLES
    used to be grouped with these two under the same "not allowlisted"
    assumption -- that stopped being true 2026-10-02 (db/migrate.py's Part
    AE8 now reads both directly on every real gateway boot, a genuine
    allowlist requirement, not inert cruft) -- see
    test_gateway_allowlists_the_connector_and_cowork_role_bridge_flags below
    for the now-correct, opposite assertion covering that pair."""
    config = _rendered_config()
    gateway = config.services["gateway"]
    assert "ECOSYSTEM_LEGACY_BRIDGE_SKILLS_PG" not in gateway.environment
    assert "ECOSYSTEM_LEGACY_BRIDGE_AGENTSTUDIO" not in gateway.environment


def test_gateway_allowlists_the_connector_and_cowork_role_bridge_flags():
    """2026-10-02: real gap found live -- connector_definitions got seeded
    on every boot (db/migrate.py's Part S16, unconditional) but nothing
    ever bridged those rows into ecosystem_items (the table Discover
    actually reads) except a manual, standalone
    scripts/ecosystem/backfill_legacy_items.py run, so a fresh install's
    Connectors Discover stayed empty until someone remembered to run that
    script by hand. Part AE8 now calls that bridge directly on every boot,
    gated by these two flags read from THIS container's own environment --
    unlike SKILLS_PG/AGENTSTUDIO above, this is real, request-independent
    boot-time behavior, so the allowlist entries are required, not cruft."""
    config = _rendered_config()
    gateway = config.services["gateway"]
    assert "ECOSYSTEM_LEGACY_BRIDGE_CONNECTORS" in gateway.environment
    assert "ECOSYSTEM_LEGACY_BRIDGE_COWORK_ROLES" in gateway.environment


def test_gate_worker_environment_allowlists_compliance_and_storage_flags():
    """The gate's static_safety_stage runs inside the gate-worker process
    (workers/ecosystem_gate_worker.py's run_gate()) -- without this key in
    gate-worker's own allowlist, COMPLIANCE_SERVICE_ENABLED=true in .env
    had no effect there even though it worked for other, unrelated,
    gateway-process-only consumers of the same flag. run_gate() also calls
    store.ecosystem_object_storage.get_ecosystem_object_storage() directly,
    so ECOSYSTEM_OBJECT_STORAGE_BACKEND needs the same allowlist entry.
    ENABLE_ECOSYSTEM_MARKETPLACE is deliberately NOT added here: nothing in
    workers/ecosystem_gate_worker.py or services/ecosystem/gate_service.py
    reads it (confirmed by a repo-wide grep) -- only gateway.py's router
    mounting and db/migrate.py (which only ever runs inside the gateway
    container's own boot command) do."""
    config = _rendered_config()
    gate_worker = config.services["gate-worker"]
    assert "COMPLIANCE_SERVICE_ENABLED" in gate_worker.environment
    assert "ECOSYSTEM_OBJECT_STORAGE_BACKEND" in gate_worker.environment


def test_gate_worker_does_not_allowlist_the_item_type_flags():
    """services/ecosystem/gate/mcp_connector_stage.py is an always-pass
    no-op today -- ECOSYSTEM_TYPE_MCP/ECOSYSTEM_TYPE_CONNECTOR appear only
    in a comment about a *future* phase there, never a real os.getenv read
    (confirmed by reading the file). Allowlisting them in gate-worker would
    be inert cruft implying they gate real behavior in this process."""
    config = _rendered_config()
    gate_worker = config.services["gate-worker"]
    for key in ("ECOSYSTEM_TYPE_PLUGIN", "ECOSYSTEM_TYPE_MCP", "ECOSYSTEM_TYPE_CONNECTOR"):
        assert key not in gate_worker.environment


def test_agentstudio_only_flags_are_deliberately_absent_from_the_committed_yaml():
    """ECOSYSTEM_AGENTSTUDIO_SKILLS / ECOSYSTEM_AGENTSTUDIO_MISSING_DEP are
    read only by AgentStudio/backend/app/engine/native_engine.py -- a
    separate, independently-deployed application (CLAUDE.md: "not mounted
    into the main gateway.py") -- never by gateway.py or anything running
    in the gate-worker container. Listing them in either service's
    environment: block here would be inert, misleading cruft implying
    they're wired up in this compose file when they are not. This test is
    a deliberate guard against that regressing back into the *committed*
    docker-compose.yml without someone re-reading why it was left out --
    a static-text check on the tracked file, not the rendered config (a
    developer's own untracked docker-compose.override.yml may legitimately
    add either key for local AgentStudio-co-located testing, which is none
    of this test's business and must not fail it)."""
    text = _COMPOSE_YML.read_text(encoding="utf-8")
    lines_outside_comments = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
    body = "\n".join(lines_outside_comments)
    assert "ECOSYSTEM_AGENTSTUDIO_SKILLS:" not in body
    assert "ECOSYSTEM_AGENTSTUDIO_MISSING_DEP:" not in body


def test_new_ecosystem_flags_default_to_off_in_the_committed_yaml():
    """Static text check, deliberately independent of whatever ambient
    .env/override a developer's machine has (which is exactly what makes
    test_*_allowlists_* above unable to assert a specific resolved value)
    -- proves the actual fallback literal committed to docker-compose.yml
    is 'false' for every flag task B-7 added, so a fresh clone with no
    .env override truly starts with the marketplace off end to end."""
    text = _COMPOSE_YML.read_text(encoding="utf-8")
    assert "ENABLE_ECOSYSTEM_MARKETPLACE: ${ENABLE_ECOSYSTEM_MARKETPLACE:-false}" in text
    assert "ECOSYSTEM_CHAT_SKILLS:        ${ECOSYSTEM_CHAT_SKILLS:-false}" in text
    assert "ECOSYSTEM_TYPE_PLUGIN:    ${ECOSYSTEM_TYPE_PLUGIN:-false}" in text
    assert "ECOSYSTEM_TYPE_MCP:       ${ECOSYSTEM_TYPE_MCP:-false}" in text
    assert "ECOSYSTEM_TYPE_CONNECTOR: ${ECOSYSTEM_TYPE_CONNECTOR:-false}" in text
    assert "ECOSYSTEM_CONNECTOR_REGISTRY_BRIDGE: ${ECOSYSTEM_CONNECTOR_REGISTRY_BRIDGE:-false}" in text
    assert text.count("ECOSYSTEM_OBJECT_STORAGE_BACKEND: ${ECOSYSTEM_OBJECT_STORAGE_BACKEND:-local}") == 2
    assert text.count("COMPLIANCE_SERVICE_ENABLED:   ${COMPLIANCE_SERVICE_ENABLED:-false}") == 1
    assert text.count("COMPLIANCE_SERVICE_ENABLED: ${COMPLIANCE_SERVICE_ENABLED:-false}") == 1
