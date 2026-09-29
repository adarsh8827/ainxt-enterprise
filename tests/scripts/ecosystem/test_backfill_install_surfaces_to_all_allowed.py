# SPDX-License-Identifier: MIT
# ============================================================
# Per-surface toggles round (2026-09-29): backfill for every EcosystemInstall
# row still sitting at whatever narrower surfaces list a since-removed
# manual toggle (or an old, narrower create-time default) left it with --
# see scripts/ecosystem/backfill_install_surfaces_to_all_allowed.py's own
# module docstring. Tier-2, real Postgres, same construction pattern as
# the sibling trust-tier/display-name backfill tests in this directory.
# ============================================================

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from db.database import SessionLocal
from db.models import EcosystemInstall
from scripts.ecosystem.backfill_install_surfaces_to_all_allowed import (
    backfill_install_surfaces_to_all_allowed,
    find_backfill_candidates,
)
from services.ecosystem import create_service, installs_service

# No EcosystemOrgProduct entitlement row exists for this org -- config_service.
# _resolve_product() falls back to the seeded 'enterprise' profile, whose
# enabled_surfaces is ["chat", "agent_studio", "desktop"] (db/migrate.py
# Part AD1) -- the same fixed target every test below reasons about.
_ORG_ID = "backfill-surfaces-test-org"
_ENTERPRISE_SURFACES = ["chat", "agent_studio", "desktop"]


def _mock_ethics_pass():
    return patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}')


def _make_install(namespace: str, *, instructions: str = "x", initial_surfaces: list[str]) -> str:
    with _mock_ethics_pass():
        item = create_service.create_via_write(
            org_id=_ORG_ID, created_by="backfill-surfaces-test-user", item_type="skill", namespace=namespace,
            display_name="Backfill Surfaces Test", description="d", category="productivity", tags=[],
            license="MIT", content={"instructions": instructions, "files": []}, surfaces=initial_surfaces,
        )
    # create_via_write's own "ui_add" trigger auto-installs the creator
    # privately -- but with a POSSIBLY gate-verdict-dependent outcome (see
    # this session's own disclosed note about fast-path/full-gate
    # non-determinism under concurrent load). Installing directly via
    # installs_service.install(), for a fresh installed_for identity, is
    # deterministic and matches this test file's own sibling backfill
    # tests' preference for direct model/service construction over
    # trusting the async gate.
    install_row = installs_service.install(
        item_id=item["item_id"], version_id=item["version_id"], org_id=_ORG_ID,
        installed_by="backfill-surfaces-test-user", installed_for=f"backfill-surfaces-test-user-{uuid.uuid4().hex[:8]}",
        surfaces=initial_surfaces, scope="private", origin="added",
    )
    return install_row["install_id"]


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    db = SessionLocal()
    try:
        db.query(EcosystemInstall).filter(EcosystemInstall.org_id == _ORG_ID).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_finds_and_fixes_an_install_narrower_than_the_orgs_allowed_surfaces():
    install_id = _make_install(f"backfill-surfaces-test/narrow-{uuid.uuid4().hex[:8]}", initial_surfaces=["chat"])

    db = SessionLocal()
    try:
        candidates = find_backfill_candidates(db)
        assert install_id in [c[0] for c in candidates]

        fixed = backfill_install_surfaces_to_all_allowed(db)
        db.commit()
        assert fixed >= 1

        row = db.query(EcosystemInstall).filter(EcosystemInstall.id == install_id).one()
        assert sorted(row.surfaces) == sorted(_ENTERPRISE_SURFACES)
    finally:
        db.close()


def test_never_needs_to_touch_an_install_already_at_the_full_allowed_set():
    install_id = _make_install(
        f"backfill-surfaces-test/already-full-{uuid.uuid4().hex[:8]}", initial_surfaces=_ENTERPRISE_SURFACES,
    )

    db = SessionLocal()
    try:
        candidates = find_backfill_candidates(db)
        assert install_id not in [c[0] for c in candidates]

        backfill_install_surfaces_to_all_allowed(db)
        db.commit()

        row = db.query(EcosystemInstall).filter(EcosystemInstall.id == install_id).one()
        assert sorted(row.surfaces) == sorted(_ENTERPRISE_SURFACES)  # unchanged
    finally:
        db.close()


def test_respects_the_compatibility_exception_for_a_tool_dependent_item():
    # A tool-dependent item (real trigger phrase, compatibility.py's own
    # _TOOL_PHRASE_PATTERNS) that somehow ended up with "chat" in its
    # surfaces (e.g. from before the compatibility exception was enforced
    # at install time too) must land WITHOUT "chat", never with it --
    # the migration is "all allowed surfaces MINUS the exception", not
    # "all allowed surfaces, full stop".
    install_id = _make_install(
        f"backfill-surfaces-test/tool-dependent-{uuid.uuid4().hex[:8]}",
        instructions="run the following command to set things up",
        initial_surfaces=["chat", "desktop"],
    )

    db = SessionLocal()
    try:
        candidates = find_backfill_candidates(db)
        assert install_id in [c[0] for c in candidates]

        backfill_install_surfaces_to_all_allowed(db)
        db.commit()

        row = db.query(EcosystemInstall).filter(EcosystemInstall.id == install_id).one()
        assert "chat" not in row.surfaces
        assert sorted(row.surfaces) == sorted(["agent_studio", "desktop"])
    finally:
        db.close()


def test_idempotent_second_run_fixes_nothing_new():
    _make_install(f"backfill-surfaces-test/idempotent-{uuid.uuid4().hex[:8]}", initial_surfaces=["chat"])

    db = SessionLocal()
    try:
        first_run = backfill_install_surfaces_to_all_allowed(db)
        db.commit()
        assert first_run >= 1

        second_run = backfill_install_surfaces_to_all_allowed(db)
        db.commit()
        assert second_run == 0
    finally:
        db.close()
