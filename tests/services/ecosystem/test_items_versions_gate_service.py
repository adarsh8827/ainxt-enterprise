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
    item_id, _ = upsert_legacy_pointer_item(
        namespace="acme/foo", item_type="skill", category="general",
        display_name="Foo", description="d",
        org_id="org-a", legacy_source="skills_pg", legacy_ref="skill-3",
    )
    version_id, _ = create_or_refresh_legacy_version(item_id=item_id, content_text="exact content", manifest={})

    from store.ecosystem_object_storage import get_ecosystem_object_storage

    db = SessionLocal()
    try:
        version = db.query(EcosystemItemVersion).filter(EcosystemItemVersion.id == version_id).one()
    finally:
        db.close()

    store = get_ecosystem_object_storage()
    assert store.get(version.object_key) == b"exact content"


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


def test_enqueue_gate_run_creates_pending_row():
    item_id, _ = upsert_legacy_pointer_item(
        namespace="acme/foo", item_type="skill", category="general",
        display_name="Foo", description="d",
        org_id="org-a", legacy_source="skills_pg", legacy_ref="skill-5",
    )
    version_id, _ = create_or_refresh_legacy_version(item_id=item_id, content_text="c", manifest={})
    gate_run_id = enqueue_gate_run(version_id, trigger="admin_provision")

    db = SessionLocal()
    try:
        run = db.query(EcosystemGateRun).filter(EcosystemGateRun.id == gate_run_id).one()
    finally:
        db.close()
    assert run.verdict == "pending"
    assert run.version_id == version_id
    assert run.trigger == "admin_provision"
