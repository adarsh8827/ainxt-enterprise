# SPDX-License-Identifier: MIT
# ============================================================
# Ecosystem marketplace object storage tests (task B-2).
#
# Local-filesystem backend: unit tests, no external services.
# S3/MinIO backend: Tier-2, requires a real MinIO/S3-compatible endpoint —
# skipped automatically when ECOSYSTEM_TEST_MINIO_ENDPOINT isn't set.
# ============================================================

from __future__ import annotations

import os
from pathlib import Path

import pytest

from store.ecosystem_object_storage import (
    LocalFilesystemEcosystemObjectStorage,
    ObjectCorruptedError,
    ObjectNotFoundError,
    assert_local_storage_root_is_mounted,
    content_hash,
    get_ecosystem_object_storage,
)


def test_put_then_get_is_byte_identical(tmp_path: Path):
    store = LocalFilesystemEcosystemObjectStorage(base_dir=str(tmp_path))
    payload = b"the quick brown fox jumps over the lazy dog"
    key = store.put(payload)
    assert store.get(key) == payload


def test_object_key_is_sha256_of_content(tmp_path: Path):
    store = LocalFilesystemEcosystemObjectStorage(base_dir=str(tmp_path))
    payload = b"skill manifest content"
    key = store.put(payload)
    assert key == content_hash(payload)


def test_put_is_idempotent_for_identical_content(tmp_path: Path):
    store = LocalFilesystemEcosystemObjectStorage(base_dir=str(tmp_path))
    payload = b"same content twice"
    key1 = store.put(payload)
    key2 = store.put(payload)
    assert key1 == key2
    # Only one file on disk for this key — no duplicate write.
    matches = list(tmp_path.rglob(key1))
    assert len(matches) == 1


def test_get_missing_key_raises_not_found(tmp_path: Path):
    store = LocalFilesystemEcosystemObjectStorage(base_dir=str(tmp_path))
    with pytest.raises(ObjectNotFoundError):
        store.get("0" * 64)


def test_tampered_object_fails_hash_check_on_read(tmp_path: Path):
    store = LocalFilesystemEcosystemObjectStorage(base_dir=str(tmp_path))
    key = store.put(b"original content")
    # Simulate on-disk corruption/tampering: overwrite the stored bytes
    # in place without going through put().
    on_disk_path = tmp_path / key[:2] / key
    on_disk_path.write_bytes(b"tampered content, different from the key")
    with pytest.raises(ObjectCorruptedError):
        store.get(key)


def test_exists_reflects_put(tmp_path: Path):
    store = LocalFilesystemEcosystemObjectStorage(base_dir=str(tmp_path))
    key = content_hash(b"not written yet")
    assert store.exists(key) is False
    store.put(b"not written yet")
    assert store.exists(key) is True


def test_sharded_layout_uses_first_two_hex_chars(tmp_path: Path):
    store = LocalFilesystemEcosystemObjectStorage(base_dir=str(tmp_path))
    key = store.put(b"shard check")
    assert (tmp_path / key[:2] / key).exists()


def test_factory_selects_local_backend_by_default(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ECOSYSTEM_OBJECT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("ECOSYSTEM_OBJECT_STORAGE_LOCAL_DIR", str(tmp_path))
    import importlib

    import core.config as config_module

    importlib.reload(config_module)
    store = get_ecosystem_object_storage()
    assert isinstance(store, LocalFilesystemEcosystemObjectStorage)


def test_factory_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("ECOSYSTEM_OBJECT_STORAGE_BACKEND", "azure_blob_typo")
    import importlib

    import core.config as config_module

    importlib.reload(config_module)
    with pytest.raises(ValueError):
        get_ecosystem_object_storage()
    # Restore the default so later tests in the same process aren't affected.
    monkeypatch.setenv("ECOSYSTEM_OBJECT_STORAGE_BACKEND", "local")
    importlib.reload(config_module)


# ── assert_local_storage_root_is_mounted (real incident, 2026-09-28) ───────
# A host-side script (outside any container) wrote 8 real starter-catalog
# skills' object bytes into a plain host directory the gate-worker
# container's mounted volume could never see. This guard is meant to be
# called by scripts/ecosystem/admin_import.py (or any future one-off admin
# import command) before doing any real work.

def _reload_config_with_backend(monkeypatch, backend: str):
    # core.config.ECOSYSTEM_OBJECT_STORAGE_BACKEND is a module-level constant
    # computed once at import time — monkeypatch.setenv alone doesn't change
    # it, same reload dance test_factory_selects_local_backend_by_default
    # above already does for the same reason.
    import importlib

    import core.config as config_module

    monkeypatch.setenv("ECOSYSTEM_OBJECT_STORAGE_BACKEND", backend)
    importlib.reload(config_module)


def test_relative_local_dir_is_refused_even_if_dockerenv_present(monkeypatch):
    _reload_config_with_backend(monkeypatch, "local")
    monkeypatch.setenv("ECOSYSTEM_OBJECT_STORAGE_LOCAL_DIR", "storage/ecosystem_objects")
    # Pretend we ARE in a container -- must still fail on the relative path
    # check first. Patches the dedicated helper, not the global pathlib.Path
    # class -- patching Path.exists itself corrupted it for the rest of the
    # test session on Windows (a real, self-inflicted bug, found the same day).
    monkeypatch.setattr("store.ecosystem_object_storage._running_inside_a_container", lambda: True)
    with pytest.raises(RuntimeError, match="absolute path"):
        assert_local_storage_root_is_mounted()


def test_absolute_local_dir_outside_a_container_is_refused(monkeypatch, tmp_path: Path):
    _reload_config_with_backend(monkeypatch, "local")
    monkeypatch.setenv("ECOSYSTEM_OBJECT_STORAGE_LOCAL_DIR", str(tmp_path))
    monkeypatch.setattr("store.ecosystem_object_storage._running_inside_a_container", lambda: False)
    with pytest.raises(RuntimeError, match="container"):
        assert_local_storage_root_is_mounted()


def test_absolute_local_dir_inside_a_container_passes(monkeypatch, tmp_path: Path):
    _reload_config_with_backend(monkeypatch, "local")
    monkeypatch.setenv("ECOSYSTEM_OBJECT_STORAGE_LOCAL_DIR", str(tmp_path))
    monkeypatch.setattr("store.ecosystem_object_storage._running_inside_a_container", lambda: True)
    assert_local_storage_root_is_mounted()  # must not raise


def test_s3_backend_is_never_checked_for_a_local_path_at_all(monkeypatch):
    _reload_config_with_backend(monkeypatch, "s3")
    monkeypatch.delenv("ECOSYSTEM_OBJECT_STORAGE_LOCAL_DIR", raising=False)
    try:
        assert_local_storage_root_is_mounted()  # must not raise -- no-op for s3
    finally:
        # core.config is process-global -- leaving it reloaded to "s3" would
        # leak into every other test in this session (same precedent as
        # test_factory_rejects_unknown_backend above).
        _reload_config_with_backend(monkeypatch, "local")


# ── Tier-2: real MinIO/S3-compatible endpoint ────────────────────────────────

_MINIO_ENDPOINT = os.getenv("ECOSYSTEM_TEST_MINIO_ENDPOINT")


@pytest.mark.skipif(not _MINIO_ENDPOINT, reason="ECOSYSTEM_TEST_MINIO_ENDPOINT not set — no MinIO available")
def test_s3_backend_put_then_get_is_byte_identical():
    from store.ecosystem_object_storage import S3EcosystemObjectStorage

    store = S3EcosystemObjectStorage(
        endpoint=_MINIO_ENDPOINT,
        access_key=os.getenv("ECOSYSTEM_TEST_MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("ECOSYSTEM_TEST_MINIO_SECRET_KEY", "minioadmin"),
        secure=False,
        bucket="ecosystem-items-test",
    )
    payload = b"tier-2 minio round trip"
    key = store.put(payload)
    assert store.get(key) == payload
    assert store.exists(key) is True


@pytest.mark.skipif(not _MINIO_ENDPOINT, reason="ECOSYSTEM_TEST_MINIO_ENDPOINT not set — no MinIO available")
def test_s3_backend_missing_key_raises_not_found():
    from store.ecosystem_object_storage import S3EcosystemObjectStorage

    store = S3EcosystemObjectStorage(
        endpoint=_MINIO_ENDPOINT,
        access_key=os.getenv("ECOSYSTEM_TEST_MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("ECOSYSTEM_TEST_MINIO_SECRET_KEY", "minioadmin"),
        secure=False,
        bucket="ecosystem-items-test",
    )
    with pytest.raises(ObjectNotFoundError):
        store.get("f" * 64)
