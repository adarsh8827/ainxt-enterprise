# SPDX-License-Identifier: MIT
# ============================================================
# ECOSYSTEM MARKETPLACE — content-hash-addressed object storage
#
# Distinct from core/storage.py's ObjectStorage (which is UUID-path-addressed,
# silently falls back MinIO->local, and serves chat attachments/generated
# docs). This store is content-addressed: the object's key IS its sha256
# hash, so re-uploading identical content is a no-op and every read can
# verify the bytes it returns actually match the key it was asked for —
# required by docs/ecosystem/ECOSYSTEM_PLAN.md's immutable-version design
# (ecosystem_item_versions.content_hash/object_key, SKILLS_PHASE_PLAN.md
# task B-2). The backend never falls back silently between local/S3 — it is
# whichever ECOSYSTEM_OBJECT_STORAGE_BACKEND says, so behavior is
# deterministic and testable, not "try one, quietly try the other."
#
# Usage:
#   from store.ecosystem_object_storage import get_ecosystem_object_storage
#   store = get_ecosystem_object_storage()
#   key = store.put(content_bytes)          # sha256 hex digest
#   data = store.get(key)                   # raises on missing/corrupted
# ============================================================

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Protocol


class ObjectNotFoundError(Exception):
    """No object exists under the given key."""


class ObjectCorruptedError(Exception):
    """The stored/retrieved bytes do not hash to the requested key."""


def content_hash(content: bytes) -> str:
    """sha256 hex digest — the canonical object_key for a given payload."""
    return hashlib.sha256(content).hexdigest()


class EcosystemObjectStorage(Protocol):
    def put(self, content: bytes) -> str:
        """Persist content, return its object_key (sha256 hex digest)."""
        ...

    def get(self, object_key: str) -> bytes:
        """Return the content for object_key.

        Raises ObjectNotFoundError if no object exists under that key, or
        ObjectCorruptedError if the stored bytes no longer hash to it.
        """
        ...

    def exists(self, object_key: str) -> bool:
        ...


class LocalFilesystemEcosystemObjectStorage:
    """Default backend. Layout: <base_dir>/<key[:2]>/<key> (git-style sharding,
    so a large catalog doesn't put tens of thousands of files in one directory).
    """

    def __init__(self, base_dir: str | None = None):
        self._base_dir = Path(
            base_dir or os.getenv("ECOSYSTEM_OBJECT_STORAGE_LOCAL_DIR", "storage/ecosystem_objects")
        )
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, object_key: str) -> Path:
        return self._base_dir / object_key[:2] / object_key

    def put(self, content: bytes) -> str:
        key = content_hash(content)
        path = self._path_for(key)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(".tmp")
            tmp_path.write_bytes(content)
            tmp_path.replace(path)  # atomic on both POSIX and Windows NTFS
        return key

    def get(self, object_key: str) -> bytes:
        path = self._path_for(object_key)
        if not path.exists():
            raise ObjectNotFoundError(f"no ecosystem object found for key {object_key!r}")
        data = path.read_bytes()
        if content_hash(data) != object_key:
            raise ObjectCorruptedError(
                f"object at key {object_key!r} does not hash to its own key — possible corruption or tampering"
            )
        return data

    def exists(self, object_key: str) -> bool:
        return self._path_for(object_key).exists()


class S3EcosystemObjectStorage:
    """S3/MinIO-compatible backend, behind the same interface. Uses the
    `minio` client (already a dependency of core/storage.py) rather than
    introducing a second S3 SDK.
    """

    def __init__(
        self,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        secure: bool | None = None,
        bucket: str | None = None,
    ):
        from minio import Minio

        self._bucket = bucket or os.getenv("ECOSYSTEM_OBJECT_STORAGE_S3_BUCKET", "ecosystem-items")
        self._client = Minio(
            endpoint or os.getenv("MINIO_ENDPOINT", ""),
            access_key=access_key or os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
            secret_key=secret_key or os.getenv("MINIO_SECRET_KEY", "minioadmin"),
            secure=secure if secure is not None else os.getenv("MINIO_SECURE", "false").lower() == "true",
        )
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    def put(self, content: bytes) -> str:
        import io

        key = content_hash(content)
        if not self.exists(key):
            self._client.put_object(self._bucket, key, io.BytesIO(content), len(content))
        return key

    def get(self, object_key: str) -> bytes:
        from minio.error import S3Error

        try:
            response = self._client.get_object(self._bucket, object_key)
            try:
                data = response.read()
            finally:
                response.close()
                response.release_conn()
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                raise ObjectNotFoundError(f"no ecosystem object found for key {object_key!r}") from exc
            raise
        if content_hash(data) != object_key:
            raise ObjectCorruptedError(
                f"object at key {object_key!r} does not hash to its own key — possible corruption or tampering"
            )
        return data

    def exists(self, object_key: str) -> bool:
        from minio.error import S3Error

        try:
            self._client.stat_object(self._bucket, object_key)
            return True
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                return False
            raise


def _running_inside_a_container() -> bool:
    """Standard, zero-config Docker marker file. A dedicated function
    (rather than an inline Path("/.dockerenv").exists() call) so tests can
    monkeypatch this one name instead of the whole pathlib.Path class --
    patching Path.exists globally corrupted it for the rest of the test
    session on Windows in an earlier version of this test (a real,
    self-inflicted bug, found and fixed the same day)."""
    return Path("/.dockerenv").exists()


def assert_local_storage_root_is_mounted() -> None:
    """Fail fast, with a clear error, before any entry point that creates
    ecosystem items OUTSIDE a normal gateway request (an admin CLI import
    command, a one-off script) does real work against the "local" object
    storage backend.

    Real incident, 2026-09-28: a host-side import script wrote 8 real
    starter-catalog skills' object bytes to a plain host directory
    (LocalFilesystemEcosystemObjectStorage's relative default resolved
    against that script's own cwd) that the gate-worker container's
    mounted `ainxt_uploads` volume could never see -- gating them failed
    fast with a clean ObjectNotFoundError once retried, but only after
    hours of investigating what first looked like an unrelated hang. See
    docs/ecosystem/design/CHANGELOG.md's dated entry for the full account.

    Two checks, both required for the "local" backend:
    1. ECOSYSTEM_OBJECT_STORAGE_LOCAL_DIR (or its default) must be an
       absolute path -- a relative one resolves differently depending on
       the calling process's cwd, which is exactly how the incident above
       happened. docker-compose.yml sets this explicitly now.
    2. The process must actually be running inside a container (checked
       via /.dockerenv, the standard, zero-config Docker marker file) --
       an absolute path alone doesn't prove anything if it's an absolute
       path on the HOST that just happens to exist.

    A no-op for the "s3"/MinIO backend, which has no cwd-dependent local
    path to get wrong.
    """
    from core.config import ECOSYSTEM_OBJECT_STORAGE_BACKEND

    if ECOSYSTEM_OBJECT_STORAGE_BACKEND != "local":
        return

    base_dir = os.getenv("ECOSYSTEM_OBJECT_STORAGE_LOCAL_DIR", "storage/ecosystem_objects")
    if not Path(base_dir).is_absolute():
        raise RuntimeError(
            f"ECOSYSTEM_OBJECT_STORAGE_LOCAL_DIR is not an absolute path (got {base_dir!r}). "
            "Refusing to run: a relative path resolves differently depending on the calling "
            "process's current working directory -- this is exactly how 8 real items' object "
            "files ended up written to a host directory the gate-worker container could never "
            "see (docs/ecosystem/design/CHANGELOG.md's 2026-09-28 entry). docker-compose.yml "
            "already sets this to /app/storage/ecosystem_objects for gateway/gate-worker -- "
            "run this command inside that container instead of on the bare host."
        )
    if not _running_inside_a_container():
        raise RuntimeError(
            "Refusing to run outside a container. This command must be invoked via "
            "`docker exec ainxt-gateway ...` (or an equivalent container context) so it shares "
            "the same mounted object-storage volume the gate-worker actually reads from -- "
            "running it directly on the host writes objects to a location the gate-worker can "
            "never see, even if ECOSYSTEM_OBJECT_STORAGE_LOCAL_DIR is set to an absolute path."
        )


def get_ecosystem_object_storage() -> EcosystemObjectStorage:
    """Factory selecting the backend named by ECOSYSTEM_OBJECT_STORAGE_BACKEND
    (core/config.py, task B-0). No silent fallback between backends — an
    unrecognized value is a configuration error, not a guess.
    """
    from core.config import ECOSYSTEM_OBJECT_STORAGE_BACKEND

    if ECOSYSTEM_OBJECT_STORAGE_BACKEND == "local":
        return LocalFilesystemEcosystemObjectStorage()
    if ECOSYSTEM_OBJECT_STORAGE_BACKEND == "s3":
        return S3EcosystemObjectStorage()
    raise ValueError(
        f"Unknown ECOSYSTEM_OBJECT_STORAGE_BACKEND={ECOSYSTEM_OBJECT_STORAGE_BACKEND!r}, expected 'local' or 's3'"
    )
