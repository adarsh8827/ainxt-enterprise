# SPDX-License-Identifier: MIT
# ============================================================
# store/ecosystem_secret_store.py — Connectors/Plugins phase credential
# broker's per-org secret store. Real DB tests (ainxt_test), real
# encrypt/decrypt roundtrip via store/credential_vault.py's real
# FERNET_KEY-derived key (2026-09-30: no longer KeyService/CKMS -- see
# ecosystem_secret_store.py's own module docstring for why that was a
# real, root-caused bug, unconditionally unreachable whenever
# CKMS_ENABLED=false, the actual default for every OSS/local deployment).
# ============================================================

from __future__ import annotations

import uuid

import pytest

from store import ecosystem_secret_store as secret_store


@pytest.fixture
def org_a():
    return f"org-a-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def org_b():
    return f"org-b-{uuid.uuid4().hex[:8]}"


def _cleanup(org_id, kind, name, user_id=None):
    secret_store.delete_secret(org_id, kind, name, user_id=user_id)


def test_create_and_get_secret_value_roundtrips(org_a):
    name = f"token-{uuid.uuid4().hex[:8]}"
    try:
        row = secret_store.create_secret(org_a, "platform", name, "super-secret-value")
        assert row["org_id"] == org_a
        assert "ciphertext" not in row

        value = secret_store.get_secret_value(org_a, "platform", name)
        assert value == "super-secret-value"
    finally:
        _cleanup(org_a, "platform", name)


def test_duplicate_create_raises(org_a):
    name = f"dup-{uuid.uuid4().hex[:8]}"
    try:
        secret_store.create_secret(org_a, "platform", name, "v1")
        with pytest.raises(ValueError):
            secret_store.create_secret(org_a, "platform", name, "v2")
    finally:
        _cleanup(org_a, "platform", name)


def test_per_org_isolation_org_b_cannot_read_org_a_secret(org_a, org_b):
    name = f"shared-name-{uuid.uuid4().hex[:8]}"
    try:
        secret_store.create_secret(org_a, "platform", name, "org-a-secret")
        # Same secret name, different org — org_b must see nothing.
        assert secret_store.get_secret(org_b, "platform", name) is None
        assert secret_store.get_secret_value(org_b, "platform", name) is None
        # org_a can still create its OWN row under the same name — proves
        # isolation is real (not just a global uniqueness collision).
        row_b = secret_store.create_secret(org_b, "platform", name, "org-b-secret")
        assert row_b["org_id"] == org_b
        assert secret_store.get_secret_value(org_a, "platform", name) == "org-a-secret"
        assert secret_store.get_secret_value(org_b, "platform", name) == "org-b-secret"
    finally:
        _cleanup(org_a, "platform", name)
        _cleanup(org_b, "platform", name)


def test_update_and_rotate_secret(org_a):
    name = f"rot-{uuid.uuid4().hex[:8]}"
    try:
        secret_store.create_secret(org_a, "per_user", name, "v1", user_id="user-1")
        secret_store.update_secret(org_a, "per_user", name, "v2", user_id="user-1")
        assert secret_store.get_secret_value(org_a, "per_user", name, user_id="user-1") == "v2"

        rotated = secret_store.rotate_secret(org_a, "per_user", name, "v3", user_id="user-1")
        assert rotated["last_rotated"] is not None
        assert secret_store.get_secret_value(org_a, "per_user", name, user_id="user-1") == "v3"
    finally:
        _cleanup(org_a, "per_user", name, user_id="user-1")


def test_delete_secret(org_a):
    name = f"del-{uuid.uuid4().hex[:8]}"
    secret_store.create_secret(org_a, "platform", name, "v1")
    assert secret_store.delete_secret(org_a, "platform", name) is True
    assert secret_store.get_secret(org_a, "platform", name) is None
    assert secret_store.delete_secret(org_a, "platform", name) is False


def test_list_secrets_scoped_to_org(org_a, org_b):
    name = f"list-{uuid.uuid4().hex[:8]}"
    try:
        secret_store.create_secret(org_a, "platform", name, "v1")
        secret_store.create_secret(org_b, "platform", name, "v1")
        a_list = secret_store.list_secrets(org_a)
        assert any(s["name"] == name for s in a_list)
        assert all(s["org_id"] == org_a for s in a_list)
    finally:
        _cleanup(org_a, "platform", name)
        _cleanup(org_b, "platform", name)


def test_tampered_ciphertext_fails_to_decrypt(org_a):
    """Confirms the AES-GCM auth tag is real — flipping a ciphertext byte
    must raise, not silently return wrong plaintext."""
    from db.database import SessionLocal
    from db.models import EcosystemSecret

    name = f"tamper-{uuid.uuid4().hex[:8]}"
    try:
        secret_store.create_secret(org_a, "platform", name, "v1")
        db = SessionLocal()
        try:
            row = db.query(EcosystemSecret).filter(
                EcosystemSecret.org_id == org_a, EcosystemSecret.name == name
            ).first()
            iv_b64, ct_b64 = row.ciphertext.split(":")
            tampered_ct = ct_b64[:-4] + ("AAAA" if ct_b64[-4:] != "AAAA" else "BBBB")
            row.ciphertext = f"{iv_b64}:{tampered_ct}"
            db.commit()
        finally:
            db.close()

        with pytest.raises(Exception):
            secret_store.get_secret_value(org_a, "platform", name)
    finally:
        _cleanup(org_a, "platform", name)
