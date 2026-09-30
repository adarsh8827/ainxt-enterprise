# SPDX-License-Identifier: MIT
# ============================================================
# items_service / versions_service / gate_service tests (task B-3 skeleton,
# real functions pulled forward for task B-4). Tier-2 — real Postgres.
# ============================================================

from __future__ import annotations

from db.database import SessionLocal
from db.models import EcosystemGateRun, EcosystemItemVersion, EcosystemSource
from services.ecosystem.gate_service import enqueue_gate_run
from services.ecosystem.items_service import get_or_create_local_source, upsert_legacy_pointer_item
from services.ecosystem.versions_service import create_or_refresh_legacy_version


def test_get_or_create_local_source_is_idempotent():
    id1 = get_or_create_local_source("org-a")
    id2 = get_or_create_local_source("org-a")
    assert id1 == id2


def test_get_or_create_local_source_is_per_org():
    id_a = get_or_create_local_source("org-a")
    id_b = get_or_create_local_source("org-b")
    assert id_a != id_b

    db = SessionLocal()
    try:
        source_a = db.query(EcosystemSource).filter(EcosystemSource.id == id_a).one()
        source_b = db.query(EcosystemSource).filter(EcosystemSource.id == id_b).one()
    finally:
        db.close()
    assert source_a.org_id == "org-a"
    assert source_b.org_id == "org-b"
    assert source_a.kind == "local"


def test_upsert_legacy_pointer_item_is_idempotent_by_legacy_ref():
    item_id_1, created_1 = upsert_legacy_pointer_item(
        namespace="acme/foo", item_type="skill", category="general",
        display_name="Foo", description="A foo skill.",
        org_id="org-a", legacy_source="skills_pg", legacy_ref="skill-123",
    )
    item_id_2, created_2 = upsert_legacy_pointer_item(
        namespace="acme/foo", item_type="skill", category="general",
        display_name="Foo (renamed)", description="An updated foo skill.",
        org_id="org-a", legacy_source="skills_pg", legacy_ref="skill-123",
    )
    assert item_id_1 == item_id_2
    assert created_1 is True
    assert created_2 is False


def test_upsert_legacy_pointer_item_refreshes_trust_tier_on_an_existing_row():
    # Real gap found and fixed (2026-09-30): the update branch refreshed
    # display_name/description/category/source_id but silently ignored a
    # changed trust_tier argument, contradicting this function's own
    # docstring ("its metadata is refreshed in place") -- a native-
    # connector row created before its own caller started passing
    # trust_tier="builtin" stayed stuck at the "org" default forever.
    from db.models import EcosystemItem

    item_id_1, _ = upsert_legacy_pointer_item(
        namespace="acme/bar", item_type="connector", category="general",
        display_name="Bar", description="A bar connector.",
        org_id="org-a", legacy_source="connector_definitions", legacy_ref="bar-1",
        trust_tier="org",
    )
    item_id_2, created_2 = upsert_legacy_pointer_item(
        namespace="acme/bar", item_type="connector", category="general",
        display_name="Bar", description="A bar connector.",
        org_id="org-a", legacy_source="connector_definitions", legacy_ref="bar-1",
        trust_tier="builtin",
    )
    assert item_id_1 == item_id_2
    assert created_2 is False

    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id_1).one()
    finally:
        db.close()
    assert item.trust_tier == "builtin"


def test_upsert_legacy_pointer_item_defaults_scope_to_org_private():
    # Byte-identical to every caller before the `scope` param existed
    # (skills_pg/AgentStudio/Cowork-role bridges never pass it) --
    # org_private is correct for genuinely org-specific content.
    from db.models import EcosystemItem

    item_id, _ = upsert_legacy_pointer_item(
        namespace="acme/default-scope", item_type="skill", category="general",
        display_name="Default Scope", description="d",
        org_id="org-a", legacy_source="skills_pg", legacy_ref="default-scope-1",
    )
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).one()
    finally:
        db.close()
    assert item.scope == "org_private"


def test_upsert_legacy_pointer_item_refreshes_scope_on_an_existing_row():
    # Real gap found live (2026-09-30, via a real UI-reference-pack
    # screenshot capture pass): items_service.list_items()'s own Discover
    # filter only shows scope IN ('builtin','optional','central_index') --
    # the native-connector bridge's items had trust_tier="builtin" and a
    # real gate_verdict="pass" but were left at the default scope=
    # "org_private", making them structurally invisible to Discover for
    # every caller. Same "must refresh on a later run, not just at
    # creation" bug class as trust_tier above, fixed alongside it.
    from db.models import EcosystemItem

    item_id_1, _ = upsert_legacy_pointer_item(
        namespace="acme/baz", item_type="connector", category="general",
        display_name="Baz", description="A baz connector.",
        org_id="org-a", legacy_source="connector_definitions", legacy_ref="baz-1",
        trust_tier="org", scope="org_private",
    )
    item_id_2, created_2 = upsert_legacy_pointer_item(
        namespace="acme/baz", item_type="connector", category="general",
        display_name="Baz", description="A baz connector.",
        org_id="org-a", legacy_source="connector_definitions", legacy_ref="baz-1",
        trust_tier="builtin", scope="builtin",
    )
    assert item_id_1 == item_id_2
    assert created_2 is False

    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id_1).one()
    finally:
        db.close()
    assert item.scope == "builtin"


def test_a_builtin_scoped_bridged_connector_is_visible_in_discover_for_any_org():
    # The real, end-to-end regression this whole fix is about: a bridged
    # item with scope="builtin" must actually be RETURNED by list_items()
    # (Discover) for a caller in a DIFFERENT org than the one the bridge
    # ran under -- native connectors are platform-wide, not per-org.
    from services.ecosystem.items_service import list_items

    item_id, _ = upsert_legacy_pointer_item(
        namespace="acme/qux", item_type="connector", category="general",
        display_name="Qux", description="A qux connector.",
        org_id="default", legacy_source="connector_definitions", legacy_ref="qux-1",
        trust_tier="builtin", scope="builtin",
    )
    result = list_items(caller_org_id="some-other-org", item_type="connector")
    assert item_id in {i["id"] for i in result["items"]}


def test_upsert_legacy_pointer_item_uses_its_own_org_local_source():
    item_id, _ = upsert_legacy_pointer_item(
        namespace="acme/foo", item_type="skill", category="general",
        display_name="Foo", description="A foo skill.",
        org_id="org-a", legacy_source="skills_pg", legacy_ref="skill-abc",
    )
    expected_source_id = get_or_create_local_source("org-a")

    from db.models import EcosystemItem

    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).one()
    finally:
        db.close()
    assert item.source_id == expected_source_id


def test_upsert_legacy_pointer_item_defaults_license_to_mit():
    from db.models import EcosystemItem

    item_id, _ = upsert_legacy_pointer_item(
        namespace="acme/foo", item_type="skill", category="general",
        display_name="Foo", description="d",
        org_id="org-a", legacy_source="skills_pg", legacy_ref="skill-xyz",
    )
    db = SessionLocal()
    try:
        item = db.query(EcosystemItem).filter(EcosystemItem.id == item_id).one()
    finally:
        db.close()
    assert item.license == "MIT"


def test_create_or_refresh_legacy_version_is_idempotent_for_unchanged_content():
    item_id, _ = upsert_legacy_pointer_item(
        namespace="acme/foo", item_type="skill", category="general",
        display_name="Foo", description="d",
        org_id="org-a", legacy_source="skills_pg", legacy_ref="skill-1",
    )
    v1, created_1 = create_or_refresh_legacy_version(item_id=item_id, content_text="same content", manifest={})
    v2, created_2 = create_or_refresh_legacy_version(item_id=item_id, content_text="same content", manifest={})
    assert v1 == v2
    assert created_1 is True
    assert created_2 is False


def test_create_or_refresh_legacy_version_creates_new_version_on_content_change():
    item_id, _ = upsert_legacy_pointer_item(
        namespace="acme/foo", item_type="skill", category="general",
        display_name="Foo", description="d",
        org_id="org-a", legacy_source="skills_pg", legacy_ref="skill-2",
    )
    v1, _ = create_or_refresh_legacy_version(item_id=item_id, content_text="version one", manifest={})
    v2, created_2 = create_or_refresh_legacy_version(item_id=item_id, content_text="version two (edited)", manifest={})
    assert v1 != v2
    assert created_2 is True

    db = SessionLocal()
    try:
        count = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.item_id == item_id).count()
    finally:
        db.close()
    assert count == 2


def test_create_or_refresh_legacy_version_stores_byte_identical_content():
    # Legacy version content is stored via the shared envelope encoding
    # (versions_service.encode_envelope) every creation path uses, with
    # content_text folded into manifest["instructions"] — not stored raw —
    # so the gate orchestrator can scan a legacy version exactly the same
    # way it scans a write/upload/import version, no special-casing.
    item_id, _ = upsert_legacy_pointer_item(
        namespace="acme/foo", item_type="skill", category="general",
        display_name="Foo", description="d",
        org_id="org-a", legacy_source="skills_pg", legacy_ref="skill-3",
    )
    version_id, _ = create_or_refresh_legacy_version(item_id=item_id, content_text="exact content", manifest={})

    from services.ecosystem.versions_service import decode_envelope
    from store.ecosystem_object_storage import get_ecosystem_object_storage

    db = SessionLocal()
    try:
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == version_id).one()
    finally:
        db.close()

    store = get_ecosystem_object_storage()
    manifest, files = decode_envelope(store.get(version.object_key))
    assert manifest["instructions"] == "exact content"
    assert files == {}


def test_create_or_refresh_legacy_version_gate_verdict_starts_pending():
    item_id, _ = upsert_legacy_pointer_item(
        namespace="acme/foo", item_type="skill", category="general",
        display_name="Foo", description="d",
        org_id="org-a", legacy_source="skills_pg", legacy_ref="skill-4",
    )
    version_id, _ = create_or_refresh_legacy_version(item_id=item_id, content_text="c", manifest={})
    db = SessionLocal()
    try:
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == version_id).one()
    finally:
        db.close()
    assert version.gate_verdict == "pending"


def test_enqueue_gate_run_creates_a_row_matching_the_version_and_trigger():
    # Task B-9 (M2) wired real gate stages into the gate orchestrator
    # (run_gate()); item 2 (pre-M3) moved its invocation behind a real
    # queue (enqueue_gate_run() now only enqueues). This test's own
    # conftest.py autouse fixture runs that queue's consumer inline, so
    # the row still resolves synchronously here — the same way it would
    # in test_gate_service_orchestrator.py's more thorough suite, which is
    # where the actual verdict-resolution behavior (pass/warn/fail/pending
    # under various conditions) is tested, not duplicated here. This test
    # only checks the row's identity fields.
    from unittest.mock import patch

    item_id, _ = upsert_legacy_pointer_item(
        namespace="acme/enqueue-test", item_type="skill", category="general",
        display_name="Foo", description="d",
        org_id="org-a", legacy_source="skills_pg", legacy_ref="skill-5",
    )
    version_id, _ = create_or_refresh_legacy_version(item_id=item_id, content_text="c", manifest={})
    with patch("models.model_router.model_router.generate", return_value='{"verdict": "pass", "reason": "fine"}'):
        gate_run_id = enqueue_gate_run(version_id, trigger="admin_provision")

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
    finally:
        db.close()
    assert run.verdict in ("pass", "warn", "fail", "pending")
    assert run.version_id == version_id
    assert run.trigger == "admin_provision"
