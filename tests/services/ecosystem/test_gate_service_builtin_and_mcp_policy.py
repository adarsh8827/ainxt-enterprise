# SPDX-License-Identifier: MIT
# ============================================================
# Policy fix (2026-09-30, user-directed): trust_tier="builtin" items
# (native connectors, built-in skills, Cowork-role plugins -- anything
# shipped in this repo) skip ethics/sandbox/supply_chain/static_safety/
# mcp_connector entirely and go straight to a real (not just cached)
# pass/warn/fail verdict from manifest+license alone. Admin-added remote
# MCP registrations (item_type="mcp_server", trust_tier != "builtin") run
# stage 7 (mcp_connector) for real but skip static_safety/supply_chain/
# sandbox always, and skip ethics unless the org's ethics_review_policy is
# explicitly "always". Every skipped stage still records a real
# stage_timings reason (Verification tab requirement) -- see
# services/ecosystem/gate_service.py's is_builtin/is_admin_mcp branches.
#
# Tier-2 -- real Postgres. Same synchronous-inline gate convention as
# test_gate_service_orchestrator.py (this package's conftest.py autouse
# fixture stands in for the real gate-worker consumer).
# ============================================================

from __future__ import annotations

from unittest.mock import patch

from db.database import SessionLocal
from db.models import EcosystemGateRun, EcosystemItemVersion
from services.ecosystem.gate_service import enqueue_gate_run
from services.ecosystem.items_service import upsert_legacy_pointer_item
from services.ecosystem.policy_service import set_policy
from services.ecosystem.versions_service import create_or_refresh_legacy_version


def _never_call_the_model(*_args, **_kwargs):
    raise AssertionError("ethics reviewer model call should never happen for this item")


def _make_item_and_version(*, item_type, trust_tier, legacy_ref, manifest=None, org_id="org-a"):
    item_id, _ = upsert_legacy_pointer_item(
        namespace=f"acme/{legacy_ref}", item_type=item_type, category="general",
        display_name=legacy_ref, description="a test item",
        org_id=org_id, legacy_source="connector_definitions", legacy_ref=legacy_ref,
        trust_tier=trust_tier,
    )
    version_id, _ = create_or_refresh_legacy_version(
        item_id=item_id, content_text="a test item",
        manifest=manifest or {"name": legacy_ref, "description": "a test item"},
    )
    return item_id, version_id


def test_builtin_item_resolves_without_ever_calling_the_ethics_reviewer():
    _, version_id = _make_item_and_version(item_type="connector", trust_tier="builtin", legacy_ref="builtin-conn-1")
    with patch("models.model_router.model_router.generate", side_effect=_never_call_the_model):
        gate_run_id = enqueue_gate_run(version_id, trigger="admin_provision", org_id="org-a")

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == version_id).one()
    finally:
        db.close()

    assert run.verdict == "pass"
    assert version.gate_verdict == "pass"
    for stage in ("static_safety", "supply_chain", "sandbox", "ethics", "mcp_connector"):
        assert run.stage_timings[stage]["status"] == "skipped"
        assert "built-in item" in run.stage_timings[stage]["reason"]
    assert run.stage_timings["manifest"]["status"] != "skipped"
    assert run.stage_timings["license"]["status"] != "skipped"


def test_admin_added_mcp_server_runs_stage_7_but_skips_ethics_by_default():
    _, version_id = _make_item_and_version(
        item_type="mcp_server", trust_tier="org", legacy_ref="admin-mcp-1",
        manifest={"name": "admin-mcp-1", "description": "a test item", "server_url": "https://8.8.8.8/mcp", "tools": []},
    )
    with patch("models.model_router.model_router.generate", side_effect=_never_call_the_model):
        gate_run_id = enqueue_gate_run(version_id, trigger="admin_provision", org_id="org-mcp-default")

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
    finally:
        db.close()

    assert run.stage_timings["static_safety"]["status"] == "skipped"
    assert run.stage_timings["supply_chain"]["status"] == "skipped"
    assert run.stage_timings["sandbox"]["status"] == "skipped"
    assert run.stage_timings["ethics"]["status"] == "skipped"
    assert "remote MCP registration" in run.stage_timings["static_safety"]["reason"]
    assert "only require ethics review" in run.stage_timings["ethics"]["reason"]
    # Stage 7 (mcp_connector) is the real check for this item type -- it
    # actually ran (not skipped), against a safe https:// URL and no tools.
    assert run.stage_timings["mcp_connector"]["status"] != "skipped"
    assert run.verdict in ("pass", "warn")


def test_admin_added_mcp_server_runs_ethics_when_org_policy_requires_it():
    org_id = "org-mcp-always"
    set_policy(org_id, ethics_review_policy="always", updated_by="test-admin")
    _, version_id = _make_item_and_version(
        item_type="mcp_server", trust_tier="org", legacy_ref="admin-mcp-2",
        manifest={"name": "admin-mcp-2", "description": "a test item", "server_url": "https://8.8.8.8/mcp", "tools": []},
    )
    with patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}'):
        gate_run_id = enqueue_gate_run(version_id, trigger="admin_provision", org_id=org_id)

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
    finally:
        db.close()

    assert run.stage_timings["ethics"]["status"] != "skipped"
    assert run.verdict == "pass"
